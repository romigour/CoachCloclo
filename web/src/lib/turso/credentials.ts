export type Credentials = { url: string; token: string };

const KEY = "coach.turso";
let memory: Credentials | null = null;

/** Même règle que `turso_host` (Python) : sans schéma ni `/` final, en minuscules. */
export function normalizeHost(url: string): string {
  return url
    .trim()
    .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
    .replace(/\/+$/, "")
    .toLowerCase();
}

function valid(v: unknown): v is Credentials {
  return (
    typeof v === "object" && v !== null &&
    typeof (v as Credentials).url === "string" && typeof (v as Credentials).token === "string"
  );
}

export function loadCredentials(): Credentials | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw !== null) {
      const parsed: unknown = JSON.parse(raw);
      if (valid(parsed)) return { url: parsed.url, token: parsed.token };
      return null;
    }
  } catch {
    return memory;
  }
  return memory;
}

export function saveCredentials(c: Credentials): void {
  memory = { url: c.url, token: c.token };
  try {
    localStorage.setItem(KEY, JSON.stringify(memory));
  } catch {
    /* stockage indisponible : la copie mémoire suffit pour la session */
  }
}

export function clearCredentials(): void {
  memory = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* rien à effacer de plus */
  }
}
