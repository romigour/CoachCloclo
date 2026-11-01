import type { StepResult, Verdict } from "./api";
import { fmtClock } from "./stats/format";

export const VERDICT_LABEL: Record<Verdict, string> = {
  in: "dans la cible",
  fast: "trop vite",
  slow: "trop lent",
  hr_high: "FC trop haute",
  hr_low: "FC trop basse",
};

const KIND_LABEL: Record<StepResult["kind"], string> = {
  warmup: "Échauffement",
  active: "Actif",
  recovery: "Récup",
  cooldown: "Retour au calme",
};

/** « 4:07/km » (sans espace, format compact des lignes d'étape). */
export function paceText(secPerKm: number): string {
  return `${fmtClock(secPerKm)}/km`;
}

function plannedVolume(s: StepResult): string {
  if (s.planned_distance_m != null) return `${s.planned_distance_m} m`;
  if (s.planned_duration_s != null) {
    const d = s.planned_duration_s;
    return d >= 60 && d % 60 === 0 ? `${d / 60} min` : `${d} s`;
  }
  return "";
}

/** « 3.2 · Actif 400 m » ; « 1 · Échauffement 15 min » hors répétition. */
export function stepLabel(s: StepResult): string {
  const num = s.iteration != null ? `${s.group}.${s.iteration}` : `${s.group}`;
  return `${num} · ${[KIND_LABEL[s.kind], plannedVolume(s)].filter(Boolean).join(" ")}`;
}

/** « VMA 3:40–3:55/km » ou « Z5 171–190 bpm » ; null sans zone. */
export function targetLabel(s: StepResult, kind: "pace" | "hr"): string | null {
  if (!s.zone) return null;
  if (s.target_low == null || s.target_high == null) return s.zone;
  const range =
    kind === "pace" ? `${fmtClock(s.target_low)}–${paceText(s.target_high)}` : `${s.target_low}–${s.target_high} bpm`;
  return `${s.zone} ${range}`;
}

/** « 412 m · 3:48/km · 172 bpm », éléments manquants omis. */
export function doneLabel(s: StepResult): string {
  return [
    s.distance_m != null ? `${Math.round(s.distance_m)} m` : null,
    s.avg_pace_s_km != null ? paceText(s.avg_pace_s_km) : null,
    s.avg_hr != null ? `${Math.round(s.avg_hr)} bpm` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** « 5/6 fractions dans la cible » ; null hors répétition ou sans étape active. */
export function repeatSummary(steps: StepResult[], group: number): string | null {
  const inGroup = steps.filter((s) => s.group === group);
  if (!inGroup.some((s) => s.iteration != null)) return null;
  const active = inGroup.filter((s) => s.kind === "active");
  if (!active.length) return null;
  return `${active.filter((s) => s.verdict === "in").length}/${active.length} fractions dans la cible`;
}
