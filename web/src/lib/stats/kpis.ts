/** Chiffres clés de la page de statistiques, avec variation par rapport à la période précédente. */
import type { StatActivity } from "../api";

export type Kpi = {
  key: "hours" | "run_km" | "sessions" | "d_plus";
  value: number;
  /** Variation relative (0.12 = +12 %) ; null sans période précédente ou si sa valeur vaut 0. */
  delta: number | null;
};

function totals(acts: StatActivity[]): Record<Kpi["key"], number> {
  let seconds = 0;
  let runM = 0;
  let dPlus = 0;
  for (const a of acts) {
    seconds += a.duration_s ?? 0;
    if (a.family === "run" || a.family === "trail") runM += a.distance_m ?? 0;
    dPlus += a.d_plus_m ?? 0;
  }
  return { hours: seconds / 3600, run_km: runM / 1000, sessions: acts.length, d_plus: dPlus };
}

export function computeKpis(current: StatActivity[], previous: StatActivity[] | null): Kpi[] {
  const cur = totals(current);
  const prev = previous === null ? null : totals(previous);
  return (["hours", "run_km", "sessions", "d_plus"] as const).map((key) => {
    const before = prev?.[key] ?? 0;
    return { key, value: cur[key], delta: prev === null || before === 0 ? null : (cur[key] - before) / before };
  });
}
