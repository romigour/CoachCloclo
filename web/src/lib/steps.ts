import type { Step, StepGroup, Zones } from "./api";
import { fmtClock } from "./stats/format";

const KIND: Record<Step["kind"], string> = {
  warmup: "Échauffement",
  active: "Effort",
  recovery: "Récupération",
  cooldown: "Retour au calme",
};

const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

function length(step: Step): string {
  if (step.distance_m != null) {
    const m = step.distance_m;
    return m >= 1000 && m % 100 === 0 ? `${nf.format(m / 1000)} km` : `${m} m`;
  }
  const s = step.duration_s ?? 0;
  if (s < 60) return `${s} s`;
  const min = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${min} min ${rest} s` : `${min} min`;
}

/** Plage chiffrée de la zone : « 4:24–4:39/km » ou « 134–148 bpm », `null` si inconnue. */
function zoneRange(zone: string, zones: Zones | null | undefined): string | null {
  const pace = zones?.pace?.[zone];
  if (pace) return `${fmtClock(pace[0])}–${fmtClock(pace[1])}/km`;
  const hr = zones?.hr?.[zone];
  return hr ? `${hr[0]}–${hr[1]} bpm` : null;
}

/** Une étape par ligne, lisible : « 6 × 400 m en VMA (4:24–4:39/km), récup 200 m ». */
export function formatSteps(steps: (Step | StepGroup)[], zones?: Zones | null): string[] {
  function withZone(text: string, zone: string | null | undefined): string {
    if (!zone) return text;
    const range = zoneRange(zone, zones);
    return range ? `${text} en ${zone} (${range})` : `${text} en ${zone}`;
  }

  return steps.map((item) => {
    if ("repeat" in item) {
      const parts = item.steps.map((s) =>
        s.kind === "recovery"
          ? withZone(`récup ${length(s)}`, s.zone && s.zone !== "récup" ? s.zone : null)
          : withZone(length(s), s.zone),
      );
      return `${item.repeat} × ${parts.join(", ")}`;
    }
    return `${KIND[item.kind]} : ${withZone(length(item), item.zone)}`;
  });
}
