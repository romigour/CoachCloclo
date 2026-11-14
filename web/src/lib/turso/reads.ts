// Lectures seules, portées des routes FastAPI et des requêtes de `Repo` (coach/plan/repo.py).
import type { Activity, CoachEvent, Cycle, HistoryState, Plan, Session, Status, Zones } from "../api";
import type { Arg, Db } from "./db";
import { activityRow, cycleDict, eventDict, goalDict, sessionDict } from "./mappers";

type Row = Record<string, unknown>;

const GOAL_COLS =
  "id, type, distance_km, d_plus_m, race_date, priority, status, target_time_s, target_source, gpx_summary_json";
const CYCLE_COLS =
  "id, status, plan_start, end_date, sessions_per_week, available_days_json, long_run_day, include_bike, plan_accepted, needs_generation";
const EVENT_COLS = "id, kind, start_date, end_date, max_sessions, days_json, session_id, note";
const SESSION_COLS =
  'id, "order", type, sport, title, description, target_kind, status, suggested_day, scheduled_date, chaining_note, steps_json, sync_error';
const ACTIVITY_COLS = "id, date, type_key, duration_s, distance_m, d_plus_m, avg_hr, session_id, match_source";

const all = async (db: Db, sql: string, args: Arg[] = []): Promise<Row[]> => (await db.execute({ sql, args })).rows;
const first = async (db: Db, sql: string, args: Arg[] = []): Promise<Row | undefined> =>
  (await all(db, sql, args))[0];

const activeCycle = async (db: Db): Promise<Cycle | null> => {
  const r = await first(db, `SELECT ${CYCLE_COLS} FROM cycle WHERE status = 'active' ORDER BY id DESC LIMIT 1`);
  return r ? cycleDict(r) : null;
};

const upcomingGoals = async (db: Db) =>
  (await all(db, `SELECT ${GOAL_COLS} FROM goal WHERE status = 'active' ORDER BY race_date, id`)).map(goalDict);

const pastGoals = async (db: Db) =>
  (await all(db, `SELECT ${GOAL_COLS} FROM goal WHERE status = 'done' ORDER BY race_date DESC, id DESC`)).map(goalDict);

function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Lundi de la semaine `weekIndex` (base 1) du cycle : `plan_start + 7·(weekIndex − 1)` jours. */
const weekMonday = (cycle: Cycle, weekIndex: number): string => addDays(cycle.plan_start, 7 * (weekIndex - 1));

export async function plan(db: Db): Promise<Plan> {
  const cycle = await activeCycle(db);
  if (!cycle) return { cycle: null, goals: [], horizon: [], open_injury: null, weeks: [] };
  const weeks = new Map<number, Session[]>();
  const sessions = await all(
    db,
    `SELECT week_index, ${SESSION_COLS} FROM session WHERE cycle_id = ? ORDER BY week_index, "order"`,
    [cycle.id],
  );
  for (const r of sessions) {
    const idx = Number(r.week_index);
    weeks.set(idx, [...(weeks.get(idx) ?? []), sessionDict(r)]);
  }
  const injury = await first(
    db,
    `SELECT ${EVENT_COLS} FROM event WHERE cycle_id = ? AND kind = 'injury' AND end_date IS NULL ORDER BY id DESC LIMIT 1`,
    [cycle.id],
  );
  const upcoming = await upcomingGoals(db);
  return {
    cycle,
    goals: upcoming.filter((g) => cycle.plan_start <= g.race_date && g.race_date <= cycle.end_date),
    horizon: upcoming.filter((g) => g.race_date > cycle.end_date),
    open_injury: injury ? eventDict(injury) : null,
    weeks: [...weeks.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([week_index, s]) => ({ week_index, week_monday: weekMonday(cycle, week_index), sessions: s })),
  };
}

export async function events(db: Db): Promise<CoachEvent[]> {
  const cycle = await activeCycle(db);
  if (!cycle) return [];
  const rows = await all(
    db,
    `SELECT ${EVENT_COLS} FROM event WHERE cycle_id = ? ORDER BY start_date DESC, id DESC`,
    [cycle.id],
  );
  return rows.map(eventDict);
}

export async function activities(db: Db, week: number): Promise<Activity[]> {
  const cycle = await activeCycle(db);
  if (!cycle) return [];
  const monday = weekMonday(cycle, week);
  const sunday = addDays(monday, 6);
  const rows = await all(
    db,
    `SELECT ${ACTIVITY_COLS} FROM activity WHERE date >= ? AND date <= ? ORDER BY date, id`,
    [monday, sunday],
  );
  return rows.map(activityRow);
}

export async function zones(db: Db): Promise<Zones | null> {
  const r = await first(db, "SELECT zones_json FROM athletesnapshot ORDER BY date DESC, id DESC LIMIT 1");
  return r ? (JSON.parse(String(r.zones_json)) as Zones) : null;
}

const idle = (): HistoryState => ({ status: "idle", imported: 0, error: null });

/** Port de `load_state` : absent ou invalide → valeurs par défaut. */
async function loadHistory(db: Db): Promise<HistoryState> {
  const r = await first(db, "SELECT value_json FROM appstate WHERE key = ?", ["history"]);
  if (!r) return idle();
  try {
    const raw = JSON.parse(String(r.value_json)) as Record<string, unknown> | null;
    if (typeof raw !== "object" || raw === null) return idle();
    const s = raw.status ?? "idle";
    const imported = raw.imported ?? 0;
    const error = raw.error ?? null;
    if (
      !["idle", "running", "done", "error"].includes(s as string) ||
      typeof imported !== "number" ||
      !Number.isInteger(imported) ||
      (error !== null && typeof error !== "string")
    ) {
      return idle();
    }
    return { status: s as HistoryState["status"], imported, error: error as string | null };
  } catch {
    return idle();
  }
}

export async function status(db: Db, today: string): Promise<Status> {
  const cycle = await activeCycle(db);
  const goals = await upcomingGoals(db);
  const proposal = await first(db, "SELECT id FROM proposal WHERE status = 'pending' ORDER BY id DESC LIMIT 1");
  let last: Cycle | null = null;
  if (!cycle) {
    const r = await first(
      db,
      `SELECT ${CYCLE_COLS} FROM cycle WHERE status = 'done' AND end_date < ? ORDER BY end_date DESC, id DESC LIMIT 1`,
      [today],
    );
    last = r ? cycleDict(r) : null;
  }
  return {
    garmin: "unavailable",
    llm_mode: "cli",
    pending_proposal_id: proposal ? Number(proposal.id) : null,
    cycle,
    goals,
    next_goal: goals[0] ?? null,
    past_goals: await pastGoals(db),
    last_cycle: last,
    has_activities: (await first(db, "SELECT id FROM activity LIMIT 1")) !== undefined,
    history: await loadHistory(db),
    storage: null,
  };
}
