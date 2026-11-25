/** Prédicteur de temps de course (Riegel) à partir de compétitions et de records récents. */
import type { PersonalRecord, StatActivity } from "../api";
import { daysBetween } from "./filter";
import { CATEGORY_M, distanceCategory, raceRows, type DistanceCategory } from "./races";

const MAX_AGE_DAYS = 365;
const MAX_RATIO = 4;
const EXPONENT = 1.06;
const CATEGORIES = Object.keys(CATEGORY_M) as DistanceCategory[];

export type Reference = { category: DistanceCategory; timeS: number; date: string; source: "race" | "record" };
export type Prediction = { category: DistanceCategory; timeS: number; from: Reference };

/** Compétitions sur route et records Garmin d'un an au plus, sur une distance connue. */
export function references(all: StatActivity[], records: PersonalRecord[], today: string): Reference[] {
  const out: Reference[] = [];
  for (const r of raceRows(all)) {
    const category = distanceCategory(r.activity.distance_m, r.activity.family);
    if (category && r.timeS != null) out.push({ category, timeS: r.timeS, date: r.activity.date, source: "race" });
  }
  for (const r of records) {
    const category = CATEGORIES.find((c) => c === r.kind);
    if (category && r.date) out.push({ category, timeS: r.value, date: r.date, source: "record" });
  }
  return out.filter((r) => {
    const age = daysBetween(r.date, today);
    return r.timeS > 0 && age >= 0 && age <= MAX_AGE_DAYS;
  });
}

/** Temps prédit par distance, depuis la référence la plus proche ; distances trop éloignées omises. */
export function predictions(refs: Reference[]): Prediction[] {
  const out: Prediction[] = [];
  for (const category of CATEGORIES) {
    const gap = (r: Reference) => Math.abs(Math.log(CATEGORY_M[category] / CATEGORY_M[r.category]));
    const from = [...refs].sort((a, b) => gap(a) - gap(b) || b.date.localeCompare(a.date))[0];
    if (!from || gap(from) > Math.log(MAX_RATIO)) continue;
    out.push({ category, timeS: from.timeS * (CATEGORY_M[category] / CATEGORY_M[from.category]) ** EXPONENT, from });
  }
  return out;
}
