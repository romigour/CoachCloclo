import { describe, expect, test } from "vitest";
import { fmtDuration, goalTimeLabel, fmtTargetTime, isDirty, parseTargetTime, settingsError, targetLabel } from "./race";
import type { Goal, RaceSegment, RaceSettings } from "./api";

const seg = (over: Partial<RaceSegment>): RaceSegment => ({
  kind: "plat", start_km: 0, end_km: 1, eq_km: 1, d_plus_m: 0, d_minus_m: 0, index: 1, avg_grade_pct: 0,
  time_s: 288, pace_s_km: 288, elapsed_s: 288, clock: "08:04", target_kind: "pace",
  target_low: 283, target_high: 293, target_zone: null, ...over,
});

test("fmtDuration", () => {
  expect(fmtDuration(18720)).toBe("5 h 12");
  expect(fmtDuration(2880)).toBe("48 min");
  expect(fmtDuration(3600)).toBe("1 h 00");
});

test("targetLabel for pace and heart-rate targets", () => {
  expect(targetLabel(seg({}))).toBe("4:43–4:53 /km");
  expect(targetLabel(seg({ target_kind: "hr", target_zone: "Z3", target_low: 140, target_high: 160 }))).toBe("Z3 · 140–160 bpm");
  expect(targetLabel(seg({ target_low: null, target_high: null }))).toBe("—");
});

test("isDirty detects an aid station change", () => {
  const a: RaceSettings = {
    target_time_s: null, start_time: "08:00", carbs_g_h: 60, water_ml_h: 500, carry_ml: 1000,
    aid_stations: [{ km: 10, name: "A", kind: "eau", cutoff: null, stop_min: 1 }],
  };
  const b = structuredClone(a);
  expect(isDirty(a, b)).toBe(false);
  b.aid_stations[0].stop_min = 2;
  expect(isDirty(a, b)).toBe(true);
});

test("parseTargetTime reads h:mm and h:mm:ss", () => {
  expect(parseTargetTime("3:45")).toBe(13500);
  expect(parseTargetTime(" 3:45:30 ")).toBe(13530);
  expect(parseTargetTime("0:45")).toBe(2700);
  expect(parseTargetTime("")).toBeNull();
  for (const bad of ["abc", "3", "3:75", "3:45:75", "0:00", "3:4", "3:45:5"]) expect(parseTargetTime(bad)).toBeNaN();
});

test("fmtTargetTime round-trips through parseTargetTime", () => {
  expect(fmtTargetTime(13500)).toBe("3:45");
  expect(fmtTargetTime(2700)).toBe("0:45");
  expect(fmtTargetTime(13530)).toBe("3:45:30");
  for (const s of [13500, 2700, 13530]) expect(parseTargetTime(fmtTargetTime(s))).toBe(s);
});

describe("settingsError", () => {
  const ok: RaceSettings = {
    target_time_s: null, start_time: "08:00", carbs_g_h: 60, water_ml_h: 500, carry_ml: 1000,
    aid_stations: [{ km: 10, name: "A", kind: "eau", cutoff: null, stop_min: 1 }],
  };
  const st = ok.aid_stations[0];
  test("valid settings", () => expect(settingsError(ok)).toBeNull());
  test.each([
    [{ start_time: "" }, "Heure de départ"],
    [{ carbs_g_h: null as unknown as number }, "Glucides"],
    [{ water_ml_h: NaN }, "Eau"],
    [{ carry_ml: 0 }, "Contenance"],
    [{ aid_stations: [{ ...st, km: NaN }] }, "Ravitaillement 1"],
    [{ aid_stations: [{ ...st, name: "  " }] }, "Ravitaillement 1"],
    [{ aid_stations: [{ ...st, stop_min: NaN }] }, "Ravitaillement 1"],
  ])("%o is refused", (over, msg) => expect(settingsError({ ...ok, ...over })).toContain(msg));
});

test("goalTimeLabel distinguishes Claude estimate, own target and none", () => {
  const g = { target_time_s: 6720, target_source: "claude" } as Goal;
  expect(goalTimeLabel(g)).toBe("Temps estimé par Claude : 1 h 52");
  expect(goalTimeLabel({ ...g, target_time_s: 6600, target_source: "user" })).toBe("Temps visé : 1 h 50");
  expect(goalTimeLabel({ ...g, target_time_s: null, target_source: null })).toBeNull();
});
