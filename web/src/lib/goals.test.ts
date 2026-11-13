import { expect, test } from "vitest";
import { goalLabel, nextRace } from "./goals";
import type { Goal } from "./api";

const mk = (extra: Partial<Goal> = {}): Goal => ({
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2027-03-01", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null, ...extra,
});

test("goal label matches the server's goal_label, with a French decimal comma", () => {
  expect(goalLabel(mk())).toBe("Course sur route de 21,1 km");
  expect(goalLabel(mk({ type: "trail", distance_km: 20 }))).toBe("Trail de 20 km");
  expect(goalLabel(mk({ distance_km: 42.195 }))).toBe("Course sur route de 42,195 km");
});

test("the countdown targets the next race of the cycle, not a past one", () => {
  const cycle = { end_date: "2027-03-01" } as never;
  const a = mk({ id: 1, race_date: "2027-02-01", priority: "secondaire" });
  const b = mk({ id: 2, race_date: "2027-03-01" });
  expect(nextRace({ cycle, goals: [a, b] }, "2027-01-10")).toBe(a);
  expect(nextRace({ cycle, goals: [a, b] }, "2027-02-01")).toBe(a);
  expect(nextRace({ cycle, goals: [a, b] }, "2027-02-02")).toBe(b);
  expect(nextRace({ cycle: null, goals: [a] }, "2027-01-10")).toBeNull();
});
