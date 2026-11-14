import { afterEach, expect, test, vi } from "vitest";

vi.mock("./mode", () => ({ READONLY: true }));
vi.mock("./turso", () => ({
  plan: vi.fn(async () => ({ cycle: null, goals: [], horizon: [], weeks: [] })),
  status: vi.fn(async () => "status"),
  events: vi.fn(async () => []),
  activities: vi.fn(async () => []),
  zones: vi.fn(async () => null),
  statsActivities: vi.fn(async () => ({ activities: [] })),
  statsRecords: vi.fn(async () => ({ records: [] })),
}));

import { api } from "./api";
import * as turso from "./turso";

afterEach(() => vi.restoreAllMocks());

test("les écritures sont refusées sans appel réseau", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  await expect(api.sync()).rejects.toMatchObject({ code: "readonly", message: "Action indisponible en lecture seule" });
  await expect(api.createEvent({} as never)).rejects.toMatchObject({ code: "readonly" });
  await expect(api.match(1, null)).rejects.toMatchObject({ code: "readonly" });
  await expect(api.saveRace(1, {})).rejects.toMatchObject({ code: "readonly" });
  await expect(api.deleteEvent(1)).rejects.toMatchObject({ code: "readonly" });
  await expect(api.importHistory()).rejects.toMatchObject({ code: "readonly" });
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("les lectures passent par Turso", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  expect(await api.plan()).toEqual({ cycle: null, goals: [], horizon: [], weeks: [] });
  await api.activities(3);
  expect(turso.activities).toHaveBeenCalledWith(3);
  expect(await api.status()).toBe("status");
  await api.events();
  await api.zones();
  await api.statsActivities();
  await api.statsRecords();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("setupStatus, update et lan valent null", async () => {
  expect(await api.setupStatus()).toBeNull();
  expect(await api.update()).toBeNull();
  expect(await api.lan()).toBeNull();
});
