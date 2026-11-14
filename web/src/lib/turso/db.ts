import { createClient } from "@libsql/client/web";
import { ApiError } from "../api";
import { normalizeHost, type Credentials } from "./credentials";

export type Arg = string | number | null;
export type Db = {
  execute(stmt: string | { sql: string; args: Arg[] }): Promise<{ rows: Record<string, unknown>[] }>;
};

const KNOWN_SCHEMA = 1;

const MESSAGES = {
  auth: "Jeton Turso refusé",
  unreachable: "Base Turso injoignable",
  schema_too_new: "Base plus récente que cette version mobile : recharge la page pour la mettre à jour",
  schema_outdated: "Mets à jour l'appli de bureau puis relance-la une fois",
  unexpected: "Erreur inattendue",
} as const;

export const fail = (code: keyof typeof MESSAGES) => new ApiError(code, MESSAGES[code]);

export function statusOf(e: unknown): number | undefined {
  if (typeof e !== "object" || e === null) return undefined;
  const o = e as { status?: unknown; statusCode?: unknown; cause?: unknown };
  for (const s of [o.status, o.statusCode]) if (typeof s === "number") return s;
  return statusOf(o.cause);
}

export function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  const msg = e instanceof Error ? e.message : String(e);
  const status = statusOf(e);
  if (status === 401 || status === 403 || /\b(401|403)\b|unauthori[sz]ed|forbidden/i.test(msg)) return fail("auth");
  if (e instanceof TypeError || /fetch failed|network/i.test(msg)) return fail("unreachable");
  if (/no such (column|table)/i.test(msg)) return fail("schema_outdated");
  return fail("unreachable");
}

export function openDb(c: Credentials): Db {
  const client = createClient({ url: "https://" + normalizeHost(c.url), authToken: c.token });
  return {
    async execute(stmt) {
      try {
        const r = await client.execute(stmt);
        return { rows: r.rows as unknown as Record<string, unknown>[] };
      } catch (e) {
        throw toApiError(e);
      }
    },
  };
}

/** Colonnes lues par les lecteurs (tâches 4 et 5), par table. */
export const REQUIRED_COLUMNS: Record<string, string[]> = {
  appstate: ["key", "value_json"],
  cycle: [
    "id", "status", "plan_start", "end_date", "sessions_per_week", "available_days_json",
    "long_run_day", "include_bike", "plan_accepted", "needs_generation",
  ],
  goal: [
    "id", "type", "distance_km", "d_plus_m", "race_date", "priority", "status",
    "target_time_s", "target_source", "gpx_summary_json",
  ],
  session: [
    "id", "cycle_id", "week_index", "order", "type", "sport", "title", "description",
    "target_kind", "status", "suggested_day", "scheduled_date", "chaining_note", "steps_json", "sync_error",
  ],
  event: ["id", "cycle_id", "kind", "start_date", "end_date", "max_sessions", "days_json", "session_id", "note"],
  activity: [
    "id", "garmin_activity_id", "date", "type_key", "duration_s", "distance_m", "d_plus_m",
    "avg_hr", "raw_json", "session_id", "match_source",
  ],
  race: [
    "id", "activity_id", "name", "official_time_s", "overall_rank", "overall_total",
    "category", "category_rank", "category_total", "excluded",
  ],
  personalrecord: ["id", "kind", "value", "garmin_activity_id", "date"],
  athletesnapshot: ["id", "date", "zones_json"],
  proposal: ["id", "status"],
};

export async function checkSchema(db: Db): Promise<void> {
  const r = await db.execute({ sql: "SELECT value_json FROM appstate WHERE key = ?", args: ["schema_version"] });
  if (r.rows.length === 0) throw fail("schema_outdated");
  let v: unknown;
  try {
    v = (JSON.parse(String(r.rows[0].value_json)) as { v?: unknown }).v;
  } catch {
    throw fail("schema_outdated");
  }
  if (typeof v !== "number") throw fail("schema_outdated");
  if (v > KNOWN_SCHEMA) throw fail("schema_too_new");
  // Un seul SELECT ordinaire (un jeton en lecture seule peut refuser PRAGMA) : les noms de tables sont des constantes.
  const sql = Object.keys(REQUIRED_COLUMNS)
    .map((t) => `SELECT '${t}' AS t, name FROM pragma_table_info('${t}')`)
    .join(" UNION ALL ");
  const info = await db.execute(sql);
  const have = new Set(info.rows.map((row) => `${row.t}.${row.name}`));
  for (const [table, cols] of Object.entries(REQUIRED_COLUMNS)) {
    if (cols.some((c) => !have.has(`${table}.${c}`))) throw fail("schema_outdated");
  }
}

export async function checkConnection(c: Credentials): Promise<void> {
  await checkSchema(openDb(c));
}
