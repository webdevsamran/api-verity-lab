/* Live data from a self-hosted apiverity server.
 *
 * The server has twenty-nine routes and the dashboard read none of them. Every
 * page in this app has always rendered one static `demo-data.json`, which is
 * the right default for the public demo and a strange thing for a product to
 * be able to do *only*: the org, contract, environment, approval, run, audit
 * and webhook views all describe state a running server actually holds.
 *
 * What this deliberately does not do
 * ----------------------------------
 * It does not synthesise the sections the server has no source for. A live
 * server stores contracts, findings, runs and audit events; it does not store
 * a fuzz result set, a latency percentile table or a coverage matrix, because
 * those are outputs of a run rather than server state. Filling them with zeros
 * would produce a dashboard reporting "0 failures, 100% coverage" for a
 * service nobody has tested -- which is worse than a page saying it has no
 * data, and much harder to notice.
 *
 * So `loadLive` returns what the server gave it, and `available` names the
 * sections it actually filled. Pages render `Missing` for the rest, which is
 * the same component the agent pages already use for exactly this distinction.
 *
 * The token
 * ---------
 * Read from `localStorage` only, never from the URL. A query parameter would
 * be the convenient way to share a link to a live dashboard, and it would put
 * a bearer token into browser history, the server's access log, and the
 * `Referer` header of every outbound link on the page -- which is the same
 * defect `SEC-APIKEY-IN-QUERY` reports about other people's contracts.
 */
import type {
  Approval,
  AuditEvent,
  DemoData,
  Environment,
  Finding,
  OrgContract,
  OrgUser,
  RunRow,
  Webhook,
} from "./data";

export interface LiveConfig {
  /** Base URL of the server, e.g. `https://verity.internal`. No trailing slash. */
  baseUrl: string;
  /** Bearer token. Stored locally; never placed in a URL. */
  token: string;
  /** Which org to show. The server scopes most routes by it. */
  orgId: number;
}

export const LIVE_KEY = "apiverity-live-source";

/** Sections a live server can genuinely fill. Everything else stays absent. */
export const LIVE_SECTIONS = [
  "org",
  "contracts",
  "findings",
  "environments",
  "policies",
  "approvals",
  "runs",
  "audit",
  "webhooks",
] as const;

export type LiveSection = (typeof LIVE_SECTIONS)[number];

export interface LiveResult {
  data: DemoData;
  /** Sections the server answered for. Read by pages to tell absent from empty. */
  available: LiveSection[];
  /** Sections that failed, with why. Reported, never silently dropped. */
  failed: { section: LiveSection; reason: string }[];
}

export function readLiveConfig(): LiveConfig | null {
  try {
    const raw = localStorage.getItem(LIVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LiveConfig>;
    if (!parsed.baseUrl) return null;
    return {
      baseUrl: String(parsed.baseUrl).replace(/\/+$/, ""),
      token: String(parsed.token ?? ""),
      orgId: Number(parsed.orgId ?? 1),
    };
  } catch {
    /* Unparseable or unavailable storage means no live source, not a crash. */
    return null;
  }
}

export function writeLiveConfig(config: LiveConfig | null): void {
  try {
    if (config === null) localStorage.removeItem(LIVE_KEY);
    else localStorage.setItem(LIVE_KEY, JSON.stringify(config));
  } catch {
    /* A source preference is not worth breaking the page over. */
  }
}

async function get<T>(config: LiveConfig, path: string): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (config.token) headers.authorization = `Bearer ${config.token}`;
  const response = await fetch(`${config.baseUrl}${path}`, { headers });
  if (!response.ok) throw new Error(`HTTP ${response.status} on ${path}`);
  return (await response.json()) as T;
}

interface Envelope<T> {
  [key: string]: T[] | unknown;
}

/** The server wraps collections under a key named after the resource. */
function items<T>(payload: Envelope<T> | T[] | null, key: string): T[] {
  if (Array.isArray(payload)) return payload;
  const value = payload?.[key];
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * Fetch every section this server can answer for, in parallel.
 *
 * One failing section does not fail the load. A server where the audit route
 * is behind a permission this token lacks is an ordinary server, and refusing
 * to render the other seven sections because of it would make the dashboard
 * usable only by an administrator.
 */
export async function loadLive(config: LiveConfig): Promise<LiveResult> {
  const available: LiveSection[] = [];
  const failed: { section: LiveSection; reason: string }[] = [];

  async function section<T>(
    name: LiveSection,
    path: string,
    key: string,
  ): Promise<T[]> {
    try {
      const payload = await get<Envelope<T>>(config, path);
      available.push(name);
      return items<T>(payload, key);
    } catch (error) {
      failed.push({
        section: name,
        reason: error instanceof Error ? error.message : String(error),
      });
      return [];
    }
  }

  /* The audit response carries the chain verdict alongside its events, so it
   * is fetched whole rather than through `section`: `chain_valid` is the one
   * field on this page that must never be defaulted. A tamper-evident log
   * reporting "valid" because nobody asked is the exact failure the hash chain
   * exists to prevent. */
  let chainValid: boolean | null = null;
  const auditSection = async (): Promise<AuditEvent[]> => {
    try {
      const payload = await get<{
        events?: AuditEvent[];
        chain_valid?: boolean;
      }>(config, "/v1/audit");
      chainValid =
        typeof payload.chain_valid === "boolean" ? payload.chain_valid : null;
      available.push("audit");
      return Array.isArray(payload.events) ? payload.events : [];
    } catch (error) {
      failed.push({
        section: "audit",
        reason: error instanceof Error ? error.message : String(error),
      });
      return [];
    }
  };

  const [
    users,
    contracts,
    environments,
    policies,
    approvals,
    runs,
    audit,
    webhooks,
  ] = await Promise.all([
    section<OrgUser>("org", `/v1/orgs/${config.orgId}/users`, "users"),
    section<OrgContract>("contracts", "/v1/contracts", "contracts"),
    section<Environment>("environments", "/v1/environments", "environments"),
    section<{ name: string; content: string }>(
      "policies",
      "/v1/policies",
      "policies",
    ),
    section<Approval>("approvals", "/v1/approvals", "approvals"),
    section<RunRow>("runs", "/v1/runs", "runs"),
    auditSection(),
    section<Webhook>("webhooks", "/v1/webhooks", "webhooks"),
  ]);

  /* Findings hang off a contract, so they need one to exist. Fetched for the
   * most recently published contract only: a dashboard that fans out one
   * request per contract turns a hundred-contract org into a hundred requests
   * on every page load. */
  let findings: Finding[] | null = null;
  const newest = contracts[contracts.length - 1];
  if (newest) {
    try {
      const payload = await get<Envelope<Finding>>(
        config,
        `/v1/contracts/${newest.id}/findings`,
      );
      findings = items<Finding>(payload, "findings");
      available.push("findings");
    } catch (error) {
      failed.push({
        section: "findings",
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }

  const data: DemoData = {
    meta: {
      tool: "apiverity",
      generated_from: config.baseUrl,
      label: `live · org ${config.orgId}`,
    },
    /* Only what the server holds, and only when it answered. `findings: []`
     * renders as a green "0 breaking findings", which is a verdict; the
     * section being absent renders as "not gathered", which is the truth when
     * there is no contract to ask about. */
    ...(findings === null ? {} : { breaking: { findings } }),
    org: {
      org: { id: config.orgId, name: `org ${config.orgId}` },
      users,
      contracts,
      environments,
      policies,
      approvals,
      runs,
      audit_events: audit,
      webhooks,
      chain_valid: chainValid ?? false,
    },
  } as DemoData;

  return { data, available, failed };
}
