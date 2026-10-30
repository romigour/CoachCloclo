import { describe, expect, it } from "vitest";
import type { StatActivity } from "../api";
import {
  MAX_DPLUS_PER_KM, MIN_DURATION_S, MIN_TREND_POINTS, MIN_ZONE_COVERAGE,
  aerobicEfficiency, easyShare, longestRunByMonth, trailSummary, trendLine, vo2maxSeries, zoneDistribution, zoneShares,
} from "./running";

function act(date: string, over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date, start: null, name: null, family: "run", type_key: "running",
    duration_s: 3600, distance_m: 10000, d_plus_m: null, avg_hr: 150, max_hr: null,
    vo2max: null, hr_zones_s: null, race: null, ...over,
  };
}

describe("constantes", () => {
  it("valeurs des contraintes globales", () => {
    expect([MIN_DURATION_S, MAX_DPLUS_PER_KM, MIN_TREND_POINTS, MIN_ZONE_COVERAGE]).toEqual([1200, 10, 8, 0.5]);
  });
});

describe("aerobicEfficiency", () => {
  it("calcule (m/min)/FC", () => {
    const r = aerobicEfficiency([act("2026-01-01")]);
    expect(r.points).toEqual([{ date: "2026-01-01", value: 10000 / 60 / 150 }]);
  });

  it("exclut trail, < 20 min, sans FC, sans distance, > 10 m/km", () => {
    const r = aerobicEfficiency([
      act("2026-01-01", { family: "trail" }),
      act("2026-01-02", { duration_s: 1199 }),
      act("2026-01-03", { avg_hr: null }),
      act("2026-01-04", { distance_m: null }),
      act("2026-01-05", { d_plus_m: 120 }),
      act("2026-01-06", { duration_s: null }),
    ]);
    expect(r.points).toEqual([]);
    expect(r.trend).toBeNull();
  });

  it("garde 20 min pile et 10 m/km pile", () => {
    const r = aerobicEfficiency([act("2026-01-01", { duration_s: 1200, d_plus_m: 100 })]);
    expect(r.points).toHaveLength(1);
  });

  it("tendance null à 7 points, pente positive à 8", () => {
    const mk = (n: number) =>
      Array.from({ length: n }, (_, i) =>
        act(`2026-01-${String(i + 1).padStart(2, "0")}`, { avg_hr: 160 - i }));
    expect(aerobicEfficiency(mk(7)).trend).toBeNull();
    const t = aerobicEfficiency(mk(8)).trend;
    expect(t).not.toBeNull();
    expect(t!.slope).toBeGreaterThan(0);
  });

  it("ne produit jamais NaN avec x identiques", () => {
    const same = Array.from({ length: 8 }, () => act("2026-01-01"));
    const t = aerobicEfficiency(same).trend;
    expect(t === null || Number.isFinite(t.slope)).toBe(true);
  });
});

describe("vo2maxSeries", () => {
  it("run et trail avec vo2max, triés par date", () => {
    const r = vo2maxSeries([
      act("2026-02-01", { vo2max: 52 }),
      act("2026-01-01", { vo2max: 50, family: "trail" }),
      act("2026-01-15", { vo2max: null }),
      act("2026-01-20", { vo2max: 60, family: "bike" }),
    ]);
    expect(r).toEqual([{ date: "2026-01-01", value: 50 }, { date: "2026-02-01", value: 52 }]);
  });
});

describe("longestRunByMonth", () => {
  it("max km par mois, run + trail", () => {
    const r = longestRunByMonth([
      act("2026-01-03", { distance_m: 10000 }),
      act("2026-01-20", { distance_m: 21000, family: "trail" }),
      act("2026-02-02", { distance_m: 5000 }),
      act("2026-02-03", { distance_m: 99000, family: "bike" }),
      act("2026-03-03", { distance_m: null }),
    ]);
    expect(r).toEqual([{ month: "2026-01", km: 21 }, { month: "2026-02", km: 5 }]);
  });
});

describe("zoneDistribution", () => {
  it("null sans course", () => {
    expect(zoneDistribution([act("2026-01-01", { family: "bike" })])).toBeNull();
  });
  it("null quand 1 course sur 3 a des zones", () => {
    expect(zoneDistribution([
      act("2026-01-01", { hr_zones_s: [1, 2, 3, 4, 5] }), act("2026-01-02"), act("2026-01-03"),
    ])).toBeNull();
  });
  it("cumule les zones", () => {
    expect(zoneDistribution([
      act("2026-01-01", { hr_zones_s: [1, 2, 3, 4, 5] }),
      act("2026-01-02", { hr_zones_s: [1, 1, 1, 1, 1], family: "trail" }),
    ])).toEqual([2, 3, 4, 5, 6]);
  });
});

describe("trailSummary", () => {
  it("null sans trail", () => {
    expect(trailSummary([act("2026-01-01")])).toBeNull();
  });
  it("cumule le D+ et ratio sur les trails avec distance", () => {
    const r = trailSummary([
      act("2026-01-01", { family: "trail", d_plus_m: 500, distance_m: 10000 }),
      act("2026-01-02", { family: "trail", d_plus_m: 300, distance_m: null }),
    ]);
    expect(r).toEqual({ dPlusM: 800, dPlusPerKm: 50 });
  });
  it("ratio 0 si aucune distance", () => {
    expect(trailSummary([act("2026-01-01", { family: "trail", d_plus_m: 300, distance_m: null })]))
      .toEqual({ dPlusM: 300, dPlusPerKm: 0 });
  });
});

describe("easyShare", () => {
  it("part des zones 1-2", () => {
    expect(easyShare([600, 1200, 300, 200, 100])).toBeCloseTo(0.75);
  });
  it("null si aucun temps", () => {
    expect(easyShare([0, 0, 0, 0, 0])).toBeNull();
  });
});

describe("trendLine", () => {
  const points = [
    { date: "2026-01-01", value: 1.5 },
    { date: "2026-01-11", value: 1.6 },
  ];
  it("extrémités de la droite et variation relative", () => {
    const t = trendLine(points, { slope: 0.01, intercept: 1.5 })!;
    expect(t.start).toEqual({ date: "2026-01-01", value: 1.5 });
    expect(t.end.date).toBe("2026-01-11");
    expect(t.end.value).toBeCloseTo(1.6);
    expect(t.changePct).toBeCloseTo(6.667, 2);
  });
  it("null sans tendance", () => {
    expect(trendLine(points, null)).toBeNull();
  });
});

describe("zoneShares", () => {
  it("part de chaque zone", () => {
    expect(zoneShares([600, 1200, 300, 200, 100])).toEqual([0.25, 0.5, 0.125, 200 / 2400, 100 / 2400]);
  });
  it("zéros si aucun temps", () => {
    expect(zoneShares([0, 0, 0, 0, 0])).toEqual([0, 0, 0, 0, 0]);
  });
});
