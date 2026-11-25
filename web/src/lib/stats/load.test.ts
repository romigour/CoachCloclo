import { describe, expect, it } from "vitest";
import type { StatActivity, Zones } from "../api";
import { addDays } from "./filter";
import { acwr, fitnessSeries, hrCoverage, hrRange, trimp, visibleFitness, weeklyRamp } from "./load";

const HR = { rest: 50, max: 190 };
const T = 108.095;

function act(over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date: "2026-11-25", start: null, name: null, family: "run", type_key: "running",
    duration_s: 3600, distance_m: 10000, d_plus_m: null, avg_hr: 150, max_hr: null,
    vo2max: null, hr_zones_s: null, race: null, ...over,
  };
}
/** Une séance identique par jour, `n` jours jusqu'à `today` compris. */
const daily = (n: number, today: string) => Array.from({ length: n }, (_, i) => act({ date: addDays(today, -i) }));

describe("hrRange", () => {
  it("déduit FC repos et max des zones Karvonen", () => {
    expect(hrRange({ pace: null, hr: { Z1: [120, 134], Z5: [176, 190] }, source: ["karvonen"] })).toEqual(HR);
  });
  it("null sans zones, sans Karvonen ou si repos >= max", () => {
    expect(hrRange(null)).toBeNull();
    expect(hrRange({ pace: null, hr: { Z1: [120, 134], Z5: [176, 190] }, source: [] })).toBeNull();
    expect(hrRange({ pace: null, hr: { Z1: [190, 190], Z5: [190, 190] }, source: ["karvonen"] })).toBeNull();
    expect(hrRange({ pace: null, hr: {}, source: ["karvonen"] })).toBeNull();
    expect(hrRange({} as Zones)).toBeNull(); // réponse incomplète : pas de plantage
  });
});

describe("trimp", () => {
  it("formule de Banister", () => expect(trimp(act(), HR)).toBeCloseTo(108.1, 1));
  it("null sans FC ou sans durée", () => {
    expect(trimp(act({ avg_hr: null }), HR)).toBeNull();
    expect(trimp(act({ avg_hr: 0 }), HR)).toBeNull();
    expect(trimp(act({ duration_s: null }), HR)).toBeNull();
  });
  it("x borné à [0, 1]", () => {
    expect(trimp(act({ avg_hr: 40 }), HR)).toBe(0);
    expect(trimp(act({ avg_hr: 210 }), HR)).toBe(trimp(act({ avg_hr: 190 }), HR));
  });
});

describe("fitnessSeries", () => {
  it("un jour de charge puis un jour vide", () => {
    const s = fitnessSeries([act({ date: "2026-11-24" })], HR, "2026-11-25");
    expect(s.map((p) => p.date)).toEqual(["2026-11-24", "2026-11-25"]);
    expect(s[0].ctl).toBeCloseTo(T / 42, 2);
    expect(s[0].atl).toBeCloseTo(T / 7, 2);
    expect(s[1].atl).toBeCloseTo((T / 7) * (6 / 7), 2);
    expect(s[1].tsb).toBeCloseTo(s[1].ctl - s[1].atl, 6);
  });
  it("vide sans activité, futur ignoré", () => {
    expect(fitnessSeries([], HR, "2026-01-01")).toEqual([]);
    expect(fitnessSeries([act({ date: "2026-11-26" })], HR, "2026-11-25")).toEqual([]);
  });
  it("les 42 premiers jours sont masqués", () => {
    const s = fitnessSeries(daily(100, "2026-11-25"), HR, "2026-11-25");
    const p = { from: "2020-01-01", to: "2026-11-25" };
    expect(visibleFitness(s, p)[0].date).toBe(s[42].date);
    expect(visibleFitness(s, p)).toHaveLength(58);
    expect(visibleFitness(s.slice(0, 42), p)).toEqual([]);
    expect(visibleFitness(s, { from: "2026-11-20", to: "2026-11-21" })).toHaveLength(2);
  });
});

describe("acwr", () => {
  it("charge constante : 1", () => expect(acwr(daily(28, "2026-11-25"), HR, "2026-11-25")).toBeCloseTo(1, 6));
  it("null avec moins de 28 jours ou sans charge", () => {
    expect(acwr(daily(27, "2026-11-25"), HR, "2026-11-25")).toBeNull();
    expect(acwr([act({ date: "2026-01-01" })], HR, "2026-11-25")).toBeNull();
  });
});

describe("weeklyRamp", () => {
  // mercredi 2026-11-25 : dernière semaine complète = lundi 16 → dimanche 22
  const weeks = [-28, -21, -14, -7].map((d) => act({ date: addDays("2026-11-18", d), duration_s: 4 * 3600 }));
  it("compare aux 4 semaines précédentes, semaine en cours ignorée", () => {
    const acts = [...weeks, act({ date: "2026-11-18", duration_s: 5 * 3600 }), act({ date: "2026-11-24", duration_s: 99999 })];
    expect(weeklyRamp(acts, "2026-11-25")).toBeCloseTo(0.25, 6);
  });
  it("null si la moyenne est nulle", () => {
    expect(weeklyRamp([], "2026-11-25")).toBeNull();
    expect(weeklyRamp([act({ date: "2026-11-18" })], "2026-11-25")).toBeNull();
  });
});

describe("hrCoverage", () => {
  it("nombre et part en durée, 42 derniers jours", () => {
    const acts = [act(), act({ avg_hr: null }), act({ avg_hr: null, date: addDays("2026-11-25", -42) })];
    expect(hrCoverage(acts, "2026-11-25")).toEqual({ missing: 1, missingShare: 0.5 });
    expect(hrCoverage([], "2026-11-25")).toEqual({ missing: 0, missingShare: 0 });
  });
});
