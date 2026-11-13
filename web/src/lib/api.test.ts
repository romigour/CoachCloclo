import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError } from "./api";

afterEach(() => vi.unstubAllGlobals());

function stub(status: number, body: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status })));
}

test("string detail becomes the message", async () => {
  stub(401, JSON.stringify({ code: "garmin_login_failed", detail: "Identifiants Garmin refusés" }));
  const err = await api.login("a@b.c", "x").catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("garmin_login_failed");
  expect(err.message).toBe("Identifiants Garmin refusés");
});

test("list detail is flattened into a readable message", async () => {
  stub(422, JSON.stringify({ code: "invalid", detail: [{ loc: ["body", "distance_km"], msg: "Field required" }, { loc: [], msg: "autre" }] }));
  const err = await api.status().catch((e) => e);
  expect(err.code).toBe("invalid");
  expect(err.message).toBe("distance_km : Field required ; autre");
});

test("non-JSON body falls back to a generic error", async () => {
  stub(502, "<html>Bad gateway</html>");
  const err = await api.status().catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("http_502");
  expect(err.status).toBe(502);
  expect(err.message).toBeTruthy();
});

test("removeRace envoie DELETE avec l'en-tête X-Coach", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
  vi.stubGlobal("fetch", f);
  await api.removeRace(3);
  const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/races/3");
  expect(init.method).toBe("DELETE");
  expect((init.headers as Record<string, string>)["X-Coach"]).toBe("1");
});

test("les appels du plan portent sur le cycle, sans id d'objectif", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
  vi.stubGlobal("fetch", f);
  await api.generate();
  await api.accept();
  await api.requestAdjustment();
  await api.events();
  await api.createEvent({ kind: "fatigue" });
  await api.updatePlanSettings({ include_bike: true });
  const calls = (f.mock.calls as unknown as [string, RequestInit][]).map(([u, i]) => `${i.method} ${u}`);
  expect(calls).toEqual([
    "POST /api/cycle/generate",
    "POST /api/cycle/accept",
    "POST /api/cycle/adjust",
    "GET /api/cycle/events",
    "POST /api/cycle/events",
    "PATCH /api/cycle",
  ]);
  const patch = (f.mock.calls as unknown as [string, RequestInit][])[5][1];
  expect(JSON.parse(patch.body as string)).toEqual({ include_bike: true });
});

test("createGoal envoie la priorité quand elle est donnée", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
  vi.stubGlobal("fetch", f);
  await api.createGoal({ type: "route", distance_km: 10, d_plus_m: 0, race_date: "2027-03-01", sessions_per_week: 3, priority: "secondaire" });
  const body = (f.mock.calls as unknown as [string, RequestInit][])[0][1].body as FormData;
  expect(body.get("priority")).toBe("secondaire");
});

test("removeGoal envoie DELETE sur l'objectif", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({ proposal_id: null, needs_generation: true }), { status: 200 }));
  vi.stubGlobal("fetch", f);
  expect(await api.removeGoal(3)).toEqual({ proposal_id: null, needs_generation: true });
  const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
  expect(`${init.method} ${url}`).toBe("DELETE /api/goals/3");
});

test("createGoal sans réglages du plan n'envoie pas sessions_per_week", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
  vi.stubGlobal("fetch", f);
  await api.createGoal({ type: "route", distance_km: 10, d_plus_m: 0, race_date: "2027-03-01", priority: "plaisir" });
  const body = (f.mock.calls as unknown as [string, RequestInit][])[0][1].body as FormData;
  expect(body.has("sessions_per_week")).toBe(false);
  expect(body.has("available_days")).toBe(false);
});
