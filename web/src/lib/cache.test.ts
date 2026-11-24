import { expect, test, vi } from "vitest";
import { clearCache, load, noteWrite, pendingLoads } from "./cache";
import { api } from "./api";

/** Requêtes pilotées à la main : chaque appel reste en attente jusqu'à `reply(i, valeur)` ou `fail(i)`. */
function manual() {
  const calls: { ok: (v: string) => void; ko: (e: unknown) => void }[] = [];
  const fetcher = vi.fn(() => new Promise<string>((ok, ko) => calls.push({ ok, ko })));
  return { fetcher, reply: (i: number, v: string) => calls[i].ok(v), fail: (i: number) => calls[i].ko(new Error("coupé")) };
}
const seed = (key: string, value: string) => load(key, async () => value, () => {});
const tick = () => new Promise((r) => setTimeout(r));

test("valeur en cache appliquée avant la relecture", async () => {
  await seed("plan", "ancien");
  const m = manual();
  const seen: string[] = [];
  const p = load("plan", m.fetcher, (v) => seen.push(v));
  expect(seen).toEqual(["ancien"]); // sans attendre
  m.reply(0, "nouveau");
  await p;
  expect(seen).toEqual(["ancien", "nouveau"]);
});

test("deux lectures simultanées : une requête", async () => {
  const m = manual();
  const a = vi.fn();
  const b = vi.fn();
  const both = Promise.all([load("plan", m.fetcher, a), load("plan", m.fetcher, b)]);
  m.reply(0, "x");
  await both;
  expect(m.fetcher).toHaveBeenCalledTimes(1);
  expect(a.mock.calls).toEqual([["x"]]);
  expect(b.mock.calls).toEqual([["x"]]);
});

test("échec d'une lecture partagée : rejetée pour chacun", async () => {
  const m = manual();
  const all = Promise.allSettled([load("plan", m.fetcher, () => {}), load("plan", m.fetcher, () => {})]);
  m.fail(0);
  expect((await all).map((r) => r.status)).toEqual(["rejected", "rejected"]);
  expect(m.fetcher).toHaveBeenCalledTimes(1);
});

test("une écriture pendant la lecture : ancienne réponse ignorée, relue", async () => {
  const m = manual();
  const apply = vi.fn();
  const p = load("plan", m.fetcher, apply);
  noteWrite();
  m.reply(0, "avant");
  await tick();
  expect(apply).not.toHaveBeenCalled();
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  m.reply(1, "après");
  await p;
  expect(apply.mock.calls).toEqual([["après"]]);
});

test("échec d'une lecture dépassée par une écriture : relue", async () => {
  const m = manual();
  const apply = vi.fn();
  const p = load("plan", m.fetcher, apply);
  noteWrite();
  m.fail(0);
  await tick();
  m.reply(1, "après");
  await p;
  expect(apply.mock.calls).toEqual([["après"]]);
});

test("lecteur arrivé après l'écriture : jamais l'ancienne réponse, la relecture est partagée", async () => {
  const m = manual();
  const before = vi.fn();
  const after = vi.fn();
  const p1 = load("plan", m.fetcher, before);
  noteWrite();
  const p2 = load("plan", m.fetcher, after); // n'attend pas la lecture dépassée
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  m.reply(0, "avant");
  await tick();
  expect(before).not.toHaveBeenCalled();
  m.reply(1, "après");
  await Promise.all([p1, p2]);
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  expect(before.mock.calls).toEqual([["après"]]);
  expect(after.mock.calls).toEqual([["après"]]);
});

test("relecture finie avant l'ancienne : l'ancienne réponse n'écrase rien, sans requête de plus", async () => {
  const m = manual();
  const apply = vi.fn();
  const p1 = load("plan", m.fetcher, apply);
  noteWrite();
  const p2 = load("plan", m.fetcher, apply);
  m.reply(1, "après");
  await p2;
  m.reply(0, "avant");
  await p1;
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  expect(apply.mock.calls.flat()).not.toContain("avant");
});

test("écritures à répétition : nombre de relectures borné", async () => {
  const apply = vi.fn();
  const fetcher = vi.fn(async () => {
    noteWrite();
    return "x";
  });
  await load("plan", fetcher, apply);
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(apply.mock.calls).toEqual([["x"]]);
  // réponse non garantie à jour : affichée mais pas gardée
  const later = vi.fn();
  const m = manual();
  const p = load("plan", m.fetcher, later);
  expect(later).not.toHaveBeenCalled();
  m.reply(0, "y");
  await p;
});

test("clearCache pendant la lecture : rien d'appliqué ni gardé", async () => {
  const m = manual();
  const apply = vi.fn();
  const p = load("plan", m.fetcher, apply);
  clearCache();
  m.reply(0, "ancienne base");
  await expect(p).resolves.toBeUndefined();
  expect(apply).not.toHaveBeenCalled();
  // lecture suivante : ni valeur gardée, ni requête de l'ancienne base partagée
  const p2 = load("plan", m.fetcher, apply);
  expect(apply).not.toHaveBeenCalled();
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  m.reply(1, "nouvelle base");
  await p2;
  expect(apply.mock.calls).toEqual([["nouvelle base"]]);
});

test("clearCache pendant une lecture qui échoue : résolue, et la suivante ne la partage pas", async () => {
  const m = manual();
  const p = load("plan", m.fetcher, () => {});
  clearCache();
  const p2 = load("plan", m.fetcher, () => {});
  expect(m.fetcher).toHaveBeenCalledTimes(2);
  m.fail(0);
  await expect(p).resolves.toBeUndefined();
  m.reply(1, "ok");
  await p2;
});

test("échec : ancienne valeur gardée, erreur remontée", async () => {
  await seed("plan", "ancien");
  const apply = vi.fn();
  await expect(load("plan", () => Promise.reject(new Error("coupé")), apply)).rejects.toThrow("coupé");
  expect(apply.mock.calls).toEqual([["ancien"]]);
  const again = vi.fn();
  await load("plan", async () => "nouveau", again);
  expect(again.mock.calls).toEqual([["ancien"], ["nouveau"]]);
});

test("pendingLoads se résout après la dernière lecture, même en échec", async () => {
  const a = manual();
  const b = manual();
  const p1 = load("plan", a.fetcher, () => {});
  load("stats", b.fetcher, () => {}).catch(() => {});
  const done = vi.fn();
  pendingLoads().then(done);
  a.reply(0, "x");
  await p1;
  await tick();
  expect(done).not.toHaveBeenCalled();
  b.fail(0);
  await tick();
  expect(done).toHaveBeenCalledTimes(1);
  await pendingLoads(); // rien en cours : immédiat
});

test("toute écriture de l'API compte, réussie ou non ; pas les lectures", async () => {
  for (const status of [200, 503, 0]) {
    vi.stubGlobal("fetch", vi.fn(async () => {
      if (status === 0) throw new TypeError("réseau");
      return new Response("{}", { status });
    }));
    const m = manual();
    const p = load("plan", m.fetcher, () => {});
    await api.sync().catch(() => {});
    m.reply(0, "avant");
    await tick();
    expect(m.fetcher).toHaveBeenCalledTimes(2);
    m.reply(1, "après");
    await p;
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  const m = manual();
  const p = load("stats", m.fetcher, () => {});
  await api.version();
  m.reply(0, "x");
  await p;
  expect(m.fetcher).toHaveBeenCalledTimes(1);
  vi.unstubAllGlobals();
});

test("pendingLoads n'attend pas les lectures d'avant clearCache", async () => {
  const m = manual();
  load("plan", m.fetcher, () => {});
  clearCache();
  let done = false;
  pendingLoads().then(() => (done = true));
  await tick();
  expect(done).toBe(true);
});
