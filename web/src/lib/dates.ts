/** Dates ISO (AAAA-MM-JJ) calculées en UTC pour éviter tout décalage de fuseau. */

export type Weekday = "lundi" | "mardi" | "mercredi" | "jeudi" | "vendredi" | "samedi" | "dimanche";

export const WEEKDAYS: Weekday[] = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function parse(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(iso: string, n: number): string {
  const d = parse(iso);
  d.setUTCDate(d.getUTCDate() + n);
  return toIso(d);
}

/** Les 7 dates ISO de la semaine, du lundi au dimanche. */
export function weekDays(weekMonday: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(weekMonday, i));
}

export function defaultExportDate(weekMonday: string, suggestedDay: Weekday): string {
  const idx = WEEKDAYS.indexOf(suggestedDay);
  return addDays(weekMonday, idx < 0 ? 0 : idx);
}

/** « jeudi 12 novembre » */
export function formatDay(iso: string): string {
  const d = parse(iso);
  const name = WEEKDAYS[(d.getUTCDay() + 6) % 7];
  return `${name} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** « 12 novembre 2026 » */
export function formatDate(iso: string): string {
  const d = parse(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

const SHORT_DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];

/** « mar. 11/11 » */
export function formatShortDay(iso: string): string {
  const d = parse(iso);
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${SHORT_DAYS[(d.getUTCDay() + 6) % 7]} ${dd}/${mm}`;
}
