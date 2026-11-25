import { describe, expect, it } from "vitest";
import type { StatActivity } from "../api";
import { hrAtPace, rollingMean } from "./running";

/** Sortie de 10 km le jour `i`. */
const run = (i: number, hr: number, pace = 330): StatActivity => ({
  id: i, garmin_id: i, date: `2026-01-${String(i + 1).padStart(2, "0")}`, start: null, name: null, family: "run",
  type_key: "running", duration_s: pace * 10, distance_m: 10000, d_plus_m: null, avg_hr: hr, max_hr: null,
  vo2max: null, hr_zones_s: null, race: null,
});

describe("hrAtPace", () => {
  const nine = [158, 158, 158, 154, 154, 154, 149, 149, 149].map((hr, i) => run(i, hr));

  it("compare le premier et le dernier tiers, par date", () => {
    expect(hrAtPace(nine)).toEqual({ paceSKm: 330, from: 158, to: 149, count: 9 });
    expect(hrAtPace([...nine].reverse())).toEqual({ paceSKm: 330, from: 158, to: 149, count: 9 });
  });
  it("null sous 9 sorties", () => {
    expect(hrAtPace(nine.slice(1))).toBeNull();
    expect(hrAtPace([])).toBeNull();
  });
  it("sortie à plus de 10 s/km de la référence non comptée", () => {
    expect(hrAtPace([...nine, run(9, 100, 345)])!.count).toBe(9);
    expect(hrAtPace([...nine, run(9, 149, 340)])!.count).toBe(10);
  });
  it("référence arrondie à 5 s", () => expect(hrAtPace(nine.map((a) => ({ ...a, duration_s: 3320 })))!.paceSKm).toBe(330));
  it("10 sorties : tiers de 3", () => {
    const ten = [158, 158, 158, 1, 1, 1, 1, 149, 149, 149].map((hr, i) => run(i, hr));
    expect(hrAtPace(ten)).toMatchObject({ from: 158, to: 149 });
  });
});

describe("rollingMean", () => {
  const pts = (n: number) => Array.from({ length: n }, (_, i) => ({ date: `2026-01-0${i + 1}`, value: i + 1 }));
  it("vide sous 5 points", () => expect(rollingMean(pts(4))).toEqual([]));
  it("datée du dernier point de la fenêtre", () => {
    expect(rollingMean(pts(6))).toEqual([{ date: "2026-01-05", value: 3 }, { date: "2026-01-06", value: 4 }]);
  });
});
