// Ports de `_cycle_dict`, `_goal_dict`, `_session_dict`, `_event_dict`, `_activity_row` (coach/api/app.py).
import type { Activity, CoachEvent, Cycle, Goal, Session } from "../api";

type Row = Record<string, unknown>;

const num = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));
const str = (v: unknown): string | null => (v === null || v === undefined ? null : String(v));

export function goalDict(r: Row): Goal {
  return {
    id: Number(r.id),
    type: r.type as Goal["type"],
    distance_km: Number(r.distance_km),
    d_plus_m: Number(r.d_plus_m),
    race_date: String(r.race_date),
    priority: r.priority as Goal["priority"],
    status: r.status as Goal["status"],
    target_time_s: num(r.target_time_s),
    target_source: str(r.target_source) as Goal["target_source"],
    gpx_summary: r.gpx_summary_json ? JSON.parse(String(r.gpx_summary_json)) : null,
  };
}

export function cycleDict(r: Row): Cycle {
  return {
    id: Number(r.id),
    status: r.status as Cycle["status"],
    plan_start: String(r.plan_start),
    end_date: String(r.end_date),
    sessions_per_week: Number(r.sessions_per_week),
    available_days: JSON.parse(String(r.available_days_json)),
    long_run_day: str(r.long_run_day),
    include_bike: Boolean(r.include_bike),
    plan_accepted: Boolean(r.plan_accepted),
    needs_generation: Boolean(r.needs_generation),
  };
}

export function eventDict(r: Row): CoachEvent {
  return {
    id: Number(r.id),
    kind: r.kind as CoachEvent["kind"],
    start_date: String(r.start_date),
    end_date: str(r.end_date),
    max_sessions: num(r.max_sessions),
    days: r.days_json === null || r.days_json === undefined ? null : JSON.parse(String(r.days_json)),
    session_id: num(r.session_id),
    note: str(r.note),
  };
}

export function sessionDict(r: Row): Session {
  return {
    id: Number(r.id),
    order: Number(r.order),
    type: String(r.type),
    sport: r.sport as Session["sport"],
    title: String(r.title),
    description: String(r.description),
    target_kind: r.target_kind as Session["target_kind"],
    status: r.status as Session["status"],
    suggested_day: r.suggested_day as Session["suggested_day"],
    scheduled_date: str(r.scheduled_date),
    chaining_note: str(r.chaining_note),
    steps: JSON.parse(String(r.steps_json)),
    sync_error: str(r.sync_error),
  };
}

export function activityRow(r: Row): Activity {
  return {
    id: Number(r.id),
    date: String(r.date),
    type_key: String(r.type_key),
    duration_s: num(r.duration_s),
    distance_m: num(r.distance_m),
    d_plus_m: num(r.d_plus_m),
    avg_hr: num(r.avg_hr),
    session_id: num(r.session_id),
    match_source: str(r.match_source),
  };
}
