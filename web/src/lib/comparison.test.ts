import { expect, test } from "vitest";
import type { StepResult } from "./api";
import { doneLabel, repeatSummary, stepLabel, targetLabel, VERDICT_LABEL } from "./comparison";

const step = (over: Partial<StepResult> = {}): StepResult => ({
  group: 1, iteration: null, position: 1, kind: "active", planned_duration_s: null, planned_distance_m: null,
  zone: null, target_low: null, target_high: null, done: true, duration_s: null, distance_m: null,
  avg_pace_s_km: null, avg_hr: null, verdict: null, ...over,
});
const rep = (group: number, iteration: number, kind: StepResult["kind"], m: number, verdict: StepResult["verdict"] = null) =>
  step({ group, iteration, kind, planned_distance_m: m, verdict });

test("stepLabel numbers repeat iterations", () => {
  expect(stepLabel(rep(3, 2, "active", 400))).toBe("3.2 · Actif 400 m");
});

test("stepLabel formats durations and plain steps", () => {
  expect(stepLabel(step({ kind: "warmup", planned_duration_s: 900 }))).toBe("1 · Échauffement 15 min");
  expect(stepLabel(step({ kind: "recovery", planned_duration_s: 45 }))).toBe("1 · Récup 45 s");
  expect(stepLabel(step({ kind: "cooldown", planned_duration_s: 90 }))).toBe("1 · Retour au calme 90 s");
});

test("targetLabel formats pace and hr ranges", () => {
  const s = step({ zone: "VMA", target_low: 220, target_high: 235 });
  expect(targetLabel(s, "pace")).toBe("VMA 3:40–3:55/km");
  expect(targetLabel(step({ zone: "Z5", target_low: 171, target_high: 190 }), "hr")).toBe("Z5 171–190 bpm");
  expect(targetLabel(step(), "pace")).toBeNull();
});

test("doneLabel omits missing values", () => {
  expect(doneLabel(step({ distance_m: 412, avg_pace_s_km: 228, avg_hr: 172 }))).toBe("412 m · 3:48/km · 172 bpm");
  expect(doneLabel(step({ distance_m: 412, avg_pace_s_km: 228 }))).toBe("412 m · 3:48/km");
});

test("doneLabel shows the signed distance gap for a distance step", () => {
  const p = { planned_distance_m: 400, avg_pace_s_km: 228, avg_hr: 172 };
  expect(doneLabel(step({ ...p, distance_m: 412 }))).toBe("412 m (+12 m) · 3:48/km · 172 bpm");
  expect(doneLabel(step({ ...p, distance_m: 388 }))).toBe("388 m (−12 m) · 3:48/km · 172 bpm");
  expect(doneLabel(step({ ...p, distance_m: 400 }))).toBe("400 m · 3:48/km · 172 bpm");
});

test("doneLabel shows actual duration and signed gap for a duration step", () => {
  const p = { planned_duration_s: 900, avg_pace_s_km: 330 };
  expect(doneLabel(step({ ...p, duration_s: 870 }))).toBe("14:30 (−0:30) · 5:30/km");
  expect(doneLabel(step({ ...p, duration_s: 905 }))).toBe("15:05 (+0:05) · 5:30/km");
  expect(doneLabel(step({ ...p, duration_s: 900 }))).toBe("15:00 · 5:30/km");
});

test("doneLabel omits the volume when the actual one is null", () => {
  expect(doneLabel(step({ planned_distance_m: 400, avg_pace_s_km: 228 }))).toBe("3:48/km");
  expect(doneLabel(step({ planned_duration_s: 900, avg_hr: 150 }))).toBe("150 bpm");
});

test("repeatSummary counts active steps in target", () => {
  const steps = [step({ group: 1, kind: "warmup" })];
  for (let i = 1; i <= 6; i++) {
    steps.push(rep(2, i, "active", 400, i === 4 ? "slow" : "in"));
    steps.push(rep(2, i, "recovery", 200, "in"));
  }
  expect(repeatSummary(steps, 2)).toBe("5/6 fractions dans la cible");
  expect(repeatSummary(steps, 1)).toBeNull();
});

test("verdict labels", () => {
  expect(VERDICT_LABEL.hr_high).toBe("FC trop haute");
});
