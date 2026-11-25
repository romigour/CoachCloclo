import { expect, test } from "vitest";
import type { PersonalRecord, StatActivity } from "../api";
import {
  acwrText, efficiencyText, fitnessText, hrAtPaceText, lastResultText, longestText, predictionText, rampText,
  regularityText, shareText, splitText, trailText, vo2Text, volumeText,
} from "./insights";

test("efficacité : hausse, baisse, stable sous 1 %", () => {
  expect(efficiencyText(3)).toBe("Ton efficacité monte de 3 % : tu cours plus vite pour un même cardio.");
  expect(efficiencyText(-3)).toBe("Ton efficacité baisse de 3 % sur la période.");
  expect(efficiencyText(0.4)).toBe("Ton efficacité est stable sur la période.");
  expect(efficiencyText(null)).toBeNull();
});

test("FC à allure donnée : écart, stable sous 2 bpm", () => {
  const r = { paceSKm: 330, from: 158, to: 149, count: 9 };
  expect(hrAtPaceText(r)).toBe("Autour de 5:30 /km, ta FC moyenne est passée de 158 à 149 bpm.");
  expect(hrAtPaceText({ ...r, from: 150 })).toBe("Autour de 5:30 /km, ta FC moyenne est stable (149 bpm).");
  expect(hrAtPaceText({ ...r, from: 151 })).toContain("passée de 151 à 149");
  expect(hrAtPaceText(null)).toBeNull();
});

test("VO2max", () => {
  expect(vo2Text([50, 52])).toBe("Ta VO2max passe de 50 à 52 sur la période.");
  expect(vo2Text([52, 52])).toBe("Ta VO2max est stable à 52.");
  expect(vo2Text([52])).toBeNull();
});

test("sortie la plus longue, trail", () => {
  expect(longestText([{ month: "2026-01", km: 18 }, { month: "2026-03", km: 25.4 }])).toBe("Ta plus longue sortie : 25,4 km, en mars 2026.");
  expect(longestText([])).toBeNull();
  expect(trailText({ dPlusM: 900, dPlusPerKm: 42 })).toBe("En trail, tu montes en moyenne 42 m par km.");
  expect(trailText(null)).toBeNull();
});

test("forme : bornes 0,1 et -0,3 incluses dans l'équilibre", () => {
  const f = (ctl: number, atl: number) => ({ date: "2026-11-25", ctl, atl, tsb: ctl - atl });
  expect(fitnessText(f(100, 89))).toBe("Aujourd'hui : bonne fraîcheur, ta fatigue est sous ta forme.");
  expect(fitnessText(f(100, 90))).toBe("Aujourd'hui, ta charge est équilibrée.");
  expect(fitnessText(f(100, 130))).toBe("Aujourd'hui, ta charge est équilibrée.");
  expect(fitnessText(f(100, 131))).toBe("Aujourd'hui, ta fatigue est élevée.");
  expect(fitnessText(f(0, 0))).toBeNull();
  expect(fitnessText(undefined)).toBeNull();
});

test("ACWR", () => {
  const tail = "repère 0,8-1,3 (un repère, pas une prédiction de blessure).";
  expect(acwrText(0.8)).toBe(`Dans le ${tail}`);
  expect(acwrText(1.3)).toBe(`Dans le ${tail}`);
  expect(acwrText(1.31)).toBe(`Au-dessus du ${tail}`);
  expect(acwrText(0.79)).toBe(`Sous le ${tail}`);
  expect(acwrText(null)).toBeNull();
});

test("variation hebdo et volume", () => {
  expect(rampText(0.15)).toBe("Ta dernière semaine complète : +15 % par rapport à la moyenne des 4 précédentes.");
  expect(rampText(0.2)).toContain("au-delà du repère de +15 %");
  expect(rampText(-0.1)).toContain("−10 %");
  expect(rampText(null)).toBeNull();
  expect(volumeText(0.12)).toBe("Tu fais 12 % d'heures en plus que sur la période précédente.");
  expect(volumeText(-0.12)).toBe("Tu fais 12 % d'heures en moins que sur la période précédente.");
  expect(volumeText(0)).toBe("Ton volume est stable par rapport à la période précédente.");
  expect(volumeText(null)).toBeNull();
});

test("intensité", () => {
  expect(splitText({ easy: 0.75, moderate: 0.25, hard: 0 })).toBe("Proche du 80/20.");
  expect(splitText({ easy: 0.7, moderate: 0.21, hard: 0.09 })).toBe("Beaucoup de zone grise.");
  expect(splitText({ easy: 0.7, moderate: 0.2, hard: 0.1 })).toBe("Part d'intensité élevée.");
  expect(splitText(null)).toBeNull();
});

test("répartition et régularité", () => {
  expect(shareText([{ family: "run", hours: 3 }, { family: "bike", hours: 1 }])).toContain("75 %");
  expect(shareText([])).toBeNull();
  expect(regularityText({ activeWeeks: 40, totalWeeks: 52, currentStreak: 5, bestStreak: 9 })).toBe("40 semaines actives sur 52.");
  expect(regularityText({ activeWeeks: 1, totalWeeks: 1, currentStreak: 1, bestStreak: 1 })).toBe("1 semaine active sur 1.");
  expect(regularityText({ activeWeeks: 0, totalWeeks: 52, currentStreak: 0, bestStreak: 0 })).toBeNull();
});

test("prédiction", () => {
  const from = { category: "10k" as const, timeS: 3000, date: "2026-10-01", source: "race" as const };
  expect(predictionText([{ category: "half", timeS: 6619, from }])).toBe("Semi : environ 1:50:19 aujourd'hui.");
  expect(predictionText([])).toBeNull();
});

test("dernier résultat : le plus récent de la période", () => {
  const race = {
    id: 1, garmin_id: 1, date: "2026-05-01", start: null, name: "10 km de Lyon", family: "run", type_key: "running",
    duration_s: 3000, distance_m: 10000, d_plus_m: null, avg_hr: null, max_hr: null, vo2max: null, hr_zones_s: null,
    race: { name: null, official_time_s: 2990, overall_rank: null, overall_total: null, category: null, category_rank: null, category_total: null },
  } as StatActivity;
  const rec: PersonalRecord = { kind: "5k", value: 1311, garmin_activity_id: null, date: "2026-06-01" };
  const p = { from: "2026-01-01", to: "2026-12-31" };
  expect(lastResultText([race], [], p)).toBe("Dernière course : 10 km de Lyon, 49:50 le 1 mai 2026.");
  expect(lastResultText([race], [rec], p)).toBe("Dernier record : 5 km, 21:51 le 1 juin 2026.");
  expect(lastResultText([race], [rec], { from: "2026-01-01", to: "2026-05-31" })).toContain("Dernière course");
  expect(lastResultText([], [rec], { from: "2020-01-01", to: "2020-12-31" })).toBeNull();
});
