// Zones d'entraînement partagées : chargées par App (au démarrage et après chaque synchro),
// lues par les cartes de séance pour chiffrer les étapes (allure ou bpm).
import { api, type Zones } from "./api";

let zones = $state<Zones | null>(null);
let generation = 0; // change avec la base : une lecture partie avant ne compte plus

export function currentZones(): Zones | null {
  return zones;
}

/** Autre base : oublie les zones, y compris une lecture en vol. */
export function resetZones(): void {
  generation++;
  zones = null;
}

/** Relit les zones ; en cas d'échec on garde les précédentes (les étapes restent lisibles sans). */
export async function loadZones(): Promise<void> {
  const mine = generation;
  try {
    const next = await api.zones();
    if (mine === generation) zones = next;
  } catch {
    // sans zones, les étapes affichent simplement le nom de la zone
  }
}
