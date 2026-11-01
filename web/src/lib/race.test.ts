import { expect, test } from "vitest";
import { fmtDuration, isDirty, targetLabel } from "./race";
import type { RaceSegment, RaceSettings } from "./api";

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
