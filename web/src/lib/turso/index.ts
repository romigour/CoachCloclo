// Seule entrée publique de turso/ pour l'appli : les lectures ouvrent le client elles-mêmes.
import { ApiError, type Status } from "../api";
import { todayIso } from "../dates";
import { loadCredentials, type Credentials } from "./credentials";
import { checkSchema, fail, openDb, type Db } from "./db";
import * as r from "./reads";
import * as s from "./stats";

export { checkConnection } from "./db";
export { clearCredentials, loadCredentials, normalizeHost, saveCredentials } from "./credentials";

type Cached = { key: string; db: Db; ready: Promise<void> };
let cached: Cached | null = null;

async function client(): Promise<Db> {
  const c: Credentials | null = loadCredentials();
  if (!c) throw new ApiError("auth", "Jeton Turso refusé");
  const key = `${c.url}\n${c.token}`;
  if (!cached || cached.key !== key) {
    const db = openDb(c);
    const ready = checkSchema(db);
    ready.catch(() => {
      if (cached?.ready === ready) cached = null; // on retentera au prochain appel
    });
    cached = { key, db, ready };
  }
  const current = cached;
  await current.ready;
  return current.db;
}

async function run<T>(fn: (db: Db) => Promise<T>): Promise<T> {
  try {
    return await fn(await client());
  } catch (e) {
    // Les erreurs de transport sont déjà traduites par openDb().execute ; le reste est un défaut du code.
    throw e instanceof ApiError ? e : fail("unexpected");
  }
}

const UNAVAILABLE = new Set(["auth", "unreachable"]);

/** Statut minimal quand la base est indisponible (miroir de `status()` côté Python). */
function minimalStatus(code: string, detail: string): Status {
  return {
    garmin: "unavailable",
    llm_mode: "cli",
    pending_proposal_id: null,
    cycle: null,
    goals: [],
    next_goal: null,
    past_goals: [],
    last_cycle: null,
    has_activities: false,
    history: { status: "idle", imported: 0, error: null },
    storage: { code, detail },
  };
}

export async function status(): Promise<Status> {
  try {
    return await run((db) => r.status(db, todayIso()));
  } catch (e) {
    const err = e as ApiError;
    if (UNAVAILABLE.has(err.code) || err.code.startsWith("schema_")) {
      return minimalStatus(err.code, String(err.detail));
    }
    throw err;
  }
}

export const plan = () => run(r.plan);
export const events = () => run(r.events);
export const activities = (week: number) => run((db) => r.activities(db, week));
export const zones = () => run(r.zones);
export const statsActivities = () => run(s.statsActivities);
export const statsRecords = () => run(s.statsRecords);
