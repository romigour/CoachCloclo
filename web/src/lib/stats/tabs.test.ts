import { expect, test } from "vitest";
import { TABS, parseTab } from "./tabs";

test("chaque adresse mène à sa sous-page", () => {
  for (const t of TABS) expect(parseTab(t.hash)).toBe(t.key);
  expect(TABS.map((t) => t.label)).toEqual(["Aperçu", "Progression", "Charge", "Intensité", "Records & courses"]);
});

test("adresse inconnue ou incomplète : Aperçu", () => {
  for (const h of ["#/stats", "#/stats/", "#/stats/inconnu", "#/week", ""]) expect(parseTab(h)).toBe("overview");
});
