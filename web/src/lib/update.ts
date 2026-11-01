import { api, type UpdateView } from "./api";

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Attend que le serveur réponde avec une version différente de `from`
 * (les erreurs réseau pendant le redémarrage sont ignorées). `false` après `timeoutMs`.
 */
export async function waitForVersion(
  from: string,
  opts: { intervalMs?: number; timeoutMs?: number; now?: () => number } = {},
): Promise<boolean> {
  const { intervalMs = 2000, timeoutMs = 120_000, now = Date.now } = opts;
  const start = now();
  while (now() - start < timeoutMs) {
    try {
      if ((await api.version()).version !== from) return true;
    } catch {
      // serveur arrêté ou en cours de démarrage : on réessaie
    }
    await sleep(intervalMs);
  }
  return false;
}

/**
 * Lance l'installation, suit la progression (sondage 1 s) jusqu'à « installing » ou l'échec,
 * puis attend la nouvelle version. En cas d'échec, `onProgress` a reçu l'état avec le message d'erreur.
 */
export async function installAndWait(
  current: string,
  onProgress: (v: UpdateView) => void,
): Promise<"restarted" | "stuck" | "failed"> {
  await api.installUpdate();
  for (;;) {
    await sleep(1000);
    let v: UpdateView | null;
    try {
      v = await api.update();
    } catch {
      break; // le serveur s'est arrêté pour laisser l'installateur travailler
    }
    if (!v) break;
    onProgress(v);
    if (v.state === "failed") return "failed";
    if (v.state === "installing") break;
  }
  return (await waitForVersion(current)) ? "restarted" : "stuck";
}
