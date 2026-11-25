/** Phrases d'interprétation de la page de statistiques ; `null` quand les données ne permettent rien d'affirmer. */
import type { Family, PersonalRecord, StatActivity } from "../api";
import { CATEGORY_LABEL, FAMILY_LABEL } from "../labels";
import type { WeekStats } from "./consistency";
import type { Period } from "./filter";
import { fmtClock, fmtDay, fmtMonth, fmtNumber, fmtPace } from "./format";
import type { Split } from "./intensity";
import { RAMP_ALERT, type FitnessPoint } from "./load";
import type { Prediction } from "./predict";
import { raceRows } from "./races";
import { recordRows } from "./records";
import type { hrAtPace, trailSummary } from "./running";

const percent = (share: number) => Math.round(share * 100);
const signed = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n)} %`;

export function efficiencyText(changePct: number | null): string | null {
  if (changePct === null) return null;
  if (Math.abs(changePct) < 1) return "Ton efficacité est stable sur la période.";
  const n = fmtNumber(Math.abs(changePct), 1);
  return changePct > 0
    ? `Ton efficacité monte de ${n} % : tu cours plus vite pour un même cardio.`
    : `Ton efficacité baisse de ${n} % sur la période.`;
}

export function hrAtPaceText(r: ReturnType<typeof hrAtPace>): string | null {
  if (!r) return null;
  const pace = `Autour de ${fmtPace(r.paceSKm)}`;
  return Math.abs(r.to - r.from) < 2
    ? `${pace}, ta FC moyenne est stable (${r.to} bpm).`
    : `${pace}, ta FC moyenne est passée de ${r.from} à ${r.to} bpm.`;
}

export function vo2Text(values: number[]): string | null {
  if (values.length < 2) return null;
  const first = values[0];
  const last = values[values.length - 1];
  return first === last
    ? `Ta VO2max est stable à ${fmtNumber(last, 1)}.`
    : `Ta VO2max passe de ${fmtNumber(first, 1)} à ${fmtNumber(last, 1)} sur la période.`;
}

export function longestText(list: { month: string; km: number }[]): string | null {
  if (list.length === 0) return null;
  const best = list.reduce((a, b) => (b.km > a.km ? b : a));
  return `Ta plus longue sortie : ${fmtNumber(best.km, 1)} km, en ${fmtMonth(best.month)}.`;
}

export function trailText(t: ReturnType<typeof trailSummary>): string | null {
  return t && t.dPlusPerKm > 0 ? `En trail, tu montes en moyenne ${fmtNumber(t.dPlusPerKm)} m par km.` : null;
}

export function fitnessText(p: FitnessPoint | undefined): string | null {
  if (!p || p.ctl <= 0) return null;
  const ratio = p.tsb / p.ctl;
  if (ratio > 0.1) return "Aujourd'hui : bonne fraîcheur, ta fatigue est sous ta forme.";
  return ratio < -0.3 ? "Aujourd'hui, ta fatigue est élevée." : "Aujourd'hui, ta charge est équilibrée.";
}

export function acwrText(v: number | null): string | null {
  if (v === null) return null;
  const where = v > 1.3 ? "Au-dessus du" : v < 0.8 ? "Sous le" : "Dans le";
  return `${where} repère 0,8-1,3 (un repère, pas une prédiction de blessure).`;
}

export function rampText(v: number | null): string | null {
  if (v === null) return null;
  const alert = percent(v) > percent(RAMP_ALERT) ? ", au-delà du repère de +15 %" : "";
  return `Ta dernière semaine complète : ${signed(percent(v))} par rapport à la moyenne des 4 précédentes${alert}.`;
}

export function volumeText(deltaHours: number | null): string | null {
  if (deltaHours === null) return null;
  const n = percent(deltaHours);
  if (n === 0) return "Ton volume est stable par rapport à la période précédente.";
  return `Tu fais ${Math.abs(n)} % d'heures en ${n > 0 ? "plus" : "moins"} que sur la période précédente.`;
}

export function splitText(s: Split | null): string | null {
  if (!s) return null;
  if (s.easy >= 0.75) return "Proche du 80/20.";
  return s.moderate > 0.2 ? "Beaucoup de zone grise." : "Part d'intensité élevée.";
}

/** `share` : trié par heures décroissantes. */
export function shareText(share: { family: Family; hours: number }[]): string | null {
  const total = share.reduce((s, x) => s + x.hours, 0);
  if (total <= 0) return null;
  return `${FAMILY_LABEL[share[0].family]} : ${percent(share[0].hours / total)} % de ton temps.`;
}

export function regularityText(w: WeekStats): string | null {
  if (w.activeWeeks === 0) return null;
  const s = w.activeWeeks > 1 ? "s" : "";
  return `${w.activeWeeks} semaine${s} active${s} sur ${w.totalWeeks}.`;
}

/** Plus longue distance prédite. */
export function predictionText(list: Prediction[]): string | null {
  const p = list[list.length - 1];
  return p ? `${CATEGORY_LABEL[p.category]} : environ ${fmtClock(p.timeS)} aujourd'hui.` : null;
}

/** Compétition ou record le plus récent de la période. */
export function lastResultText(acts: StatActivity[], records: PersonalRecord[], p: Period): string | null {
  const inPeriod = (d: string | null): d is string => d !== null && d >= p.from && d <= p.to;
  const race = raceRows(acts).find((r) => r.timeS !== null && inPeriod(r.activity.date));
  const record = recordRows(records)
    .filter((r) => r.timeS !== null && inPeriod(r.date))
    .sort((a, b) => b.date!.localeCompare(a.date!))[0];
  if (record && (!race || record.date! > race.activity.date)) {
    return `Dernier record : ${record.label}, ${fmtClock(record.timeS!)} le ${fmtDay(record.date!)}.`;
  }
  if (!race) return null;
  const name = race.activity.race?.name ?? race.activity.name ?? "compétition";
  return `Dernière course : ${name}, ${fmtClock(race.timeS!)} le ${fmtDay(race.activity.date)}.`;
}
