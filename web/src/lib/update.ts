import { api, ApiError, type UpdateView } from "./api";

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
 * Suit une installation déjà en cours (sondage 1 s) jusqu'à « installing » ou l'échec,
 * puis attend la nouvelle version. En cas d'échec, `onProgress` a reçu l'état avec le message d'erreur.
 */
export async function followInstall(
  current: string,
  onProgress: (v: UpdateView) => void,
): Promise<"restarted" | "stuck" | "failed"> {
  for (;;) {
    await sleep(1000);
    let v: UpdateView | null;
    try {
      v = await api.update();
    } catch {
      // le serveur s'est arrêté pour laisser l'installateur travailler
      onProgress({ current, latest: null, available: true, state: "installing", progress: 100, error: null });
      break;
    }
    if (!v) break;
    onProgress(v);
    if (v.state === "failed") return "failed";
    if (v.state === "installing") break;
  }
  return (await waitForVersion(current)) ? "restarted" : "stuck";
}

/** Lance l'installation (409 « déjà en cours » : on la suit simplement) puis la suit jusqu'au redémarrage. */
export async function installAndWait(
  current: string,
  onProgress: (v: UpdateView) => void,
): Promise<"restarted" | "stuck" | "failed"> {
  try {
    await api.installUpdate();
  } catch (e) {
    if (!(e instanceof ApiError && e.code === "update_running")) throw e;
  }
  return followInstall(current, onProgress);
}
