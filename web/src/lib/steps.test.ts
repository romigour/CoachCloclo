import { expect, test } from "vitest";
import type { Zones } from "./api";
import { formatSteps } from "./steps";

test("repeat reads naturally", () => {
  const lines = formatSteps([
    { kind: "warmup", duration_s: 900, zone: "EF" },
    { repeat: 6, steps: [
      { kind: "active", distance_m: 400, zone: "VMA" },
      { kind: "recovery", distance_m: 200, zone: null },
    ] },
    { kind: "cooldown", duration_s: 600, zone: "récup" },
  ]);
  expect(lines).toEqual([
    "Échauffement : 15 min en EF",
    "6 × 400 m en VMA, récup 200 m",
    "Retour au calme : 10 min en récup",
  ]);
});

const ZONES: Zones = {
  pace: { récup: [390, 435], EF: [360, 396], marathon: [318, 336], seuil: [294, 309], VMA: [264, 279] },
  hr: { Z1: [120, 134], Z2: [134, 148], Z3: [148, 162], Z4: [162, 176], Z5: [176, 190] },
  source: [],
};

test("zones d'allure : plage min/km après la zone", () => {
  const lines = formatSteps(
    [
      { kind: "warmup", duration_s: 900, zone: "EF" },
      { repeat: 6, steps: [
        { kind: "active", distance_m: 400, zone: "VMA" },
        { kind: "recovery", distance_m: 200, zone: "récup" },
      ] },
    ],
    ZONES,
  );
  expect(lines).toEqual([
    "Échauffement : 15 min en EF (6:00–6:36/km)",
    "6 × 400 m en VMA (4:24–4:39/km), récup 200 m",
  ]);
});

test("zones FC : plage en bpm", () => {
  expect(formatSteps([{ kind: "active", duration_s: 1200, zone: "Z2" }], ZONES)).toEqual([
    "Effort : 20 min en Z2 (134–148 bpm)",
  ]);
});

test("allure inconnue ou zone inconnue : zone seule", () => {
  const sansAllure = { ...ZONES, pace: null };
  expect(formatSteps([{ kind: "active", duration_s: 600, zone: "seuil" }], sansAllure)).toEqual([
    "Effort : 10 min en seuil",
  ]);
  expect(formatSteps([{ kind: "active", duration_s: 600, zone: "tempo" }], ZONES)).toEqual([
    "Effort : 10 min en tempo",
  ]);
});
