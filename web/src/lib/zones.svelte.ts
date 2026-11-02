// Zones d'entraînement partagées : chargées par App (au démarrage et après chaque synchro),
// lues par les cartes de séance pour chiffrer les étapes (allure ou bpm).
import { api, type Zones } from "./api";

let zones = $state<Zones | null>(null);

export function currentZones(): Zones | null {
  return zones;
}

/** Relit les zones ; en cas d'échec on garde les précédentes (les étapes restent lisibles sans). */
export async function loadZones(): Promise<void> {
  try {
    zones = await api.zones();
  } catch {
    // sans zones, les étapes affichent simplement le nom de la zone
  }
}
