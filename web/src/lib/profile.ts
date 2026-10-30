import type { Step, StepGroup } from "./api";

/** Niveau d'intensité 1 (récup) à 5 (VMA), commun aux zones d'allure et de FC. */
export type Level = 1 | 2 | 3 | 4 | 5;

const ZONE_LEVEL: Record<string, Level> = {
  "récup": 1, Z1: 1,
  EF: 2, Z2: 2,
  marathon: 3, Z3: 3,
  seuil: 4, Z4: 4,
  VMA: 5, Z5: 5,
};

const KIND_LEVEL: Record<Step["kind"], Level> = { warmup: 2, active: 3, recovery: 1, cooldown: 1 };

// une étape en distance n'a pas de durée : on l'estime à 5:30 /km, juste pour la largeur du bloc
const SECONDS_PER_METER = 0.33;

export type Block = { level: Level; seconds: number };

export function stepLevel(step: Step): Level {
  return (step.zone && ZONE_LEVEL[step.zone]) || KIND_LEVEL[step.kind];
}

function seconds(step: Step): number {
  if (step.duration_s != null) return step.duration_s;
  if (step.distance_m != null) return step.distance_m * SECONDS_PER_METER;
  return 0;
}

/** Blocs du profil d'intensité, répétitions dépliées, dans l'ordre de la séance. */
export function profile(steps: (Step | StepGroup)[]): Block[] {
  const flat = steps.flatMap((item) =>
    "repeat" in item ? Array.from({ length: item.repeat }, () => item.steps).flat() : [item],
  );
  return flat.map((s) => ({ level: stepLevel(s), seconds: seconds(s) })).filter((b) => b.seconds > 0);
}

/** Durée totale, ou null si une étape est en distance (durée inconnue). */
export function totalSeconds(steps: (Step | StepGroup)[]): number | null {
  let total = 0;
  for (const item of steps) {
    const group = "repeat" in item ? item.steps : [item];
    const times = "repeat" in item ? item.repeat : 1;
    for (const s of group) {
      if (s.duration_s == null) return null;
      total += s.duration_s * times;
    }
  }
  return total;
}

/** « 1 h 09 », « 45 min » */
export function formatDuration(s: number): string {
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
}

/** Niveau dominant d'une séance (celui qui porte l'effort), pour les pastilles du calendrier. */
export function peakLevel(steps: (Step | StepGroup)[]): Level {
  const blocks = profile(steps);
  return blocks.reduce<Level>((max, b) => (b.level > max ? b.level : max), 1);
}
