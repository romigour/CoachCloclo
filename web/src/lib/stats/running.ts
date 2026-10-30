/** Progression en course à pied : efficacité aérobie, VO2max, sortie longue, zones FC, trail. */
import type { StatActivity } from "../api";
import { daysBetween } from "./filter";

export const MIN_DURATION_S = 1200;
export const MAX_DPLUS_PER_KM = 10;
export const MIN_TREND_POINTS = 8;
export const MIN_ZONE_COVERAGE = 0.5;

const isRunOrTrail = (a: StatActivity) => a.family === "run" || a.family === "trail";

/** Efficacité aérobie : (m/min) / FC moyenne, sur les sorties « plates » d'au moins 20 min. */
export function aerobicEfficiency(acts: StatActivity[]): {
  points: { date: string; value: number }[];
  trend: { slope: number; intercept: number } | null;
} {
  const points = acts
    .filter(
      (a) =>
        a.family === "run" &&
        (a.duration_s ?? 0) >= MIN_DURATION_S &&
        a.avg_hr != null && a.avg_hr > 0 &&
        a.distance_m != null && a.distance_m > 0 &&
        (a.d_plus_m ?? 0) / (a.distance_m / 1000) <= MAX_DPLUS_PER_KM,
    )
    .map((a) => ({
      date: a.date,
      value: a.distance_m! / (a.duration_s! / 60) / a.avg_hr!,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));

  if (points.length < MIN_TREND_POINTS) return { points, trend: null };

  // Moindres carrés sur x = jours depuis le premier point.
  const xs = points.map((p) => daysBetween(points[0].date, p.date));
  const n = points.length;
  const mx = xs.reduce((s, x) => s + x, 0) / n;
  const my = points.reduce((s, p) => s + p.value, 0) / n;
  let sxx = 0;
  let sxy = 0;
  xs.forEach((x, i) => {
    sxx += (x - mx) ** 2;
    sxy += (x - mx) * (points[i].value - my);
  });
  if (sxx === 0) return { points, trend: null };
  const slope = sxy / sxx;
  return { points, trend: { slope, intercept: my - slope * mx } };
}

export function vo2maxSeries(acts: StatActivity[]): { date: string; value: number }[] {
  return acts
    .filter((a) => isRunOrTrail(a) && a.vo2max != null)
    .map((a) => ({ date: a.date, value: a.vo2max! }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

/** Plus longue sortie (km) de chaque mois ayant au moins une sortie avec distance. */
export function longestRunByMonth(acts: StatActivity[]): { month: string; km: number }[] {
  const best = new Map<string, number>();
  for (const a of acts) {
    if (!isRunOrTrail(a) || !a.distance_m) continue;
    const m = a.date.slice(0, 7);
    best.set(m, Math.max(best.get(m) ?? 0, a.distance_m / 1000));
  }
  return [...best.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, km]) => ({ month, km }));
}

/** Secondes cumulées par zone FC ; null si couverture insuffisante. */
export function zoneDistribution(acts: StatActivity[]): number[] | null {
  const runs = acts.filter(isRunOrTrail);
  if (runs.length === 0) return null;
  const withZones = runs.filter((a) => a.hr_zones_s != null);
  if (withZones.length / runs.length < MIN_ZONE_COVERAGE) return null;
  const total = [0, 0, 0, 0, 0];
  for (const a of withZones) a.hr_zones_s!.forEach((s, i) => { if (i < 5) total[i] += s ?? 0; });
  return total;
}

/** D+ cumulé et D+ par km (trails avec distance uniquement pour le ratio). */
export function trailSummary(acts: StatActivity[]): { dPlusM: number; dPlusPerKm: number } | null {
  const trails = acts.filter((a) => a.family === "trail");
  if (trails.length === 0) return null;
  const dPlusM = trails.reduce((s, a) => s + (a.d_plus_m ?? 0), 0);
  const withDist = trails.filter((a) => a.distance_m != null && a.distance_m > 0);
  const km = withDist.reduce((s, a) => s + a.distance_m! / 1000, 0);
  const dPlusForRatio = withDist.reduce((s, a) => s + (a.d_plus_m ?? 0), 0);
  return { dPlusM, dPlusPerKm: km > 0 ? dPlusForRatio / km : 0 };
}
