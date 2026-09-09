/* Agent-governance pages: MCP fleet posture, tool poisoning, call budgets.
 *
 * These three are the views no competitor's UI shows, and all three render
 * data that a real run produced -- `scripts/generate-demo-data.py` starts
 * three mock MCP servers with deliberately different postures and probes
 * them, so the fleet table below is measurements rather than a mockup.
 *
 * The severity vocabulary is the engine's, not this file's: INFO findings are
 * observations and are shown as such, because the fleet view has to be usable
 * as evidence that a server was checked and was fine, not only as an alarm.
 */
import { Badge, Empty, PageHead, SevBadge, StatGrid } from "../components/ui";
import type { AgentFinding } from "../data";
import type { PageProps } from "./types";

type Data = PageProps["data"];

/* A section that was never generated is not a section that is loading. The
 * demo artifact went stale for months and six pages sat on "Loading…" the
 * whole time, which reads as a broken app rather than an absent input. */
function Missing({ section }: { section: string }) {
  return (
    <Empty
      msg={`This artifact carries no '${section}' section.`}
      hint="Regenerate it with scripts/generate-demo-data.py, or point the dashboard at a run that produced one."
    />
  );
}

/* Badge classes, which are the CSS token names: error / warn / info / success. */
function tone(severity: string): string {
  return severity === "ERROR" ? "error" : severity === "WARN" ? "warn" : "info";
}

function worst(findings: { severity: string }[]): string {
  if (findings.some((f) => f.severity === "ERROR")) return "ERROR";
  if (findings.some((f) => f.severity === "WARN")) return "WARN";
  return findings.length ? "INFO" : "CLEAN";
}

/* How badly anonymous access matters here, taken from the engine rather than
 * decided again in the browser.
 *
 * `MCP-AUTH-ANONYMOUS-LIST` is INFO on a laptop and ERROR on a public host --
 * the fact is identical and the consequence is not. A red pass/fail badge in
 * this column told every reader that a local dev server was failing, which is
 * how a column stops being read. */
function anonymousTone(server: {
  auth: { anonymous_access?: string };
  findings: AgentFinding[];
}) {
  const finding = server.findings.find(
    (f) => f.rule_id === "MCP-AUTH-ANONYMOUS-LIST",
  );
  if (!finding)
    return server.auth.anonymous_access === "served" ? "warn" : "success";
  return tone(finding.severity);
}

export function FleetPage({ data }: { data: Data }) {
  if (!data) return <Empty msg="Loading…" />;
  if (!data.agents) return <Missing section="agents" />;
  const fleet = data.agents.fleet;

  const errors = fleet.filter((s) => worst(s.findings) === "ERROR").length;
  const anonymous = fleet.filter(
    (s) => s.auth.anonymous_access === "served",
  ).length;

  return (
    <>
      <PageHead
        title="MCP Fleet"
        sub="every server an agent talks to, and whether it still matches what it declared"
        note={
          <>
            Each row is a real probe: <code>server/discover</code> and{" "}
            <code>tools/list</code>, read-only. Nothing here invoked a tool.
          </>
        }
      />
      <StatGrid
        stats={[
          { label: "Servers", value: fleet.length },
          {
            label: "With breaking drift",
            value: errors,
            tone: errors ? "error" : "success",
          },
          {
            label: "Serving tools anonymously",
            value: anonymous,
            tone: anonymous ? "warn" : "success",
          },
        ]}
      />
      <div className="table-wrap">
        <table>
          <caption>Fleet posture, newest probe per server</caption>
          <thead>
            <tr>
              <th>Server</th>
              <th>Endpoint</th>
              <th>Tools</th>
              <th>Protocol</th>
              <th>Anonymous</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {fleet.map((server) => {
              const verdict = worst(server.findings);
              return (
                <tr key={server.name}>
                  <td>{server.name}</td>
                  <td>
                    <code>{server.endpoint}</code>
                  </td>
                  <td>
                    {server.tools_served} served
                    {server.tools_served === server.tools_declared ? (
                      " "
                    ) : (
                      <> · {server.tools_declared} declared</>
                    )}
                  </td>
                  <td>
                    <Badge tone="info">
                      {server.protocol_revision ?? "unknown"}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={anonymousTone(server)}>
                      {server.auth.anonymous_access === "served"
                        ? `${server.auth.anonymous_tool_count ?? "?"} tools without a credential`
                        : String(
                            server.auth.anonymous_access ?? "not established",
                          )}
                    </Badge>
                  </td>
                  <td>
                    {verdict === "CLEAN" ? (
                      <Badge tone="success">matches</Badge>
                    ) : (
                      <Badge tone={tone(verdict)}>
                        {server.findings.length} finding(s)
                      </Badge>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {fleet.map((server) => (
        <section key={server.name}>
          <h3>{server.name}</h3>
          {server.findings.length === 0 ? (
            <Empty msg="Nothing to report: served set matches the manifest." />
          ) : (
            <div className="table-wrap">
              <table>
                <caption>Findings for {server.name}</caption>
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Rule</th>
                    <th>Tool</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {server.findings.map((finding, index) => (
                    <tr key={`${finding.rule_id}-${index}`}>
                      <td>
                        <SevBadge sev={finding.severity} />
                      </td>
                      <td>
                        <code>{finding.rule_id}</code>
                      </td>
                      <td>{finding.tool ?? "—"}</td>
                      <td>{finding.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </>
  );
}

export function PoisoningPage({ data }: { data: Data }) {
  if (!data) return <Empty msg="Loading…" />;
  if (!data.agents) return <Missing section="agents" />;
  const scan = data.agents.poisoning;

  const byTool = new Map<string, typeof scan.findings>();
  for (const finding of scan.findings) {
    const key = finding.operation_key ?? "whole manifest";
    byTool.set(key, [...(byTool.get(key) ?? []), finding]);
  }

  return (
    <>
      <PageHead
        title="Tool Poisoning"
        sub="a description is what an agent routes on, so it is executable text"
        note={
          <>
            Scanned <code>{scan.manifest}</code> — {scan.tools} tools,{" "}
            {scan.findings.length} findings. OWASP MCP03.
          </>
        }
      />
      {scan.findings.length === 0 ? (
        <Empty msg="No poisoning indicators in this manifest." />
      ) : (
        [...byTool.entries()].map(([tool, findings]) => (
          <section key={tool}>
            <h3>{tool}</h3>
            <div className="table-wrap">
              <table>
                <caption>Findings for {tool}</caption>
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Rule</th>
                    <th>What was found</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((finding, index) => (
                    <tr key={`${finding.rule_id}-${index}`}>
                      <td>
                        <SevBadge sev={finding.severity} />
                      </td>
                      <td>
                        <code>{finding.rule_id}</code>
                      </td>
                      <td>{finding.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))
      )}
    </>
  );
}

export function BudgetsPage({ data }: { data: Data }) {
  if (!data) return <Empty msg="Loading…" />;
  if (!data.agents) return <Missing section="agents" />;
  const budget = data.agents.budget;

  return (
    <>
      <PageHead
        title="Call Budgets"
        sub="how often an agent may call each tool, and whether it did"
        note={
          <>
            Windows slide: five calls between 12:00:50 and 12:01:30 are two and
            three in clock minutes, and five in any one minute.
          </>
        }
      />
      <StatGrid
        stats={[
          { label: "Limits", value: budget.limits.length },
          { label: "Calls observed", value: budget.calls_observed },
          {
            label: "Breaches",
            value: budget.findings.filter((f) => f.severity === "ERROR").length,
            tone: budget.findings.some((f) => f.severity === "ERROR")
              ? "error"
              : "success",
          },
        ]}
      />
      <div className="table-wrap">
        <table>
          <caption>Declared limits</caption>
          <thead>
            <tr>
              <th>Operation</th>
              <th>Allowance</th>
              <th>Window</th>
            </tr>
          </thead>
          <tbody>
            {budget.limits.map((limit) => (
              <tr key={limit.operation_key}>
                <td>
                  <code>{limit.operation_key}</code>
                </td>
                <td>
                  {limit.max_calls === 0 ? (
                    <Badge tone="error">never</Badge>
                  ) : (
                    limit.max_calls
                  )}
                </td>
                <td>{limit.window}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table>
          <caption>What the observed calls did to those limits</caption>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Rule</th>
              <th>Operation</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {budget.findings.map((finding, index) => (
              <tr key={`${finding.rule_id}-${index}`}>
                <td>
                  <SevBadge sev={finding.severity} />
                </td>
                <td>
                  <code>{finding.rule_id}</code>
                </td>
                <td>{finding.operation_key ?? "—"}</td>
                <td>{finding.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
