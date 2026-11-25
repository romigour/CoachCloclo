/** Sous-pages de Statistiques et leurs adresses. */
export type StatsTab = "overview" | "progress" | "load" | "intensity" | "races";

export const TABS: { key: StatsTab; label: string; hash: string }[] = [
  { key: "overview", label: "Aperçu", hash: "#/stats" },
  { key: "progress", label: "Progression", hash: "#/stats/progress" },
  { key: "load", label: "Charge", hash: "#/stats/load" },
  { key: "intensity", label: "Intensité", hash: "#/stats/intensity" },
  { key: "races", label: "Records & courses", hash: "#/stats/races" },
];

/** Sous-page d'une adresse ; inconnue : l'Aperçu. */
export function parseTab(hash: string): StatsTab {
  return TABS.find((t) => t.hash === hash)?.key ?? "overview";
}
