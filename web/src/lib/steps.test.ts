import { expect, test } from "vitest";
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
