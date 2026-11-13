import type { Goal, Plan } from "./api";

/** Libellé court d'un objectif, comme `goal_label` côté serveur : « Trail de 20 km », « Course sur route de 21,1 km ». */
export function goalLabel(g: Pick<Goal, "type" | "distance_km">): string {
  const distance = String(g.distance_km).replace(".", ",");
  return `${g.type === "trail" ? "Trail" : "Course sur route"} de ${distance} km`;
}

/**
 * Prochaine course du cycle (la plus proche à partir d'aujourd'hui) : c'est elle que vise le compte
 * à rebours. Les titres qui décrivent la cible du cycle utilisent `cycleGoal` (la course qui le termine).
 */
export function nextRace(plan: Pick<Plan, "cycle" | "goals">, today: string): Goal | null {
  if (!plan.cycle) return null;
  return plan.goals.find((g) => g.race_date >= today) ?? null;
}
