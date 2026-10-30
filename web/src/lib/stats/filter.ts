/** Filtres de période et de sport pour la page de statistiques. Dates ISO (AAAA-MM-JJ), calculs en UTC. */
import type { Family, StatActivity } from "../api";
import { addDays } from "../dates";

export type Period = { from: string; to: string };

export type PeriodChoice =
  | { kind: "12m" }
  | { kind: "year"; year: number }
  | { kind: "all" }
  | { kind: "custom"; from: string; to: string };

/** `running` regroupe `run` et `trail`. */
export type SportFilter = "all" | "running" | Family;

const FAMILIES: Family[] = ["run", "trail", "bike", "swim", "strength", "walk", "other"];

const DAY_MS = 86_400_000;

function utcMs(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function toIso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export { addDays };

/** Nombre de jours de `a` à `b` (positif si `b` est après `a`). */
export function daysBetween(a: string, b: string): number {
  return Math.round((utcMs(b) - utcMs(a)) / DAY_MS);
}

/** Lundi de la semaine contenant `iso` (semaines du lundi au dimanche). */
export function mondayOf(iso: string): string {
  const dow = new Date(utcMs(iso)).getUTCDay(); // 0 = dimanche
  return addDays(iso, -((dow + 6) % 7));
}

/** Même jour un an plus tôt ; le 29 février retombe sur le 28. */
function yearAgo(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const ms = Date.UTC(y - 1, m - 1, d);
  return new Date(ms).getUTCMonth() === m - 1 ? toIso(ms) : toIso(Date.UTC(y - 1, m - 1, d - 1));
}

export function resolvePeriod(choice: PeriodChoice, today: string, acts: StatActivity[]): Period {
  switch (choice.kind) {
    case "12m":
      return { from: addDays(yearAgo(today), 1), to: today };
    case "year": {
      const end = `${choice.year}-12-31`;
      return { from: `${choice.year}-01-01`, to: end > today ? today : end };
    }
    case "custom":
      return { from: choice.from, to: choice.to };
    case "all": {
      const first = acts.reduce<string | null>((min, a) => (min === null || a.date < min ? a.date : min), null);
      return { from: first ?? today, to: today };
    }
  }
}

/** Période de même durée, juste avant `p`. */
export function previousPeriod(p: Period): Period {
  const len = daysBetween(p.from, p.to) + 1;
  const to = addDays(p.from, -1);
  return { from: addDays(to, -(len - 1)), to };
}

export function filterActivities(acts: StatActivity[], p: Period, sport: SportFilter): StatActivity[] {
  return acts.filter((a) => {
    if (a.date < p.from || a.date > p.to) return false;
    if (sport === "all") return true;
    if (sport === "running") return a.family === "run" || a.family === "trail";
    return a.family === sport;
  });
}

/** `all`, `running` si course ou trail présents, puis chaque famille présente (ordre de `Family`). */
export function sportOptions(acts: StatActivity[]): SportFilter[] {
  const present = new Set(acts.map((a) => a.family));
  const out: SportFilter[] = ["all"];
  if (present.has("run") || present.has("trail")) out.push("running");
  for (const f of FAMILIES) if (present.has(f)) out.push(f);
  return out;
}
