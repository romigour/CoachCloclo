/** Volume par semaine ou par mois, réparti par famille, et part de chaque sport. */
import type { Family, StatActivity } from "../api";
import { addDays, daysBetween, mondayOf, type Period } from "./filter";

export type Bucket = "week" | "month";

const FAMILIES: Family[] = ["run", "trail", "bike", "swim", "strength", "walk", "other"];

/** Semaines jusqu'à ~6 mois (183 jours), mois au-delà. */
export function bucketFor(p: Period): Bucket {
  return daysBetween(p.from, p.to) + 1 <= 183 ? "week" : "month";
}

function nextMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
}

export function volumeSeries(
  acts: StatActivity[],
  p: Period,
  metric: "hours" | "km",
): { labels: string[]; series: { family: Family; values: number[] }[]; movingAvg: (number | null)[] } {
  const bucket = bucketFor(p);
  const key = (iso: string) => (bucket === "week" ? mondayOf(iso) : iso.slice(0, 7));

  const labels: string[] = [];
  if (bucket === "week") {
    for (let w = mondayOf(p.from); w <= p.to; w = addDays(w, 7)) labels.push(w);
  } else {
    for (let m = p.from.slice(0, 7); m <= p.to.slice(0, 7); m = nextMonth(m)) labels.push(m);
  }
  const index = new Map(labels.map((l, i) => [l, i]));

  const byFamily = new Map<Family, number[]>();
  for (const a of acts) {
    if (a.date < p.from || a.date > p.to) continue;
    const i = index.get(key(a.date));
    if (i === undefined) continue;
    const values = byFamily.get(a.family) ?? new Array<number>(labels.length).fill(0);
    values[i] += metric === "hours" ? (a.duration_s ?? 0) / 3600 : (a.distance_m ?? 0) / 1000;
    byFamily.set(a.family, values);
  }

  // Une famille sans volume pour la métrique (ex. renfo en km) n'a rien à tracer.
  const series = FAMILIES.filter((f) => byFamily.get(f)?.some((v) => v > 0)).map((family) => ({
    family,
    values: byFamily.get(family)!,
  }));
  const totals = labels.map((_, i) => series.reduce((s, x) => s + x.values[i], 0));
  const movingAvg = totals.map((_, i) => (i < 3 ? null : (totals[i - 3] + totals[i - 2] + totals[i - 1] + totals[i]) / 4));
  return { labels, series, movingAvg };
}

/** Heures par famille, décroissantes ; les familles à 0 h sont exclues. */
export function sportShare(acts: StatActivity[]): { family: Family; hours: number }[] {
  const secs = new Map<Family, number>();
  for (const a of acts) secs.set(a.family, (secs.get(a.family) ?? 0) + (a.duration_s ?? 0));
  return FAMILIES.map((family) => ({ family, hours: (secs.get(family) ?? 0) / 3600 }))
    .filter((x) => x.hours > 0)
    .sort((a, b) => b.hours - a.hours);
}
