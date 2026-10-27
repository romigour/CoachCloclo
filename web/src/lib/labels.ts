import type { SessionStatus } from "./api";

export const STATUS_LABEL: Record<SessionStatus, string> = {
  todo: "À exporter",
  exported: "Dans Garmin",
  done: "Réalisée",
  missed: "Manquée",
  sync_error: "Erreur de synchro",
};

export const TYPE_LABEL: Record<string, string> = {
  EF: "Endurance fondamentale",
  seuil: "Seuil",
  VMA: "VMA",
  "côtes": "Côtes",
  sortie_longue: "Sortie longue",
  "récup": "Récupération",
};
