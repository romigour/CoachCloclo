/** Charge d'entraînement : TRIMP de Banister, forme, fatigue, fraîcheur, ACWR. Dates ISO, calculs en UTC. */
import type { StatActivity, Zones } from "../api";
import { addDays, daysBetween, mondayOf, type Period } from "./filter";

export const RAMP_ALERT = 0.15;
export const MISSING_HR_ALERT = 0.3;
const CTL_DAYS = 42;
const ATL_DAYS = 7;
const CHRONIC_DAYS = 28;

export type HrRange = { rest: number; max: number };
export type FitnessPoint = { date: string; ctl: number; atl: number; tsb: number };

/** FC repos et max retrouvées dans les zones Karvonen (Z1 bas = 50 % de la réserve) ; null sinon. */
export function hrRange(zones: Zones | null): HrRange | null {
  const z1 = zones?.hr.Z1;
  const z5 = zones?.hr.Z5;
  if (!zones?.source.includes("karvonen") || !z1 || !z5) return null;
  const max = z5[1];
  const rest = 2 * z1[0] - max;
  return rest > 0 && rest < max ? { rest, max } : null;
}

/** Charge d'une séance ; null sans FC ou sans durée. */
export function trimp(a: StatActivity, hr: HrRange): number | null {
  if (!a.avg_hr || !a.duration_s) return null;
  const x = Math.min(1, Math.max(0, (a.avg_hr - hr.rest) / (hr.max - hr.rest)));
  return (a.duration_s / 60) * x * 0.64 * Math.exp(1.92 * x);
}

function dailyLoad(all: StatActivity[], hr: HrRange): Map<string, number> {
  const out = new Map<string, number>();
  for (const a of all) out.set(a.date, (out.get(a.date) ?? 0) + (trimp(a, hr) ?? 0));
  return out;
}

const firstDate = (all: StatActivity[]) =>
  all.reduce<string | null>((min, a) => (min === null || a.date < min ? a.date : min), null);

/** Forme (42 j), fatigue (7 j) et fraîcheur de chaque jour, de la première activité à `today`. */
export function fitnessSeries(all: StatActivity[], hr: HrRange, today: string): FitnessPoint[] {
  const first = firstDate(all);
  if (first === null) return [];
  const load = dailyLoad(all, hr);
  const out: FitnessPoint[] = [];
  let ctl = 0;
  let atl = 0;
  for (let date = first; date <= today; date = addDays(date, 1)) {
    const l = load.get(date) ?? 0;
    ctl += (l - ctl) / CTL_DAYS;
    atl += (l - atl) / ATL_DAYS;
    out.push({ date, ctl, atl, tsb: ctl - atl });
  }
  return out;
}

/** Points de la période, sans la montée en charge artificielle des 42 premiers jours. */
export function visibleFitness(s: FitnessPoint[], p: Period): FitnessPoint[] {
  return s.slice(CTL_DAYS).filter((x) => x.date >= p.from && x.date <= p.to);
}

/** Charge moyenne 7 j / 28 j ; null avec moins de 28 jours d'historique ou sans charge. */
export function acwr(all: StatActivity[], hr: HrRange, today: string): number | null {
  const first = firstDate(all);
  if (first === null || daysBetween(first, today) + 1 < CHRONIC_DAYS) return null;
  const load = dailyLoad(all, hr);
  const mean = (n: number) => {
    let sum = 0;
    for (let i = 0; i < n; i++) sum += load.get(addDays(today, -i)) ?? 0;
    return sum / n;
  };
  const chronic = mean(CHRONIC_DAYS);
  return chronic > 0 ? mean(ATL_DAYS) / chronic : null;
}

/** Heures de la dernière semaine complète par rapport à la moyenne des 4 précédentes (0.15 = +15 %). */
export function weeklyRamp(acts: StatActivity[], today: string): number | null {
  const last = addDays(mondayOf(today), -7);
  const seconds = new Map<string, number>();
  for (const a of acts) {
    const w = mondayOf(a.date);
    seconds.set(w, (seconds.get(w) ?? 0) + (a.duration_s ?? 0));
  }
  const mean = [1, 2, 3, 4].reduce((s, i) => s + (seconds.get(addDays(last, -7 * i)) ?? 0), 0) / 4;
  return mean > 0 ? (seconds.get(last) ?? 0) / mean - 1 : null;
}

/** Séances sans FC des 42 derniers jours : nombre et part de la durée. */
export function hrCoverage(all: StatActivity[], today: string): { missing: number; missingShare: number } {
  const from = addDays(today, -(CTL_DAYS - 1));
  const recent = all.filter((a) => a.date >= from && a.date <= today);
  const without = recent.filter((a) => !a.avg_hr);
  const sum = (l: StatActivity[]) => l.reduce((s, a) => s + (a.duration_s ?? 0), 0);
  const total = sum(recent);
  return { missing: without.length, missingShare: total > 0 ? sum(without) / total : 0 };
}
