import type { RaceSegment, RaceSettings } from "./api";
import { fmtClock } from "./stats/format";

/** Durée en secondes → « 5 h 12 » (arrondie à la minute), « 48 min » sous l'heure. */
export function fmtDuration(s: number): string {
  const min = Math.round(s / 60);
  const h = Math.floor(min / 60);
  return h > 0 ? `${h} h ${String(min % 60).padStart(2, "0")}` : `${min} min`;
}

/** Cible affichée sur la montre pour un segment : fourchette d'allure ou zone FC. */
export function targetLabel(seg: RaceSegment): string {
  if (seg.target_low == null || seg.target_high == null) return "—";
  if (seg.target_kind === "pace") return `${fmtClock(seg.target_low)}–${fmtClock(seg.target_high)} /km`;
  return `${seg.target_zone ?? ""} · ${seg.target_low}–${seg.target_high} bpm`;
}

export const isDirty = (a: RaceSettings, b: RaceSettings): boolean => JSON.stringify(a) !== JSON.stringify(b);
