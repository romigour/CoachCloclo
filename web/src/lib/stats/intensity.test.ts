import { describe, expect, it } from "vitest";
import type { StatActivity } from "../api";
import { monthlySplit, split } from "./intensity";

const run = (date: string, zones: number[] | null): StatActivity => ({
  id: 1, garmin_id: 1, date, start: null, name: null, family: "run", type_key: "running", duration_s: 3600,
  distance_m: 10000, d_plus_m: null, avg_hr: 150, max_hr: null, vo2max: null, hr_zones_s: zones, race: null,
});

describe("split", () => {
  it("Z1-2 / Z3 / Z4-5", () => expect(split([60, 20, 10, 5, 5])).toEqual({ easy: 0.8, moderate: 0.1, hard: 0.1 }));
  it("null sans temps", () => expect(split([0, 0, 0, 0, 0])).toBeNull());
});

describe("monthlySplit", () => {
  it("tous les mois de la période, vides ou mal couverts à null", () => {
    const z = [50, 0, 50, 0, 0];
    const acts = [run("2025-12-05", z), run("2026-02-01", z), run("2026-02-02", null), run("2026-02-03", null)];
    expect(monthlySplit(acts, { from: "2025-12-01", to: "2026-02-28" })).toEqual([
      { month: "2025-12", split: { easy: 0.5, moderate: 0.5, hard: 0 } },
      { month: "2026-01", split: null },
      { month: "2026-02", split: null },
    ]);
  });
});
