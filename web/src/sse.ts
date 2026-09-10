/* Server-sent events, read over `fetch` rather than through `EventSource`.
 *
 * `GET /v1/runs/<id>/events` has been on the server since the job queue
 * shipped and nothing has ever subscribed to it. Wiring it up runs straight
 * into the one thing `EventSource` cannot do: send an `Authorization` header.
 * Every route on this server is authenticated, so the browser API built for
 * this exact job is the one API that cannot do it.
 *
 * The usual workaround is a token in the query string. That is refused here
 * for the same reason the source picker refuses it and `SEC-APIKEY-IN-QUERY`
 * reports it in other people's contracts: a URL reaches access logs, proxy
 * logs, browser history and `Referer` headers, and a streaming request holds
 * that URL open for the length of the run.
 *
 * So the stream is read from `fetch`'s body and the wire format is parsed
 * here. It is a small format -- `field: value` lines, a blank line ends an
 * event -- and forty lines of parser is a better trade than a credential in a
 * log.
 */

export interface SseEvent {
  /** The `event:` field, or `message` when the server did not send one. */
  event: string;
  /** The `data:` field, joined with newlines when the server sent several. */
  data: string;
  id?: string;
}

export interface StreamOptions {
  /** Bearer token, sent as a header. Never appended to the URL. */
  token?: string;
  /** Aborts the stream. */
  signal?: AbortSignal;
}

/** Split a raw SSE frame into its fields. */
export function parseFrame(frame: string): SseEvent | null {
  const lines = frame.split(/\r?\n/);
  const data: string[] = [];
  let event = "message";
  let id: string | undefined;

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue; // blank, or a keep-alive comment
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // "If value starts with a space, remove it" -- one space, not all of them.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id") id = value;
  }

  if (!data.length && event === "message") return null;
  return { event, data: data.join("\n"), ...(id === undefined ? {} : { id }) };
}

/**
 * Read one SSE stream to completion, calling `onEvent` for each event.
 *
 * Resolves when the server closes the stream. Rejects on a transport failure
 * or a non-2xx response -- a caller showing live progress needs to know the
 * difference between "the run finished" and "we lost the connection", and a
 * promise that resolves either way cannot tell them.
 */
export async function streamEvents(
  url: string,
  onEvent: (event: SseEvent) => void,
  { token, signal }: StreamOptions = {},
): Promise<void> {
  const headers: Record<string, string> = { accept: "text/event-stream" };
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(url, { headers, signal });
  if (!response.ok) throw new Error(`HTTP ${response.status} on ${url}`);
  if (!response.body)
    throw new Error("this browser gave no readable body for the stream");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // A frame ends at a blank line. Anything after the last one is a
      // partial frame and stays in the buffer: dispatching half an event
      // would deliver truncated JSON that the caller cannot distinguish from
      // a malformed one.
      let boundary = buffer.search(/\r?\n\r?\n/);
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + (buffer[boundary] === "\r" ? 4 : 2));
        const parsed = parseFrame(frame);
        if (parsed) onEvent(parsed);
        boundary = buffer.search(/\r?\n\r?\n/);
      }
    }
    // A server that closes without a trailing blank line still meant the last
    // frame. Dropping it would lose the terminal `status` event, which is the
    // one the caller is waiting for.
    const tail = parseFrame(buffer);
    if (tail) onEvent(tail);
  } finally {
    reader.releaseLock();
  }
}

export interface RunEvent {
  id?: string;
  /** What the run reported. The raw frame when it was not JSON. */
  message: string;
  /** ISO timestamp, when the server sent one. */
  ts?: string;
  /** Percentage complete, when the server sent one. */
  pct?: number;
}

export interface RunProgress {
  /** Progress events the run has emitted so far. */
  events: RunEvent[];
  /** The run's status, once the server has sent it. */
  status: string | null;
}

/** Pull the readable parts out of one progress frame.
 *
 * The server sends the whole event row as JSON. Rendering that verbatim puts
 * `{"id": 1, "ts": "...", "message": "diffing", "pct": null}` in front of a
 * reader who wanted "diffing" -- and the fields around it are exactly the ones
 * a table shows in its own columns.
 *
 * A frame that is not JSON is shown as it arrived rather than discarded: a
 * server that streams plain text is not wrong, and dropping its output would
 * make the progress view empty for no stated reason.
 */
function readProgress(frame: SseEvent): RunEvent {
  try {
    const payload = JSON.parse(frame.data);
    if (
      payload &&
      typeof payload === "object" &&
      typeof payload.message === "string"
    ) {
      return {
        ...(frame.id === undefined ? {} : { id: frame.id }),
        message: payload.message,
        ...(typeof payload.ts === "string" ? { ts: payload.ts } : {}),
        ...(typeof payload.pct === "number" ? { pct: payload.pct } : {}),
      };
    }
  } catch {
    /* Not JSON. The raw frame is the message. */
  }
  return {
    ...(frame.id === undefined ? {} : { id: frame.id }),
    message: frame.data,
  };
}

/**
 * Follow one run to completion.
 *
 * The server's stream is deterministic: the history it already has, then a
 * final `status` event. So this is not a subscription that waits for the
 * future -- it is a read of what happened, which is why it terminates.
 */
export async function followRun(
  baseUrl: string,
  runId: number,
  onChange: (progress: RunProgress) => void,
  options: StreamOptions = {},
): Promise<RunProgress> {
  const progress: RunProgress = { events: [], status: null };

  await streamEvents(
    `${baseUrl.replace(/\/+$/, "")}/v1/runs/${runId}/events`,
    (event) => {
      if (event.event === "status") {
        try {
          progress.status = String(JSON.parse(event.data).status ?? "");
        } catch {
          // A status frame we cannot read is not a status. Leaving it null
          // shows "unknown" rather than inventing one.
          progress.status = null;
        }
      } else {
        progress.events.push(readProgress(event));
      }
      onChange({ events: [...progress.events], status: progress.status });
    },
    options,
  );

  return progress;
}
