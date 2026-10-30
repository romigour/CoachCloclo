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

/** Durée en minutes → « 1 h 05 » ou « 45 min ». */
export function fmtMinutes(min: number): string {
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
}

export { MONTHS_SHORT };
