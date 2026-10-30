/** Régularité : minutes par jour et séries de semaines actives. Dates ISO, semaines du lundi au dimanche. */
import type { StatActivity } from "../api";
import { addDays, mondayOf, type Period } from "./filter";

/** Minutes (arrondies) par jour ayant au moins une activité, triées par date. */
export function dailyMinutes(acts: StatActivity[]): [string, number][] {
  const secs = new Map<string, number>();
  for (const a of acts) secs.set(a.date, (secs.get(a.date) ?? 0) + (a.duration_s ?? 0));
  return [...secs.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([d, s]) => [d, Math.round(s / 60)]);
}

export type WeekStats = { activeWeeks: number; totalWeeks: number; currentStreak: number; bestStreak: number };

/**
 * Semaines (lundi-dimanche) couvrant `p`. La semaine en cours (contenant `today`) compte si
 * elle est active et ne casse pas la série tant qu'elle est vide.
 */
export function weekStats(acts: StatActivity[], p: Period, today: string): WeekStats {
  const active = new Set<string>();
  for (const a of acts) if (a.date >= p.from && a.date <= p.to) active.add(mondayOf(a.date));

  const weeks: string[] = [];
  for (let w = mondayOf(p.from); w <= p.to; w = addDays(w, 7)) weeks.push(w);

  let best = 0;
  let run = 0;
  for (const w of weeks) {
    run = active.has(w) ? run + 1 : 0;
    best = Math.max(best, run);
  }

  // Série courante : on remonte depuis la dernière semaine, en ignorant la semaine en cours si elle est vide.
  let i = weeks.length - 1;
  if (i >= 0 && weeks[i] === mondayOf(today) && !active.has(weeks[i])) i--;
  let current = 0;
  for (; i >= 0 && active.has(weeks[i]); i--) current++;

  return { activeWeeks: weeks.filter((w) => active.has(w)).length, totalWeeks: weeks.length, currentStreak: current, bestStreak: best };
}
