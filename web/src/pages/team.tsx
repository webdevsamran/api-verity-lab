/* Team / enterprise pages: org dashboard, environments, approvals, policies,
 * runs/jobs, audit log, webhooks, users. */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { readLiveConfig } from "../live";
import { followRun, type RunProgress } from "../sse";
import { Badge, Empty, Exports, Missing, PageHead } from "../components/ui";
import type { PageProps } from "./types";

export function OrgDashboard({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading organization snapshot…" />;
  const org = data.org;
  const cards: [string, string | number][] = [
    ["Organization", org.org.name],
    ["Members", org.users.filter((u) => u.kind === "user").length],
    [
      "Service accounts",
      org.users.filter((u) => u.kind === "service_account").length,
    ],
    ["Contracts published", org.contracts.length],
    ["Environments", org.environments.length],
    ["Audit chain valid", org.chain_valid ? "yes" : "TAMPERED"],
  ];
  return (
    <>
      <PageHead title="Organization Dashboard" sub={org.org.name} />
      <div className="cards">
        {cards.map(([k, v]) => (
          <div key={k} className="card">
            <div className="card-value">{String(v)}</div>
            <div className="card-key">{k}</div>
          </div>
        ))}
      </div>
    </>
  );
}

export function EnvironmentsPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading environments…" />;
  return (
    <>
      <PageHead
        title="Environments / Targets"
        sub="ownership + safety classification"
      />
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Base URL</th>
            <th>Safety class</th>
            <th>Owner</th>
            <th>Allowed modes</th>
          </tr>
        </thead>
        <tbody>
          {data.org.environments.map((e) => (
            <tr key={e.id}>
              <td>{e.name}</td>
              <td>
                <code>{e.base_url}</code>
              </td>
              <td>
                <Badge tone={e.safety_class === "dev" ? "success" : "warn"}>
                  {e.safety_class}
                </Badge>
              </td>
              <td>{e.owner ?? "—"}</td>
              <td>{e.allowed_modes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function ApprovalsPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading approvals…" />;
  return (
    <>
      <PageHead
        title="Approvals / Exceptions"
        sub="intentional breaking-change signoff"
      />
      {data.org.approvals.length === 0 ? (
        <Empty msg="No approvals recorded." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Contract</th>
              <th>Transition</th>
              <th>Justification</th>
              <th>Status</th>
              <th>Requested by</th>
              <th>Decided by</th>
            </tr>
          </thead>
          <tbody>
            {data.org.approvals.map((a) => (
              <tr key={a.id}>
                <td>{a.contract_title}</td>
                <td>
                  v{a.from_version} → v{a.to_version}
                </td>
                <td>{a.justification}</td>
                <td>
                  <Badge
                    tone={
                      a.status === "approved"
                        ? "success"
                        : a.status === "rejected"
                          ? "error"
                          : "warn"
                    }
                  >
                    {a.status}
                  </Badge>
                </td>
                <td>{a.requested_by}</td>
                <td>{a.decided_by ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export function PoliciesPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading policies…" />;
  return (
    <>
      <PageHead title="Policies" sub="policy-as-code" />
      {data.org.policies.map((p) => (
        <div key={p.name}>
          <h3>
            <code>{p.name}</code>
          </h3>
          <pre className="detail">{p.content}</pre>
        </div>
      ))}
    </>
  );
}

/* Run progress, read from the server's SSE stream.
 *
 * `GET /v1/runs/<id>/events` has existed since the job queue shipped and
 * nothing had ever subscribed to it. Opened on demand rather than for every
 * row: a page listing a hundred runs would otherwise hold a hundred streaming
 * connections open, and the reader is looking at one of them.
 */
function RunProgressRow({ runId }: { runId: number }) {
  // Memoised: `readLiveConfig` parses storage and returns a fresh object every
  // call, so an un-memoised value would be a new identity on every render --
  // and the effect below depends on it. That is not a slow re-render, it is a
  // stream that reconnects forever.
  const live = useMemo(() => readLiveConfig(), []);
  const [progress, setProgress] = useState<RunProgress>({
    events: [],
    status: null,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    followRun(live.baseUrl, runId, setProgress, {
      token: live.token,
      signal: controller.signal,
    }).catch((e: unknown) => {
      // An aborted stream is this component unmounting, not a failure to
      // report: a red banner every time someone collapses a row would train
      // them to ignore the real ones.
      if (controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : String(e));
    });
    return () => controller.abort();
    // Keyed on the run alone. `live` is read once per mount, which is correct
    // here because changing the data source re-mounts the whole page.
  }, [runId, live]);

  if (!live) {
    return (
      <td colSpan={6} className="muted">
        Live progress needs a server source — this artifact records what a run
        produced, not what it did while running.
      </td>
    );
  }
  if (error) {
    return (
      <td colSpan={6} className="muted">
        Could not follow run #{runId}: {error}
      </td>
    );
  }
  return (
    <td colSpan={6}>
      {progress.events.length === 0 ? (
        <span className="muted">No progress events recorded for this run.</span>
      ) : (
        <ol className="run-progress">
          {progress.events.map((e, i) => (
            <li key={e.id ?? i}>
              {e.message}
              {typeof e.pct === "number" && (
                <span className="muted"> · {e.pct}%</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {progress.status && (
        <p className="muted">
          Final status: <strong>{progress.status}</strong>
        </p>
      )}
    </td>
  );
}

export function JobsPage({ data }: { data: PageProps["data"] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!data?.org) return <Empty msg="Loading runs…" />;
  return (
    <>
      <PageHead title="Runs / Jobs" sub="verification + load executions" />
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Requested by</th>
            <th>Verifies</th>
            <th>Environment</th>
          </tr>
        </thead>
        <tbody>
          {data.org.runs.map((r) => (
            <Fragment key={r.id}>
              <tr>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-inline"
                    aria-expanded={open === r.id}
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    #{r.id}
                  </button>
                </td>
                <td>{r.kind}</td>
                <td>
                  <Badge
                    tone={
                      r.status === "passed"
                        ? "success"
                        : r.status === "running"
                          ? "info"
                          : "error"
                    }
                  >
                    {r.status}
                  </Badge>
                </td>
                <td>{r.requested_by}</td>
                <td>{r.verification_for ?? "—"}</td>
                <td>{r.environment ?? "—"}</td>
              </tr>
              {open === r.id && (
                <tr className="run-detail">
                  <RunProgressRow runId={r.id} />
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function AuditPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading audit log…" />;
  return (
    <>
      <PageHead
        title="Audit Log"
        sub={data.org.chain_valid ? "hash chain verified ✓" : "CHAIN TAMPERED"}
      />
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>When (UTC)</th>
            <th>Actor</th>
            <th>Action</th>
            <th>Target</th>
            <th>Entry hash</th>
          </tr>
        </thead>
        <tbody>
          {data.org.audit_events.map((e) => (
            <tr key={e.id}>
              <td>{e.id}</td>
              <td>{new Date(e.ts).toISOString()}</td>
              <td>{e.actor}</td>
              <td>
                <code>{e.action}</code>
              </td>
              <td>{e.target}</td>
              <td>
                <code title={e.entry_hash}>{e.entry_hash.slice(0, 10)}…</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function WebhooksPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading webhooks…" />;
  return (
    <>
      <PageHead title="Webhooks / Integrations" sub="HMAC-signed deliveries" />
      <table>
        <thead>
          <tr>
            <th>URL</th>
            <th>Secret ref</th>
            <th>Events</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {data.org.webhooks.map((w) => (
            <tr key={w.id}>
              <td>
                <code>{w.url}</code>
              </td>
              <td>
                <code>{w.secret_ref}</code>
              </td>
              <td>{w.events.join(", ")}</td>
              <td>{w.active ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function UsersPage({ data }: { data: PageProps["data"] }) {
  if (!data?.org) return <Empty msg="Loading users…" />;
  return (
    <>
      <PageHead title="Users / Teams / Service Accounts" sub="RBAC roles" />
      <table>
        <thead>
          <tr>
            <th>Subject</th>
            <th>Name</th>
            <th>Role</th>
            <th>Kind</th>
          </tr>
        </thead>
        <tbody>
          {data.org.users.map((u) => (
            <tr key={u.id}>
              <td>
                <code>{u.subject}</code>
              </td>
              <td>{u.display_name}</td>
              <td>
                <Badge
                  tone={
                    u.role === "owner"
                      ? "info"
                      : u.role === "admin"
                        ? "info"
                        : "neutral"
                  }
                >
                  {u.role}
                </Badge>
              </td>
              <td>{u.kind}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/* ------------------------------------------------------- blast radius */

/* Laid out here rather than in `components/ui.tsx` on purpose. That module is
 * reachable from the shell, so a chart added to it lands in the entry chunk
 * and is downloaded by everyone who opens the app -- including the people who
 * never open this page. It lives in the route chunk that uses it. */

interface Node {
  id: string;
  label: string;
  weight: number;
  y: number;
}

const ROW_H = 42;
const PAD_Y = 26;
const LEFT_X = 208;
const RIGHT_X = 452;
const VIEW_W = 660;

function layout(ids: string[], weight: (id: string) => number): Node[] {
  return ids.map((id, i) => ({
    id,
    label: id,
    weight: weight(id),
    y: PAD_Y + i * ROW_H + ROW_H / 2,
  }));
}

/**
 * A bipartite graph: operations on the left, the consumers that call them on
 * the right, an edge for each dependency.
 *
 * Hand-drawn SVG, like every other chart here -- a graph library costs more
 * than every page in this app put together, and this layout is two columns
 * and a bezier.
 *
 * The SVG is `aria-hidden`. All of the interaction lives in the tables below
 * it, which are real tables with real buttons: a screen reader user gets the
 * same information and the same controls, and keyboard focus never has to
 * enter the drawing. A graph that can only be read by looking at it is a
 * graph half the audience cannot read.
 */
function BlastGraph({
  operations,
  consumers,
  edges,
  selected,
}: {
  operations: Node[];
  consumers: Node[];
  edges: [string, string][];
  selected: string | null;
}) {
  const height =
    PAD_Y * 2 + Math.max(operations.length, consumers.length, 1) * ROW_H;
  const opY = new Map(operations.map((n) => [n.id, n.y]));
  const conY = new Map(consumers.map((n) => [n.id, n.y]));
  const lit = (op: string, consumer: string) =>
    selected === null || selected === op || selected === consumer;

  return (
    <svg
      className="blast-graph"
      viewBox={`0 0 ${VIEW_W} ${height}`}
      role="presentation"
      aria-hidden="true"
    >
      {edges.map(([op, consumer]) => {
        const y1 = opY.get(op);
        const y2 = conY.get(consumer);
        if (y1 === undefined || y2 === undefined) return null;
        const mid = (LEFT_X + RIGHT_X) / 2;
        return (
          <path
            key={`${op}->${consumer}`}
            className={"blast-edge" + (lit(op, consumer) ? "" : " dim")}
            d={`M ${LEFT_X} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${RIGHT_X} ${y2}`}
          />
        );
      })}
      {operations.map((n) => (
        <g
          key={n.id}
          className={
            "blast-node" +
            (selected === null || selected === n.id ? "" : " dim")
          }
        >
          <rect x={4} y={n.y - 14} width={LEFT_X - 4} height={28} rx={6} />
          <text x={14} y={n.y + 4}>
            {n.label}
          </text>
          <text className="blast-count" x={LEFT_X - 12} y={n.y + 4}>
            {n.weight}
          </text>
        </g>
      ))}
      {consumers.map((n) => (
        <g
          key={n.id}
          className={
            "blast-node consumer" +
            (selected === null || selected === n.id ? "" : " dim")
          }
        >
          <rect
            x={RIGHT_X}
            y={n.y - 14}
            width={VIEW_W - RIGHT_X - 4}
            height={28}
            rx={6}
          />
          <text x={RIGHT_X + 12} y={n.y + 4}>
            {n.label}
          </text>
          <text className="blast-count" x={VIEW_W - 14} y={n.y + 4}>
            {n.weight}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function BlastRadiusPage({ data }: { data: PageProps["data"] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const graph = useRef<HTMLDivElement>(null);
  const blast = data?.blast;

  const model = useMemo(() => {
    if (!blast) return null;
    const operationIds = Object.keys(blast.by_operation);
    const consumerIds = Object.keys(blast.by_consumer);
    const edges: [string, string][] = [];
    for (const [op, names] of Object.entries(blast.by_operation)) {
      for (const name of names) edges.push([op, name]);
    }
    return {
      operations: layout(operationIds, (id) => blast.errors_by_operation[id] ?? 0),
      consumers: layout(consumerIds, (id) => blast.by_consumer[id]?.findings ?? 0),
      edges,
    };
  }, [blast]);

  /* A section that was never generated is not a section that is loading.
   * Blast radius is the output of a run against a consumer registry, not
   * server state, so a live dashboard legitimately has none -- and "Loading…"
   * forever reads as a broken app rather than an absent input. */
  if (!data) return <Empty msg="Loading…" />;
  if (!blast || !model) return <Missing source={data.source} section="blast" />;

  const affected = Object.keys(blast.by_consumer).length;
  const teams = new Set(
    Object.values(blast.by_consumer)
      .map((c) => c.team)
      .filter((t): t is string => Boolean(t)),
  );

  return (
    <>
      <PageHead
        title="Blast Radius"
        sub={`${affected} of ${blast.consumers_registered} registered consumers affected`}
      />
      <div className="cards">
        <div className="card">
          <div className="card-value">{affected}</div>
          <div className="card-key">Consumers affected</div>
        </div>
        <div className="card">
          <div className="card-value">{teams.size}</div>
          <div className="card-key">Teams to tell</div>
        </div>
        <div className="card">
          <div className="card-value">
            {Object.keys(blast.errors_by_operation).length}
          </div>
          <div className="card-key">Operations with an ERROR</div>
        </div>
        <div className="card">
          <div className="card-value">{blast.unclaimed_operations.length}</div>
          <div className="card-key">Broken and unclaimed</div>
        </div>
      </div>

      {/* The single most misreadable thing on this page. Without it, an empty
       * consumer list reads as "nobody calls this", when it may only mean
       * "nobody wrote it down" -- and those two lead to opposite decisions. */}
      <p className="muted">
        Read from <code>{blast.registry}</code>, which declares itself{" "}
        <strong>{blast.complete ? "complete" : "incomplete"}</strong>.{" "}
        {blast.complete ? (
          <>
            An operation with no consumer here really is called by nobody
            registered, and a finding may be softened on that basis.
          </>
        ) : (
          <>
            An operation with no consumer here may simply be one nobody wrote
            down. Nothing on this page lowers a severity.
          </>
        )}
      </p>

      {blast.unclaimed_operations.length > 0 && (
        <p className="muted">
          <strong>Unclaimed:</strong>{" "}
          {blast.unclaimed_operations.map((op) => (
            <code key={op}>{op}</code>
          ))}{" "}
          — breaking, and no registered consumer. That is where an incomplete
          registry hurts, so it is named rather than left as an empty row.
        </p>
      )}

      <div className="section-head">
        <h2>Who calls what</h2>
        {/* One row per edge, not per consumer: a consumer calling three broken
          * operations is three facts, and a row per consumer would have to
          * pick one of them to show. */}
        <Exports
          view="blast radius"
          chartIn={graph}
          rows={model.edges.map(([operation, consumer]) => ({
            operation_key: operation,
            consumer,
            team: blast.by_consumer[consumer]?.team ?? "",
            consumer_findings: blast.by_consumer[consumer]?.findings ?? 0,
            operation_errors: blast.errors_by_operation[operation] ?? 0,
          }))}
          columns={[
            "operation_key",
            "consumer",
            "team",
            "consumer_findings",
            "operation_errors",
          ]}
        />
      </div>
      <div ref={graph}>
        <BlastGraph {...model} selected={selected} />
      </div>
      {selected && (
        <p className="muted">
          Showing <code>{selected}</code>.{" "}
          <button className="linklike" onClick={() => setSelected(null)}>
            Show everything
          </button>
        </p>
      )}

      <h3>By operation</h3>
      <table>
        <caption className="visually-hidden">
          Each breaking operation, how many ERROR findings it carries, and the
          registered consumers that call it
        </caption>
        <thead>
          <tr>
            <th>Operation</th>
            <th>ERRORs</th>
            <th>Consumers</th>
          </tr>
        </thead>
        <tbody>
          {model.operations.map((n) => (
            <tr key={n.id} className={selected === n.id ? "row-selected" : ""}>
              <td>
                <button
                  className="linklike"
                  aria-pressed={selected === n.id}
                  onClick={() =>
                    setSelected(selected === n.id ? null : n.id)
                  }
                >
                  <code>{n.id}</code>
                </button>
              </td>
              <td>{n.weight}</td>
              <td>
                {blast.by_operation[n.id].length === 0 ? (
                  <span className="muted">none registered</span>
                ) : (
                  blast.by_operation[n.id].join(", ")
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Who to tell</h3>
      <table>
        <caption className="visually-hidden">
          Each affected consumer, the team that owns it, where to reach them,
          and which operations it calls
        </caption>
        <thead>
          <tr>
            <th>Consumer</th>
            <th>Team</th>
            <th>Contact</th>
            <th>Operations</th>
            <th>Findings</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(blast.by_consumer).map(([name, c]) => (
            <tr key={name} className={selected === name ? "row-selected" : ""}>
              <td>
                <button
                  className="linklike"
                  aria-pressed={selected === name}
                  onClick={() =>
                    setSelected(selected === name ? null : name)
                  }
                >
                  {name}
                </button>
              </td>
              <td>{c.team ?? "—"}</td>
              <td>{c.contact ?? "—"}</td>
              <td>
                {c.operations.map((op) => (
                  <code key={op}>{op}</code>
                ))}
              </td>
              <td>{c.findings}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
