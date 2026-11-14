import { beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "../api";

const m = vi.hoisted(() => ({
  creds: null as { url: string; token: string } | null,
  openDb: vi.fn(),
  checkSchema: vi.fn(),
  plan: vi.fn(),
}));

vi.mock("./credentials", () => ({
  loadCredentials: () => m.creds,
  saveCredentials: vi.fn(),
  clearCredentials: vi.fn(),
  normalizeHost: (u: string) => u,
}));
vi.mock("./db", async () => {
  const actual = await vi.importActual<typeof import("./db")>("./db");
  return { ...actual, openDb: m.openDb, checkSchema: m.checkSchema, checkConnection: vi.fn() };
});
vi.mock("./reads", () => ({ plan: m.plan, events: vi.fn(), activities: vi.fn(), zones: vi.fn(), status: m.plan }));
vi.mock("./stats", () => ({ statsActivities: vi.fn(), statsRecords: vi.fn() }));

import * as turso from "./index";

const creds = (n: number) => ({ url: `u${n}`, token: `t${n}` });

beforeEach(async () => {
  vi.clearAllMocks();
  m.creds = null;
  m.openDb.mockImplementation((c) => ({ execute: vi.fn(), tag: c.url }));
  m.checkSchema.mockResolvedValue(undefined);
  m.plan.mockResolvedValue("ok");
  // purge le cache : un échec de schéma le vide
  m.creds = creds(0);
  m.checkSchema.mockRejectedValueOnce(new ApiError("unreachable", "x"));
  await turso.plan().catch(() => {});
  await Promise.resolve();
  vi.clearAllMocks();
  m.openDb.mockImplementation((c) => ({ execute: vi.fn(), tag: c.url }));
  m.checkSchema.mockResolvedValue(undefined);
  m.plan.mockResolvedValue("ok");
});

test("sans identifiants : auth", async () => {
  m.creds = null;
  await expect(turso.plan()).rejects.toMatchObject({ code: "auth", message: "Jeton Turso refusé" });
  expect(m.openDb).not.toHaveBeenCalled();
});

test("cache réutilisé, schéma vérifié une fois", async () => {
  m.creds = creds(1);
  await turso.plan();
  await turso.plan();
  expect(m.openDb).toHaveBeenCalledTimes(1);
  expect(m.checkSchema).toHaveBeenCalledTimes(1);
});

test("identifiants changés : client rouvert et schéma revérifié", async () => {
  m.creds = creds(2);
  await turso.plan();
  m.creds = creds(3);
  await turso.plan();
  expect(m.openDb).toHaveBeenCalledTimes(2);
  expect(m.checkSchema).toHaveBeenCalledTimes(2);
});

test("échec du schéma : erreur traduite puis nouvelle tentative", async () => {
  m.creds = creds(4);
  m.checkSchema.mockRejectedValueOnce(new ApiError("schema_outdated", "vieux"));
  await expect(turso.plan()).rejects.toMatchObject({ code: "schema_outdated" });
  await new Promise((r) => setTimeout(r, 0));
  await expect(turso.plan()).resolves.toBe("ok");
  expect(m.checkSchema).toHaveBeenCalledTimes(2);
});

test.each([
  ["auth", new ApiError("auth", "Jeton Turso refusé")],
  ["unreachable", new ApiError("unreachable", "Base Turso injoignable")],
  ["schema_too_new", new ApiError("schema_too_new", "trop récente")],
  ["schema_outdated", new ApiError("schema_outdated", "vieux")],
])("status() dégradé pour %s", async (code, err) => {
  m.creds = creds(5);
  m.plan.mockRejectedValueOnce(err); // status mocké sur m.plan
  const s = await turso.status();
  expect(s.cycle).toBeNull();
  expect(s.goals).toEqual([]);
  expect(s.garmin).toBe("unavailable");
  expect(s.history).toEqual({ status: "idle", imported: 0, error: null });
  expect(s.storage).toEqual({ code, detail: err.detail });
});

test("status() sans identifiants : dégradé en auth", async () => {
  m.creds = null;
  expect((await turso.status()).storage).toMatchObject({ code: "auth" });
});

test("status() relance les erreurs hors stockage", async () => {
  m.creds = creds(6);
  m.plan.mockRejectedValueOnce(new ApiError("boom", "autre"));
  await expect(turso.status()).rejects.toMatchObject({ code: "boom" });
});

test("erreur inattendue : code unexpected, ni masquée en injoignable ni dégradée par status()", async () => {
  m.creds = creds(9);
  m.plan.mockRejectedValueOnce(new Error("bug"));
  await expect(turso.plan()).rejects.toMatchObject({ code: "unexpected", message: "Erreur inattendue" });
  m.plan.mockRejectedValueOnce(new TypeError("x is undefined"));
  await expect(turso.status()).rejects.toMatchObject({ code: "unexpected" });
});

test("course : l'entrée du cache remplacée puis vidée ne casse pas l'appel en cours", async () => {
  m.creds = creds(7);
  let release!: () => void;
  m.checkSchema.mockImplementationOnce(() => new Promise<void>((r) => (release = r)));
  const first = turso.plan();
  m.creds = creds(8);
  m.checkSchema.mockRejectedValueOnce(new ApiError("unreachable", "x"));
  await expect(turso.plan()).rejects.toMatchObject({ code: "unreachable" });
  await new Promise((r) => setTimeout(r, 0)); // le cache est vidé
  release();
  await expect(first).resolves.toBe("ok");
});
