import { expect, test } from "vitest";
import type { Family, StatActivity } from "../api";
import { addDays, daysBetween, filterActivities, mondayOf, previousPeriod, resolvePeriod, sportOptions } from "./filter";

function act(date: string, family: Family, id = 1): StatActivity {
  return {
    id, garmin_id: id, date, start: null, name: null, family, type_key: family,
    duration_s: 3600, distance_m: 10000, d_plus_m: null, avg_hr: null, max_hr: null, vo2max: null,
    hr_zones_s: null, race: null,
  };
}

test("12m : du lendemain du même jour un an plus tôt jusqu'à aujourd'hui", () => {
  expect(resolvePeriod({ kind: "12m" }, "2026-10-30", [])).toEqual({ from: "2025-10-31", to: "2026-10-30" });
});

test("12m au 29 février ne déborde pas", () => {
  expect(resolvePeriod({ kind: "12m" }, "2028-02-29", [])).toEqual({ from: "2027-03-01", to: "2028-02-29" });
});

test("previousPeriod : même durée, juste avant", () => {
  const p = resolvePeriod({ kind: "12m" }, "2026-10-30", []);
  expect(previousPeriod(p)).toEqual({ from: "2024-10-31", to: "2025-10-30" });
});

test("year, custom et all", () => {
  expect(resolvePeriod({ kind: "year", year: 2025 }, "2026-10-30", [])).toEqual({ from: "2025-01-01", to: "2025-12-31" });
  expect(resolvePeriod({ kind: "year", year: 2026 }, "2026-10-30", [])).toEqual({ from: "2026-01-01", to: "2026-10-30" });
  expect(resolvePeriod({ kind: "custom", from: "2026-01-05", to: "2026-02-01" }, "2026-10-30", [])).toEqual({
    from: "2026-01-05", to: "2026-02-01",
  });
  const acts = [act("2024-05-02", "run", 2), act("2023-03-04", "bike", 1)];
  expect(resolvePeriod({ kind: "all" }, "2026-10-30", acts)).toEqual({ from: "2023-03-04", to: "2026-10-30" });
  expect(resolvePeriod({ kind: "all" }, "2026-10-30", [])).toEqual({ from: "2026-10-30", to: "2026-10-30" });
});

test("filterActivities : running garde run et trail, exclut bike ; bornes incluses", () => {
  const acts = [act("2026-01-01", "run", 1), act("2026-01-02", "trail", 2), act("2026-01-03", "bike", 3), act("2026-01-04", "run", 4)];
  const p = { from: "2026-01-01", to: "2026-01-03" };
  expect(filterActivities(acts, p, "running").map((a) => a.id)).toEqual([1, 2]);
  expect(filterActivities(acts, p, "all").map((a) => a.id)).toEqual([1, 2, 3]);
  expect(filterActivities(acts, p, "bike").map((a) => a.id)).toEqual([3]);
});

test("sportOptions : all, running, puis familles dans l'ordre", () => {
  const acts = [act("2026-01-01", "swim"), act("2026-01-01", "trail"), act("2026-01-01", "bike")];
  expect(sportOptions(acts)).toEqual(["all", "running", "trail", "bike", "swim"]);
  expect(sportOptions([act("2026-01-01", "swim")])).toEqual(["all", "swim"]);
});

test("utilitaires ISO", () => {
  expect(mondayOf("2026-11-01")).toBe("2026-10-26");
  expect(mondayOf("2026-10-26")).toBe("2026-10-26");
  expect(addDays("2026-02-28", 1)).toBe("2026-03-01");
  expect(daysBetween("2026-10-26", "2026-11-01")).toBe(6);
  expect(daysBetween("2026-03-28", "2026-03-30")).toBe(2);
});
