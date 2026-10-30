import { describe, expect, it } from "vitest";
import type { StatActivity } from "../api";
import { bucketFor, sportShare, volumeSeries } from "./volume";

function act(date: string, over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date, start: null, name: null, family: "run", type_key: "running",
    duration_s: 3600, distance_m: 10000, d_plus_m: null, avg_hr: null, max_hr: null,
    vo2max: null, hr_zones_s: null, race: null, ...over,
  };
}

describe("bucketFor", () => {
  it("90 jours -> semaine, 400 jours -> mois", () => {
    expect(bucketFor({ from: "2026-08-01", to: "2026-10-29" })).toBe("week");
    expect(bucketFor({ from: "2025-09-25", to: "2026-10-29" })).toBe("month");
  });
});

describe("volumeSeries", () => {
  it("inclut les mois vides à 0", () => {
    const p = { from: "2025-01-01", to: "2026-02-28" };
    const r = volumeSeries([act("2025-01-10"), act("2026-02-03")], p, "hours");
    expect(r.labels).toHaveLength(14);
    expect(r.labels[0]).toBe("2025-01");
    expect(r.series).toHaveLength(1);
    expect(r.series[0].values[1]).toBe(0);
    expect(r.series[0].values[0]).toBe(1);
  });

  it("inclut les semaines vides et une série par famille présente", () => {
    const p = { from: "2026-10-05", to: "2026-10-25" };
    const r = volumeSeries([act("2026-10-06"), act("2026-10-20", { family: "bike" })], p, "hours");
    expect(r.labels).toEqual(["2026-10-05", "2026-10-12", "2026-10-19"]);
    expect(r.series.map((s) => s.family)).toEqual(["run", "bike"]);
    expect(r.series[0].values).toEqual([1, 0, 0]);
  });

  it("movingAvg : null puis moyenne glissante sur 4", () => {
    const p = { from: "2026-10-05", to: "2026-11-01" };
    const acts = [1, 2, 3, 4].map((h, i) => act(`2026-10-${String(5 + 7 * i).padStart(2, "0")}`, { duration_s: h * 3600 }));
    const r = volumeSeries(acts, p, "hours");
    expect(r.movingAvg.slice(0, 3)).toEqual([null, null, null]);
    expect(r.movingAvg[3]).toBeCloseTo(2.5);
  });

  it("en km, une activité sans distance compte 0 (pas de NaN)", () => {
    const p = { from: "2026-10-05", to: "2026-10-11" };
    const r = volumeSeries([act("2026-10-06", { distance_m: null }), act("2026-10-07", { distance_m: 5000 })], p, "km");
    expect(r.series[0].values).toEqual([5]);
  });
});

describe("sportShare", () => {
  it("trie par heures décroissantes et exclut les 0 h", () => {
    const r = sportShare([
      act("2026-10-01", { family: "bike", duration_s: 7200 }),
      act("2026-10-02", { family: "run", duration_s: 3600 }),
      act("2026-10-03", { family: "swim", duration_s: null }),
    ]);
    expect(r).toEqual([{ family: "bike", hours: 2 }, { family: "run", hours: 1 }]);
  });
});
