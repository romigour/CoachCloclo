import type { Family, SessionStatus } from "./api";
import type { SportFilter } from "./stats/filter";
import type { DistanceCategory } from "./stats/races";

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

/** Libellés des familles de sport (page Stats). */
export const FAMILY_LABEL: Record<Family, string> = {
  run: "Course sur route",
  trail: "Trail",
  bike: "Vélo",
  swim: "Natation",
  strength: "Renfo / cardio",
  walk: "Marche / rando",
  other: "Autres",
};

/** Libellés du filtre sport : `running` regroupe route et trail. */
export const SPORT_LABEL: Record<SportFilter, string> = {
  all: "Tous",
  running: "Course à pied",
  ...FAMILY_LABEL,
};

/** Catégories de distance des compétitions (progression). */
export const CATEGORY_LABEL: Record<DistanceCategory, string> = {
  "5k": "5 km",
  "10k": "10 km",
  half: "Semi",
  marathon: "Marathon",
};
