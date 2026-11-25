import { expect, test } from "vitest";
import type { Session, StatActivity, Step, StepGroup, Zones } from "./api";
import { trailPace, volumeLine, weekDPlus, weekKm } from "./weekVolume";

const zones: Zones = {
  pace: { récup: [360, 400], EF: [340, 380], marathon: [300, 320], seuil: [270, 290], VMA: [240, 260] },
  hr: {},
  source: [],
};
const NO_ZONES: Zones = { pace: null, hr: {}, source: [] };

const session = (steps: (Step | StepGroup)[], over: Partial<Session> = {}): Session => ({
  id: 1, order: 1, type: "EF", title: "", description: "", target_kind: "pace", status: "todo", suggested_day: "lundi",
  sport: "run", scheduled_date: null, chaining_note: null, sync_error: null, steps, ...over,
});
const timed = (duration_s: number, zone: string | null, kind: Step["kind"] = "active") =>
  session([{ kind, duration_s, zone }]);
const hilly = (over: Partial<Session> = {}) =>
  session([{ kind: "active", duration_s: 3600, zone: "Z2" }], { target_kind: "hr", d_plus_m: 600, ...over });

test("distance exacte, répétitions dépliées", () => {
  const s = session([{ repeat: 5, steps: [{ kind: "active", distance_m: 1000, zone: "seuil" }] }]);
  expect(weekKm([s], null, null)).toBe(5);
});

test.each([
  [3600, "EF"], [3800, "Z1"], [3600, "Z2"], [3100, "Z3"], [2800, "Z4"], [2500, "Z5"],
])("%i s en %s : 10 km", (d, zone) => {
  expect(weekKm([timed(d, zone)], zones, null)).toBe(10);
});

test("sans zone : récup pour une récupération, EF sinon", () => {
  expect(weekKm([timed(3800, null, "recovery")], zones, null)).toBe(10);
  expect(weekKm([timed(3600, null, "warmup")], zones, null)).toBe(10);
});

test("séance en FC avec D+ : allure trail, sinon allure de zone", () => {
  expect(weekKm([hilly()], zones, 450)).toBe(8);
  expect(weekKm([hilly()], zones, null)).toBe(10);
  expect(weekKm([hilly({ d_plus_m: null })], zones, 450)).toBe(10);
});

test("l'allure trail ne touche pas une séance en allure", () => {
  const s = hilly({ target_kind: "pace", steps: [{ kind: "active", duration_s: 3600, zone: "EF" }] });
  expect(weekKm([s], zones, 450)).toBe(10);
});

test("sans zones d'allure : inconnu si une étape en dépend", () => {
  for (const z of [null, NO_ZONES]) {
    expect(weekKm([session([{ kind: "active", distance_m: 5000 }]), timed(3600, "EF")], z, null)).toBeNull();
    expect(weekKm([hilly()], z, 450)).toBe(8);
  }
});

test("arrondi du total, pas de chaque séance", () => {
  const s = session([{ kind: "active", distance_m: 5400 }]);
  expect(weekKm([s, s], zones, null)).toBe(11);
});

test("le vélo ne compte pas, une semaine de vélo n'affiche rien", () => {
  const bike = hilly({ sport: "bike", d_plus_m: 300 });
  expect(weekKm([bike], zones, 450)).toBeNull();
  expect(weekDPlus([bike])).toBeNull();
  expect(weekKm([bike, timed(3600, "EF")], zones, null)).toBe(10);
});

test("D+ de la semaine", () => {
  expect(weekDPlus([hilly(), hilly({ d_plus_m: null }), hilly({ d_plus_m: 150 })])).toBe(750);
  expect(weekDPlus([hilly({ d_plus_m: null }), hilly({ d_plus_m: 0 })])).toBeNull();
});

const TODAY = "2026-11-25";
const run = (over: Partial<StatActivity> = {}): StatActivity => ({
  id: 1, garmin_id: 1, date: "2026-11-20", start: null, name: null, family: "trail", type_key: "trail_running",
  duration_s: 3600, distance_m: 8000, d_plus_m: 300, avg_hr: null, max_hr: null, vo2max: null, hr_zones_s: null,
  race: null, ...over,
});

test("allure trail : temps total sur distance totale", () => {
  expect(trailPace([run(), run({ duration_s: 5400, distance_m: 12000 })], TODAY)).toBe(450);
});

test("allure trail : sorties inutilisables ou anciennes ignorées", () => {
  expect(trailPace([], TODAY)).toBeNull();
  const unusable = [
    run({ family: "run" }), run({ distance_m: null }), run({ distance_m: 0 }), run({ duration_s: null }),
    run({ duration_s: 0 }), run({ date: "2026-09-29" }), run({ date: "2026-11-26" }),
  ];
  expect(trailPace(unusable, TODAY)).toBeNull();
  expect(trailPace([run({ date: "2026-09-30" })], TODAY)).toBe(450);
});

test("ligne affichée", () => {
  expect(volumeLine(36, 450)).toBe("≈ 36 km · ≈ 450 m D+");
  expect(volumeLine(36, null)).toBe("≈ 36 km");
  expect(volumeLine(null, 450)).toBe("≈ 450 m D+");
  expect(volumeLine(null, null)).toBe("");
});
