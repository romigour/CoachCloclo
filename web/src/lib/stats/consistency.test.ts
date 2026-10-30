import { describe, expect, it } from "vitest";
import type { StatActivity } from "../api";
import { calendarRanges, dailyMinutes, weekStats } from "./consistency";

function act(date: string, over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date, start: null, name: null, family: "run", type_key: "running",
    duration_s: 3600, distance_m: 10000, d_plus_m: null, avg_hr: null, max_hr: null,
    vo2max: null, hr_zones_s: null, race: null, ...over,
  };
}

describe("dailyMinutes", () => {
  it("additionne par jour et arrondit les minutes", () => {
    const r = dailyMinutes([act("2026-10-01", { duration_s: 1800 }), act("2026-10-01", { duration_s: 610 }), act("2026-10-02", { duration_s: null })]);
    expect(r).toEqual([["2026-10-01", 40], ["2026-10-02", 0]]);
  });
});

describe("weekStats", () => {
  // today = jeudi 2026-10-29, semaine en cours = lundi 2026-10-26
  const p = { from: "2026-10-05", to: "2026-10-29" };
  const today = "2026-10-29";

  it("série courante de 3 avec la semaine en cours vide", () => {
    const acts = [act("2026-10-07"), act("2026-10-14"), act("2026-10-21")];
    const s = weekStats(acts, p, today);
    expect(s.totalWeeks).toBe(4);
    expect(s.activeWeeks).toBe(3);
    expect(s.currentStreak).toBe(3);
  });

  it("la semaine en cours compte si active", () => {
    const s = weekStats([act("2026-10-21"), act("2026-10-27")], p, today);
    expect(s.currentStreak).toBe(2);
  });

  it("une semaine vide au milieu casse la série", () => {
    const acts = [act("2026-10-06"), act("2026-10-13"), act("2026-10-27")];
    const s = weekStats(acts, p, today);
    expect(s.currentStreak).toBe(1);
    expect(s.bestStreak).toBe(2);
    expect(s.bestStreak).toBeGreaterThanOrEqual(s.currentStreak);
  });

  it("une semaine passée vide en fin de période donne une série nulle", () => {
    const s = weekStats([act("2026-10-07")], { from: "2026-10-05", to: "2026-10-25" }, today);
    expect(s.currentStreak).toBe(0);
    expect(s.bestStreak).toBe(1);
  });

  it("un dimanche tardif reste dans sa semaine (date, pas start)", () => {
    const s = weekStats([act("2026-10-25", { start: "2026-10-25T23:30:00" })], { from: "2026-10-19", to: "2026-10-25" }, "2026-10-25");
    expect(s.totalWeeks).toBe(1);
    expect(s.activeWeeks).toBe(1);
  });
});

describe("calendarRanges", () => {
  it("une seule rangée bornée à la période jusqu'à 53 semaines", () => {
    expect(calendarRanges({ from: "2025-10-31", to: "2026-10-30" })).toEqual([
      { from: "2025-10-31", to: "2026-10-30", weeks: 53 },
    ]);
    expect(calendarRanges({ from: "2026-06-15", to: "2026-06-15" })).toEqual([
      { from: "2026-06-15", to: "2026-06-15", weeks: 1 },
    ]);
  });

  it("au-delà, une rangée par année bornée à la période", () => {
    expect(calendarRanges({ from: "2024-05-01", to: "2026-10-30" })).toEqual([
      { from: "2024-05-01", to: "2024-12-31", weeks: 36 },
      { from: "2025-01-01", to: "2025-12-31", weeks: 53 },
      { from: "2026-01-01", to: "2026-10-30", weeks: 44 },
    ]);
  });
});
