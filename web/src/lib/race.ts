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

/**
 * Temps visé saisi → secondes : « 3:45 » = 3 h 45, « 3:45:30 » accepté.
 * Vide → null (pas de temps visé) ; format invalide ou durée nulle → NaN.
 */
export function parseTargetTime(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(t);
  if (!m) return NaN;
  const [h, min, s] = [Number(m[1]), Number(m[2]), Number(m[3] ?? 0)];
  if (min > 59 || s > 59) return NaN;
  const total = h * 3600 + min * 60 + s;
  return total > 0 ? total : NaN;
}

/** Secondes → temps visé affiché : « 3:45 », ou « 3:45:30 » avec des secondes. */
export function fmtTargetTime(seconds: number): string {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = total % 60;
  return s ? `${h}:${m}:${String(s).padStart(2, "0")}` : `${h}:${m}`;
}

const intIn = (v: number, min: number, max: number) => Number.isInteger(v) && v >= min && v <= max;
const numIn = (v: number, min: number, max: number) => Number.isFinite(v) && v >= min && v <= max;

/** Premier réglage invalide (champ vidé, hors bornes) en français, ou null si tout est valide. */
export function settingsError(s: RaceSettings): string | null {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(s.start_time ?? "")) return "Heure de départ manquante : saisis-la au format hh:mm.";
  if (!intIn(s.carbs_g_h, 0, 150)) return "Glucides : saisis un nombre entier de 0 à 150 g/h.";
  if (!intIn(s.water_ml_h, 0, 2000)) return "Eau : saisis un nombre entier de 0 à 2000 ml/h.";
  if (!intIn(s.carry_ml, 1, 5000)) return "Contenance emportée : saisis un nombre entier de 1 à 5000 ml.";
  for (const [i, st] of s.aid_stations.entries()) {
    const name = st.name?.trim() ?? "";
    if (!(Number.isFinite(st.km) && st.km > 0) || !name || name.length > 60 || !numIn(st.stop_min, 0, 120))
      return `Ravitaillement ${i + 1} : km (positif), nom (60 caractères au plus) et arrêt (0 à 120 min) sont requis.`;
  }
  return null;
}
