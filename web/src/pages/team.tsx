/* Team / enterprise pages: org dashboard, environments, approvals, policies,
 * runs/jobs, audit log, webhooks, users. */
import { Fragment, useEffect, useMemo, useState } from "react";
import { readLiveConfig } from "../live";
import { followRun, type RunProgress } from "../sse";
import { Badge, Empty, PageHead } from "../components/ui";
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
