import type { Activity } from "./api";
import { formatShortDay } from "./dates";

const km = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** « mar. 11/11 · 52 min · 10,2 km » */
export function formatActivity(a: Activity): string {
  const parts = [formatShortDay(a.date)];
  if (a.duration_s != null) parts.push(`${Math.round(a.duration_s / 60)} min`);
  if (a.distance_m != null) parts.push(`${km.format(a.distance_m / 1000)} km`);
  return parts.join(" · ");
}
