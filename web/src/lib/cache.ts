// Cache des lectures, en mémoire seulement (vide à chaque lancement) : une page déjà vue s'affiche tout de suite,
// puis se met à jour. Les valeurs gardées ne doivent jamais être modifiées sur place.

/** Relectures au plus quand des écritures se terminent pendant chaque lecture. */
const MAX_REREADS = 3;

/** `writes` : nombre d'écritures déjà terminées au départ de la lecture. */
type Read = { writes: number; order: number; result: Promise<unknown> };
type Kept = { writes: number; order: number; value: unknown };

const kept = new Map<string, Kept>(); // dernière valeur lue par clé
const reads = new Map<string, Read>(); // lecture en vol la plus récente par clé
const pending = new Set<Promise<void>>();
let writes = 0;
let generation = 0; // change à chaque `clearCache` : les lectures d'avant ne comptent plus
let order = 0;

/** Lecture en vol de cette clé si aucune écriture ne s'est terminée depuis son départ, sinon une nouvelle. */
function read<T>(key: string, fetcher: () => Promise<T>): Read {
  const current = reads.get(key);
  if (current && current.writes === writes) return current;
  const started: Read = { writes, order: ++order, result: fetcher() };
  reads.set(key, started);
  const forget = () => {
    if (reads.get(key) === started) reads.delete(key);
  };
  started.result.then(forget, forget);
  return started;
}

async function refresh<T>(key: string, fetcher: () => Promise<T>, apply: (value: T) => void): Promise<void> {
  const born = generation;
  for (let rereads = 0; ; rereads++) {
    const current = read(key, fetcher);
    let value: unknown;
    let failed = false;
    try {
      value = await current.result;
    } catch (e) {
      value = e;
      failed = true;
    }
    if (born !== generation) return; // base ou accès changé pendant la lecture : réponse ignorée
    const newest = kept.get(key);
    const outdated = current.writes !== writes;
    if (outdated && newest?.writes === writes) return apply(newest.value as T); // déjà relu depuis l'écriture
    if (outdated && rereads < MAX_REREADS) continue;
    if (failed) throw value;
    // réponse plus ancienne que la valeur gardée : celle-ci l'emporte
    if (newest && newest.order > current.order) return apply(newest.value as T);
    if (!outdated) kept.set(key, { writes: current.writes, order: current.order, value });
    return apply(value as T);
  }
}

/** Applique la valeur gardée tout de suite (s'il y en a une), relit, puis applique la nouvelle.
 * Une lecture déjà en vol pour la même clé est partagée ; une écriture terminée entre-temps la fait relire.
 * Après `clearCache`, la réponse est ignorée et la promesse résolue. En échec : rejetée, valeur gardée intacte. */
export function load<T>(key: string, fetcher: () => Promise<T>, apply: (value: T) => void): Promise<void> {
  const known = kept.get(key);
  if (known) apply(known.value as T);
  const result = refresh(key, fetcher, apply);
  pending.add(result);
  const forget = () => {
    pending.delete(result);
  };
  result.then(forget, forget);
  return result;
}

/** Une écriture vient de se terminer (réussie ou non) : les lectures parties avant sont dépassées. */
export function noteWrite(): void {
  writes++;
}

/** Oublie tout, y compris les lectures en vol (autre base, autre accès). */
export function clearCache(): void {
  generation++;
  kept.clear();
  reads.clear();
  pending.clear();
}

/** Fin des lectures en cours, y compris celles lancées entre-temps, réussies ou non. */
export async function pendingLoads(): Promise<void> {
  while (pending.size) await Promise.allSettled([...pending]);
}
