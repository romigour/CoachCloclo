import { describe, expect, it } from "vitest";
import type { RaceInfo, StatActivity } from "../api";
import { distanceCategory, raceProgression, raceRows, topPercent } from "./races";

function race(over: Partial<RaceInfo> = {}): RaceInfo {
  return {
    name: null, official_time_s: null, overall_rank: null, overall_total: null,
    category: null, category_rank: null, category_total: null, ...over,
  };
}
function act(date: string, over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date, start: null, name: null, family: "run", type_key: "running",
    duration_s: 3000, distance_m: 10000, d_plus_m: null, avg_hr: null, max_hr: null,
    vo2max: null, hr_zones_s: null, race: race(), ...over,
  };
}

describe("distanceCategory", () => {
  it("±3 %", () => {
    expect(distanceCategory(10300, "run")).toBe("10k");
    expect(distanceCategory(10400, "run")).toBeNull();
    expect(distanceCategory(5000, "run")).toBe("5k");
    expect(distanceCategory(21097.5, "run")).toBe("half");
    expect(distanceCategory(42195, "run")).toBe("marathon");
  });
  it("trail et distance absente -> null", () => {
    expect(distanceCategory(21000, "trail")).toBeNull();
    expect(distanceCategory(null, "run")).toBeNull();
  });
});

describe("topPercent", () => {
  it("arrondi, minimum 1, null si manquant", () => {
    expect(topPercent(12, 80)).toBe(15);
    expect(topPercent(1, 5000)).toBe(1);
    expect(topPercent(null, 80)).toBeNull();
    expect(topPercent(3, null)).toBeNull();
    expect(topPercent(3, 0)).toBeNull();
  });
});

describe("raceRows", () => {
  it("temps officiel prioritaire, plus récentes d'abord, ignore sans race", () => {
    const rows = raceRows([
      act("2026-01-01", { id: 1, race: race({ official_time_s: 2990, overall_rank: 12, overall_total: 80 }) }),
      act("2026-03-01", { id: 2 }),
      act("2026-02-01", { id: 3, race: null }),
    ]);
    expect(rows.map((r) => r.activity.id)).toEqual([2, 1]);
    expect(rows[1]).toMatchObject({ timeS: 2990, official: true, paceSKm: 299, overallTop: 15, categoryTop: null });
    expect(rows[0]).toMatchObject({ timeS: 3000, official: false, paceSKm: 300 });
  });
  it("allure null sans distance", () => {
    const rows = raceRows([act("2026-01-01", { distance_m: null })]);
    expect(rows[0].paceSKm).toBeNull();
  });
});

describe("raceProgression", () => {
  it("ignore une catégorie courue une seule fois, trié par date", () => {
    const r = raceProgression([
      act("2026-03-01", { distance_m: 10000, duration_s: 2900 }),
      act("2026-01-01", { distance_m: 10100, duration_s: 3000 }),
      act("2026-02-01", { distance_m: 5000, duration_s: 1400 }),
    ]);
    expect(r).toEqual([{ category: "10k", points: [
      { date: "2026-01-01", timeS: 3000 }, { date: "2026-03-01", timeS: 2900 },
    ] }]);
  });
});
