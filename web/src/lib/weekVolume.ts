/** Kilomètres et D+ prévus d'une semaine (ordres de grandeur). */

import type { Activity, Session, Step, Zones } from "./api";
import { addDays } from "./dates";

// zones de FC assimilées à l'allure correspondante
const HR_TO_PACE: Record<string, string> = { Z1: "récup", Z2: "EF", Z3: "marathon", Z4: "seuil", Z5: "VMA" };
/** Début des 8 semaines de sorties prises en compte. */
export const trailSince = (today: string) => addDays(today, -56);

/** Allure moyenne (s/km) des sorties trail (`activities`) des 8 dernières semaines. */
export function trailPace(activities: Activity[], today: string): number | null {
  const from = trailSince(today);
  let seconds = 0;
  let meters = 0;
  for (const a of activities) {
    if (a.date < from || a.date > today || !a.duration_s || !a.distance_m) continue;
    seconds += a.duration_s;
    meters += a.distance_m;
  }
  return meters > 0 ? seconds / (meters / 1000) : null;
}

/** Séance dont l'allure dépend du terrain : estimée d'après les sorties trail. */
export const usesTrailPace = (s: Session) => s.sport !== "bike" && s.target_kind === "hr" && !!s.d_plus_m;

/** Allure (s/km) au milieu de la zone de l'étape ; sans zone : récup pour une récupération, EF sinon. */
function zonePace(step: Step, zones: Zones | null): number | null {
  const zone = step.zone ?? (step.kind === "recovery" ? "récup" : "EF");
  const range = zones?.pace?.[HR_TO_PACE[zone] ?? zone];
  return range ? (range[0] + range[1]) / 2 : null;
}

function stepMeters(step: Step, zones: Zones | null, trail: number | null): number | null {
  if (step.distance_m != null) return step.distance_m;
  if (step.duration_s == null) return 0;
  const pace = trail ?? zonePace(step, zones);
  return pace ? (step.duration_s / pace) * 1000 : null;
}

/** Km de course estimés, arrondis ; null si une étape est incalculable ou s'il n'y a rien à courir. */
export function weekKm(sessions: Session[], zones: Zones | null, trail: number | null): number | null {
  let total = 0;
  for (const s of sessions) {
    if (s.sport === "bike") continue;
    const pace = usesTrailPace(s) ? trail : null;
    for (const item of s.steps) {
      const group = "repeat" in item ? item.steps : [item];
      const times = "repeat" in item ? item.repeat : 1;
      for (const step of group) {
        const meters = stepMeters(step, zones, pace);
        if (meters == null) return null;
        total += meters * times;
      }
    }
  }
  return Math.round(total / 1000) || null;
}

/** D+ prévu pour les séances de course ; null s'il n'y en a pas. */
export function weekDPlus(sessions: Session[]): number | null {
  return sessions.reduce((sum, s) => sum + (s.sport === "bike" ? 0 : (s.d_plus_m ?? 0)), 0) || null;
}

/** « ≈ 36 km · ≈ 450 m D+ » */
export function volumeLine(km: number | null, dPlus: number | null): string {
  return [km && `≈ ${km} km`, dPlus && `≈ ${dPlus} m D+`].filter(Boolean).join(" · ");
}
