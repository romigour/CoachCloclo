/** Répartition de l'effort : facile (Z1-2), moyen (Z3), dur (Z4-5). */
import type { StatActivity } from "../api";
import type { Period } from "./filter";
import { zoneDistribution, zoneShares } from "./running";
import { nextMonth } from "./volume";

export type Split = { easy: number; moderate: number; hard: number };

/** Parts (0..1) du temps par niveau d'effort ; null sans temps. */
export function split(zones: number[]): Split | null {
  if (!zones.some((z) => z > 0)) return null;
  const [z1, z2, z3, z4, z5] = zoneShares(zones);
  return { easy: z1 + z2, moderate: z3, hard: z4 + z5 };
}

/** Répartition de chaque mois de la période ; null si le mois est vide ou mal couvert. */
export function monthlySplit(acts: StatActivity[], p: Period): { month: string; split: Split | null }[] {
  const byMonth = new Map<string, StatActivity[]>();
  for (const a of acts) {
    const m = a.date.slice(0, 7);
    byMonth.set(m, [...(byMonth.get(m) ?? []), a]);
  }
  const out: { month: string; split: Split | null }[] = [];
  for (let m = p.from.slice(0, 7); m <= p.to.slice(0, 7); m = nextMonth(m)) {
    const zones = zoneDistribution(byMonth.get(m) ?? []);
    out.push({ month: m, split: zones ? split(zones) : null });
  }
  return out;
}
