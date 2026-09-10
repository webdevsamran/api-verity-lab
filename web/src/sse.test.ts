/* The run-progress stream nothing had ever subscribed to.
 *
 * `GET /v1/runs/<id>/events` shipped with the job queue and no client read it.
 * The reason it stayed unread is worth recording: `EventSource`, the browser
 * API built for exactly this, cannot send an `Authorization` header, and every
 * route on this server is authenticated. The usual workaround puts the token
 * in the query string, where it reaches access logs, proxy logs, browser
 * history and `Referer` headers -- and a streaming request holds that URL open
 * for the length of the run.
 *
 * So the wire format is parsed here, and these tests are mostly about the
 * parser, because a framing bug in a stream shows up as data that is subtly
 * wrong rather than as an error.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { followRun, parseFrame, streamEvents } from "./sse";

function streamOf(chunks: string[], { status = 200 } = {}) {
  const encoder = new TextEncoder();
  return {
    ok: status < 400,
    status,
    body: {
      getReader() {
        let i = 0;
        return {
          read: () =>
            Promise.resolve(
              i < chunks.length
                ? { done: false, value: encoder.encode(chunks[i++]) }
                : { done: true, value: undefined },
            ),
          releaseLock() {},
        };
      },
    },
  } as unknown as Response;
}

function stub(chunks: string[], options?: { status?: number }) {
  const calls: { url: string; headers: Record<string, string> }[] = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({
      url,
      headers: (init?.headers ?? {}) as Record<string, string>,
    });
    return Promise.resolve(streamOf(chunks, options));
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("frame parsing", () => {
  it("reads the three fields the server sends", () => {
    const event = parseFrame('id: 4\nevent: progress\ndata: {"step":"diff"}');
    expect(event).toEqual({
      id: "4",
      event: "progress",
      data: '{"step":"diff"}',
    });
  });

  it("strips exactly one leading space from a value", () => {
    // Two spaces means the value really starts with one. Trimming would
    // silently rewrite indented content in a log line.
    expect(parseFrame("data:  indented")?.data).toBe(" indented");
  });

  it("joins multi-line data with newlines", () => {
    expect(parseFrame("data: one\ndata: two")?.data).toBe("one\ntwo");
  });

  it("defaults the event name to `message`", () => {
    expect(parseFrame("data: hello")?.event).toBe("message");
  });

  it("ignores a keep-alive comment", () => {
    expect(parseFrame(": ping")).toBeNull();
  });

  it("ignores a field it does not know", () => {
    expect(parseFrame("retry: 5000\ndata: x")?.data).toBe("x");
  });
});

describe("streaming", () => {
  it("dispatches one event per frame", async () => {
    stub(["event: progress\ndata: a\n\nevent: progress\ndata: b\n\n"]);
    const seen: string[] = [];
    await streamEvents("https://verity.test/s", (e) => seen.push(e.data));
    expect(seen).toEqual(["a", "b"]);
  });

  it("waits for a frame split across two chunks", async () => {
    // The failure this prevents is not an error: it is half a JSON document
    // delivered as a whole event.
    stub(['event: progress\ndata: {"ste', 'p":"diff"}\n\n']);
    const seen: string[] = [];
    await streamEvents("https://verity.test/s", (e) => seen.push(e.data));
    expect(seen).toEqual(['{"step":"diff"}']);
  });

  it("delivers a final frame the server did not terminate", async () => {
    // Dropping it loses the terminal `status` event, which is the one the
    // caller is waiting for.
    stub(["event: status\ndata: done"]);
    const seen: string[] = [];
    await streamEvents("https://verity.test/s", (e) => seen.push(e.event));
    expect(seen).toEqual(["status"]);
  });

  it("handles CRLF framing", async () => {
    stub(["event: progress\r\ndata: a\r\n\r\n"]);
    const seen: string[] = [];
    await streamEvents("https://verity.test/s", (e) => seen.push(e.data));
    expect(seen).toEqual(["a"]);
  });

  it("sends the token as a header and never in the URL", async () => {
    const calls = stub(["data: x\n\n"]);
    await streamEvents("https://verity.test/s", () => {}, { token: "sekrit" });
    expect(calls[0].headers.authorization).toBe("Bearer sekrit");
    expect(calls[0].url).not.toContain("sekrit");
  });

  it("rejects on a refusal instead of resolving empty", async () => {
    // "The run finished" and "we lost the connection" must not look the same
    // to a caller showing live progress.
    stub([], { status: 403 });
    await expect(
      streamEvents("https://verity.test/s", () => {}),
    ).rejects.toThrow("403");
  });
});

describe("following a run", () => {
  it("collects progress and the final status", async () => {
    stub([
      "id: 1\nevent: progress\ndata: loading contract\n\n",
      "id: 2\nevent: progress\ndata: diffing\n\n",
      'event: status\ndata: {"run_id":7,"status":"passed"}\n\n',
    ]);
    const snapshots: number[] = [];
    const result = await followRun("https://verity.test", 7, (p) =>
      snapshots.push(p.events.length),
    );

    expect(result.status).toBe("passed");
    expect(result.events.map((e) => e.message)).toEqual([
      "loading contract",
      "diffing",
    ]);
    expect(snapshots).toEqual([1, 2, 2]); // the status frame adds no progress row
  });

  it("reports an unreadable status as unknown rather than inventing one", async () => {
    stub(["event: status\ndata: not json\n\n"]);
    const result = await followRun("https://verity.test", 7, () => {});
    expect(result.status).toBeNull();
  });

  it("builds the URL without doubling a trailing slash", async () => {
    const calls = stub(['event: status\ndata: {"status":"passed"}\n\n']);
    await followRun("https://verity.test/", 7, () => {});
    expect(calls[0].url).toBe("https://verity.test/v1/runs/7/events");
  });
});

describe("progress frames", () => {
  it("shows the message, not the whole JSON row", async () => {
    // The server sends the event row. Rendering it verbatim puts
    // `{"id":1,"ts":"…","message":"diffing","pct":null}` in front of a reader
    // who wanted "diffing" -- and every other field is already a table column.
    stub([
      'event: progress\ndata: {"id":1,"ts":"2026-01-01T00:00:00Z","message":"diffing","pct":40}\n\n',
    ]);
    const result = await followRun("https://verity.test", 7, () => {});
    expect(result.events[0]).toMatchObject({ message: "diffing", pct: 40 });
  });

  it("keeps a plain-text frame rather than discarding it", async () => {
    // A server that streams text is not wrong, and dropping its output would
    // leave the progress view empty for no stated reason.
    stub(["event: progress\ndata: still working\n\n"]);
    const result = await followRun("https://verity.test", 7, () => {});
    expect(result.events[0].message).toBe("still working");
  });

  it("omits a percentage the server did not send", async () => {
    stub(['event: progress\ndata: {"message":"diffing","pct":null}\n\n']);
    const result = await followRun("https://verity.test", 7, () => {});
    expect(result.events[0].pct).toBeUndefined();
  });
});
