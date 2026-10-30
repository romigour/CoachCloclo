/** Records personnels Garmin : ordre d'affichage, distance nominale et allure. */
import type { PersonalRecord } from "../api";

type Kind = PersonalRecord["kind"];

/** Ordre et libellés du tableau ; distance nominale (m) pour l'allure, null pour la plus longue sortie. */
const RECORDS: { kind: Kind; label: string; meters: number | null }[] = [
  { kind: "1k", label: "1 km", meters: 1000 },
  { kind: "1mile", label: "1 mile", meters: 1609.344 },
  { kind: "5k", label: "5 km", meters: 5000 },
  { kind: "10k", label: "10 km", meters: 10000 },
  { kind: "half", label: "Semi", meters: 21097.5 },
  { kind: "marathon", label: "Marathon", meters: 42195 },
  { kind: "longest_run", label: "Plus longue sortie", meters: null },
];

export type RecordRow = {
  kind: Kind;
  label: string;
  /** Temps en secondes (null pour la plus longue sortie). */
  timeS: number | null;
  /** Allure s/km sur la distance nominale. */
  paceSKm: number | null;
  /** Distance en km (plus longue sortie uniquement). */
  distanceKm: number | null;
  date: string | null;
  url: string | null;
};

export function garminActivityUrl(garminId: number): string {
  return `https://connect.garmin.com/modern/activity/${garminId}`;
}

/** Lignes du tableau des records, dans l'ordre 1 km → plus longue sortie ; valeurs non positives ignorées. */
export function recordRows(records: PersonalRecord[]): RecordRow[] {
  const rows: RecordRow[] = [];
  for (const { kind, label, meters } of RECORDS) {
    const r = records.find((x) => x.kind === kind);
    if (!r || !(r.value > 0)) continue;
    const url = r.garmin_activity_id != null ? garminActivityUrl(r.garmin_activity_id) : null;
    rows.push(
      meters === null
        ? { kind, label, timeS: null, paceSKm: null, distanceKm: r.value / 1000, date: r.date, url }
        : { kind, label, timeS: r.value, paceSKm: r.value / (meters / 1000), distanceKm: null, date: r.date, url },
    );
  }
  return rows;
}
