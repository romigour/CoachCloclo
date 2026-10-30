import { expect, test } from "vitest";
import { formatDuration, peakLevel, profile, totalSeconds } from "./profile";
import type { Step, StepGroup } from "./api";

const seuil: (Step | StepGroup)[] = [
  { kind: "warmup", duration_s: 1200, zone: "EF" },
  { repeat: 3, steps: [{ kind: "active", duration_s: 600, zone: "seuil" }, { kind: "recovery", duration_s: 180 }] },
  { kind: "cooldown", duration_s: 600 },
];

test("profile unrolls repeats and maps pace and HR zones to the same levels", () => {
  expect(profile(seuil).map((b) => b.level)).toEqual([2, 4, 1, 4, 1, 4, 1, 1]);
  expect(profile([{ kind: "active", duration_s: 60, zone: "Z5" }])[0].level).toBe(5);
});

test("a step without a zone falls back on its kind", () => {
  expect(profile([{ kind: "active", duration_s: 60 }])[0].level).toBe(3);
  expect(profile([{ kind: "warmup", duration_s: 60 }])[0].level).toBe(2);
});

test("distance steps get an estimated width but no known total duration", () => {
  const vma: (Step | StepGroup)[] = [{ repeat: 10, steps: [{ kind: "active", distance_m: 400, zone: "VMA" }] }];
  expect(profile(vma)).toHaveLength(10);
  expect(profile(vma)[0].seconds).toBeGreaterThan(0);
  expect(totalSeconds(vma)).toBeNull();
});

test("total duration and its display", () => {
  expect(totalSeconds(seuil)).toBe(1200 + 3 * 780 + 600);
  expect(formatDuration(4140)).toBe("1 h 09");
  expect(formatDuration(2700)).toBe("45 min");
});

test("peak level is the hardest block", () => {
  expect(peakLevel(seuil)).toBe(4);
  expect(peakLevel([])).toBe(1);
});
