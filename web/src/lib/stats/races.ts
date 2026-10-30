/** Compétitions : catégories de distance, classements et progression par distance. */
import type { Family, StatActivity } from "../api";

export type DistanceCategory = "5k" | "10k" | "half" | "marathon";

export const CATEGORY_M: Record<DistanceCategory, number> = {
  "5k": 5000,
  "10k": 10000,
  half: 21097.5,
  marathon: 42195,
};

const TOLERANCE = 0.03;

/** Catégorie de distance (±3 %) ; jamais pour le trail. */
export function distanceCategory(distanceM: number | null, family: Family): DistanceCategory | null {
  if (distanceM == null || distanceM <= 0 || family === "trail") return null;
  for (const [cat, m] of Object.entries(CATEGORY_M) as [DistanceCategory, number][]) {
    if (Math.abs(distanceM - m) <= m * TOLERANCE) return cat;
  }
  return null;
}

export function topPercent(rank: number | null, total: number | null): number | null {
  if (rank == null || total == null || total <= 0) return null;
  return Math.max(1, Math.round((rank / total) * 100));
}

export type RaceRow = {
  activity: StatActivity;
  timeS: number | null;
  official: boolean;
  paceSKm: number | null;
  overallTop: number | null;
  categoryTop: number | null;
};

export function raceRows(acts: StatActivity[]): RaceRow[] {
  return acts
    .filter((a) => a.race != null)
    .map((a) => {
      const race = a.race!;
      const official = race.official_time_s != null;
      const timeS = race.official_time_s ?? a.duration_s;
      const paceSKm = timeS != null && a.distance_m ? timeS / (a.distance_m / 1000) : null;
      return {
        activity: a,
        timeS,
        official,
        paceSKm,
        overallTop: topPercent(race.overall_rank, race.overall_total),
        categoryTop: topPercent(race.category_rank, race.category_total),
      };
    })
    .sort((x, y) => y.activity.date.localeCompare(x.activity.date));
}

/** Évolution du temps par catégorie de distance (au moins 2 courses). */
export function raceProgression(
  acts: StatActivity[],
): { category: DistanceCategory; points: { date: string; timeS: number }[] }[] {
  const byCat = new Map<DistanceCategory, { date: string; timeS: number }[]>();
  for (const r of raceRows(acts)) {
    const cat = distanceCategory(r.activity.distance_m, r.activity.family);
    if (!cat || r.timeS == null) continue;
    const list = byCat.get(cat) ?? [];
    list.push({ date: r.activity.date, timeS: r.timeS });
    byCat.set(cat, list);
  }
  return (Object.keys(CATEGORY_M) as DistanceCategory[])
    .filter((c) => (byCat.get(c)?.length ?? 0) >= 2)
    .map((category) => ({
      category,
      points: byCat.get(category)!.sort((a, b) => a.date.localeCompare(b.date)),
    }));
}
