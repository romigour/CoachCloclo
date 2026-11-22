/** Libellés de l'état de l'historique Garmin (Réglages > Données). */
import type { HistoryState } from "./api";
import { formatDate } from "./dates";

const plural = (n: number, word: string) => `${n} ${word}${n > 1 ? "s" : ""}`;

/** « 0 activité », « 1 activité », « 777 activités » */
export function activityCount(n: number): string {
  return plural(n, "activité");
}

/** « 0 nouvelle », « 1 nouvelle », « 3 nouvelles » */
export function newCount(n: number): string {
  return plural(n, "nouvelle");
}

/** « dernier import le 20 novembre 2026, 0 nouvelle », nul si aucun import n'a abouti. */
export function lastImport(h: HistoryState): string | null {
  if (!h.finished_at) return null;
  return `dernier import le ${formatDate(h.finished_at.slice(0, 10))}, ${newCount(h.imported)}`;
}

/** Total en base pour les Réglages ; jamais un faux « 0 » quand la base est injoignable. */
export function totalLabel(total: number | null): string {
  return total === null ? "Nombre d'activités indisponible" : activityCount(total);
}

/** Bandeau des Statistiques pendant un import : `imported` compte les ajouts, pas un total. */
export function importBanner(imported: number): string {
  return `Import de l'historique en cours… (${newCount(imported)})`;
}
