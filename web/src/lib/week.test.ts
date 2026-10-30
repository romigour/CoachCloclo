import { expect, test } from "vitest";
import { currentWeek, days, daysUntil, focusSession, sessionDate } from "./week";
import type { Session, Week } from "./api";

const s = (id: number, suggested_day: Session["suggested_day"], extra: Partial<Session> = {}): Session => ({
  id, order: id, type: "EF", title: `S${id}`, description: "", target_kind: "pace", status: "todo",
  suggested_day, scheduled_date: null, chaining_note: null, steps: [], sync_error: null, ...extra,
});

const week = (idx: number, monday: string, sessions: Session[]): Week => ({ week_index: idx, week_monday: monday, sessions });

test("a session sits on its scheduled date when it falls within the week, else on its suggested day", () => {
  expect(sessionDate(s(1, "mardi"), "2026-10-26")).toBe("2026-10-27");
  expect(sessionDate(s(1, "mardi", { scheduled_date: "2026-10-30" }), "2026-10-26")).toBe("2026-10-30");
  expect(sessionDate(s(1, "mardi", { scheduled_date: "2026-11-30" }), "2026-10-26")).toBe("2026-10-27");
});

test("days spreads the week's sessions over Monday to Sunday", () => {
  const d = days(week(1, "2026-10-26", [s(1, "lundi"), s(2, "vendredi"), s(3, "vendredi")]));
  expect(d).toHaveLength(7);
  expect(d.map((x) => x.sessions.length)).toEqual([1, 0, 0, 0, 2, 0, 0]);
});

test("current week contains today, else the next one, else the last", () => {
  const weeks = [week(1, "2026-10-19", []), week(2, "2026-10-26", [])];
  expect(currentWeek(weeks, "2026-11-01")?.week_index).toBe(2);
  expect(currentWeek(weeks, "2026-10-01")?.week_index).toBe(1);
  expect(currentWeek(weeks, "2026-12-01")?.week_index).toBe(2);
  expect(currentWeek([], "2026-12-01")).toBeNull();
});

test("focus is today's session, else the next one not done", () => {
  const w = week(1, "2026-10-26", [s(1, "lundi", { status: "done" }), s(2, "vendredi"), s(3, "dimanche")]);
  expect(focusSession(w, "2026-10-30")?.id).toBe(2);
  expect(focusSession(w, "2026-10-28")?.id).toBe(2);
  expect(focusSession(w, "2026-10-31")?.id).toBe(3);
  expect(focusSession(w, "2026-11-02")).toBeNull();
});

test("days until the race", () => {
  expect(daysUntil("2026-10-30", "2026-12-06")).toBe(37);
  expect(daysUntil("2026-12-06", "2026-12-06")).toBe(0);
});
