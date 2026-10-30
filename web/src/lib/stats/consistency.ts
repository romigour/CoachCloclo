/** Régularité : minutes par jour et séries de semaines actives. Dates ISO, semaines du lundi au dimanche. */
import type { StatActivity } from "../api";
import { addDays, daysBetween, mondayOf, type Period } from "./filter";

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

export type CalendarRange = { from: string; to: string; weeks: number };

/** Semaines (colonnes lundi-dimanche) touchées par l'intervalle. */
function weeksSpanned(from: string, to: string): number {
  return daysBetween(mondayOf(from), mondayOf(to)) / 7 + 1;
}

/**
 * Rangées du calendrier de régularité, bornées à la période : une seule rangée jusqu'à
 * 53 semaines, sinon une par année civile (première et dernière tronquées à la période).
 */
export function calendarRanges(p: Period): CalendarRange[] {
  const weeks = weeksSpanned(p.from, p.to);
  if (weeks <= 53) return [{ from: p.from, to: p.to, weeks }];
  const out: CalendarRange[] = [];
  for (let y = Number(p.from.slice(0, 4)); y <= Number(p.to.slice(0, 4)); y++) {
    const from = `${y}-01-01` < p.from ? p.from : `${y}-01-01`;
    const to = `${y}-12-31` > p.to ? p.to : `${y}-12-31`;
    out.push({ from, to, weeks: weeksSpanned(from, to) });
  }
  return out;
}
