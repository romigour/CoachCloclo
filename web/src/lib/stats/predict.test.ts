import { describe, expect, it } from "vitest";
import type { PersonalRecord, RaceInfo, StatActivity } from "../api";
import { addDays } from "./filter";
import { predictions, references, type Reference } from "./predict";

const TODAY = "2026-11-25";
const RACE: RaceInfo = {
  name: null, official_time_s: null, overall_rank: null, overall_total: null,
  category: null, category_rank: null, category_total: null,
};
function act(over: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date: "2026-10-01", start: null, name: null, family: "run", type_key: "running",
    duration_s: 3000, distance_m: 10000, d_plus_m: null, avg_hr: 150, max_hr: null,
    vo2max: null, hr_zones_s: null, race: RACE, ...over,
  };
}
const rec = (kind: PersonalRecord["kind"], value: number, date: string | null = "2026-10-01"): PersonalRecord =>
  ({ kind, value, garmin_activity_id: null, date });
const ref = (category: Reference["category"], timeS: number, date = "2026-10-01"): Reference =>
  ({ category, timeS, date, source: "record" });
const byCat = (refs: Reference[], c: Reference["category"]) => predictions(refs).find((p) => p.category === c);

describe("references", () => {
  it("compétition : temps officiel, à défaut montre", () => {
    expect(references([act()], [], TODAY)).toEqual([{ category: "10k", timeS: 3000, date: "2026-10-01", source: "race" }]);
    expect(references([act({ race: { ...RACE, official_time_s: 2990 } })], [], TODAY)[0].timeS).toBe(2990);
  });
  it("exclut trail, sortie ordinaire, distance hors catégorie et temps absent", () => {
    expect(
      references([act({ family: "trail" }), act({ race: null }), act({ distance_m: 12000 }), act({ duration_s: null })], [], TODAY),
    ).toEqual([]);
  });
  it("365 jours gardé, 366 exclu, futur exclu", () => {
    const at = (d: number) => references([act({ date: addDays(TODAY, d) })], [], TODAY).length;
    expect([at(-365), at(-366), at(0), at(1)]).toEqual([1, 0, 1, 0]);
  });
  it("records utiles seulement, datés et positifs", () => {
    const list = [rec("1k", 200), rec("1mile", 350), rec("longest_run", 30000), rec("5k", 0), rec("half", 6000, null), rec("10k", 2900)];
    expect(references([], list, TODAY)).toEqual([ref("10k", 2900)]);
  });
});

describe("predictions", () => {
  it("Riegel depuis 10 km en 3000 s", () => {
    const refs = [ref("10k", 3000)];
    expect(byCat(refs, "5k")!.timeS).toBeCloseTo(1438.9, 0);
    expect(byCat(refs, "10k")!.timeS).toBe(3000);
    expect(byCat(refs, "half")!.timeS).toBeCloseTo(6619, -1);
  });
  it("pas de prédiction au-delà d'un rapport de 4", () => {
    expect(byCat([ref("10k", 3000)], "marathon")).toBeUndefined();
    expect(byCat([ref("marathon", 14000)], "10k")).toBeUndefined();
  });
  it("référence la plus proche", () => expect(byCat([ref("half", 6000), ref("5k", 1300)], "10k")!.from.category).toBe("5k"));
  it("à égalité, la plus récente", () => {
    expect(byCat([ref("10k", 3000, "2026-03-01"), ref("10k", 3100, "2026-09-01")], "5k")!.from.timeS).toBe(3100);
  });
  it("vide sans référence", () => expect(predictions([])).toEqual([]));
});
