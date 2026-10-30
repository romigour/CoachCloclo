import { expect, test } from "vitest";
import type { Family, StatActivity } from "../api";
import { computeKpis } from "./kpis";

function act(family: Family, o: Partial<StatActivity> = {}): StatActivity {
  return {
    id: 1, garmin_id: 1, date: "2026-01-01", start: null, name: null, family, type_key: family,
    duration_s: 3600, distance_m: 10000, d_plus_m: 100, avg_hr: null, max_hr: null, vo2max: null,
    hr_zones_s: null, race: null, ...o,
  };
}
const by = (ks: ReturnType<typeof computeKpis>, key: string) => ks.find((k) => k.key === key)!;

test("activité sans distance : 1 séance, ses heures, 0 km, pas de NaN", () => {
  const ks = computeKpis([act("run", { distance_m: null, d_plus_m: null })], null);
  expect(by(ks, "sessions").value).toBe(1);
  expect(by(ks, "hours").value).toBe(1);
  expect(by(ks, "run_km").value).toBe(0);
  expect(by(ks, "d_plus").value).toBe(0);
  for (const k of ks) expect(Number.isNaN(k.value)).toBe(false);
});

test("durée null comptée comme 0", () => {
  expect(by(computeKpis([act("run", { duration_s: null })], null), "hours").value).toBe(0);
});

test("période précédente vide : tous les delta à null", () => {
  const ks = computeKpis([act("run")], []);
  expect(ks.map((k) => k.delta)).toEqual([null, null, null, null]);
});

test("previous null : delta null", () => {
  expect(computeKpis([act("run")], null).every((k) => k.delta === null)).toBe(true);
});

test("run_km ignore le vélo, inclut le trail", () => {
  const ks = computeKpis([act("run"), act("trail", { distance_m: 5000 }), act("bike", { distance_m: 80000 })], null);
  expect(by(ks, "run_km").value).toBeCloseTo(15);
  expect(by(ks, "sessions").value).toBe(3);
});

test("delta relatif", () => {
  const ks = computeKpis([act("run"), act("run")], [act("run")]);
  expect(by(ks, "sessions").delta).toBeCloseTo(1);
  expect(by(ks, "hours").delta).toBeCloseTo(1);
});
