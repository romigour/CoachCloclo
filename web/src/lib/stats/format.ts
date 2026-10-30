/** Mise en forme française des nombres et dates de la page Stats (affichage seulement, aucun calcul). */

const MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** Nombre avec séparateur de milliers ; une décimale sous 100 si `decimals` le permet. */
export function fmtNumber(n: number, decimals = 0): string {
  const digits = Math.abs(n) >= 100 ? 0 : decimals;
  return n.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

/** « 3 nov. 2026 » (ou sans l'année). */
export function fmtDay(iso: string, withYear = true): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS_SHORT[m - 1]}${withYear ? ` ${y}` : ""}`;
}

/** « nov. 2026 » à partir de « 2026-11 ». */
export function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${y}`;
}

/** « janv. 26 » à partir de « 2026-01 » (étiquette d'axe courte). */
export function fmtMonthShort(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
}

/** « janv. 26 » à partir d'un horodatage (axe temporel ECharts, heure locale). */
export function fmtMonthTick(ms: number): string {
  const d = new Date(ms);
  return `${MONTHS_SHORT[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
}

/** Durée en minutes → « 1 h 05 » ou « 45 min ». */
export function fmtMinutes(min: number): string {
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
}

export { MONTHS_SHORT };

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Durée en secondes → « 41:30 » sous l'heure, « 1:23:45 » au-delà (arrondi à la seconde). */
export function fmtClock(seconds: number): string {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}` : `${m}:${pad2(s)}`;
}

/**
 * Saisie « h:mm:ss » (ou « m:ss ») → secondes. Vide → null (champ non renseigné) ;
 * format invalide → NaN ; « 0:00:00 » → 0 (à refuser par l'appelant avec son propre message).
 */
export function parseClock(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})$/.exec(t);
  if (!m) return NaN;
  const [h, min, s] = [Number(m[1] ?? 0), Number(m[2]), Number(m[3])];
  if (s > 59 || (m[1] !== undefined && min > 59)) return NaN;
  return h * 3600 + min * 60 + s;
}

/** Allure en secondes par km → « 4:07 /km ». */
export function fmtPace(secondsPerKm: number): string {
  return `${fmtClock(secondsPerKm)} /km`;
}
