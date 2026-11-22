import { expect, test } from "vitest";
import { activityCount, importBanner, lastImport, newCount, totalLabel } from "./history";

test("activityCount : singulier pour 0 et 1, pluriel au-delà", () => {
  expect(activityCount(0)).toBe("0 activité");
  expect(activityCount(1)).toBe("1 activité");
  expect(activityCount(777)).toBe("777 activités");
});

test("newCount : singulier pour 0 et 1, pluriel au-delà", () => {
  expect(newCount(0)).toBe("0 nouvelle");
  expect(newCount(1)).toBe("1 nouvelle");
  expect(newCount(3)).toBe("3 nouvelles");
});

test("lastImport : nul sans import terminé, sinon date et nouveautés", () => {
  const base = { status: "done", imported: 0, error: null, total: 777 } as const;
  expect(lastImport({ ...base, finished_at: null })).toBeNull();
  expect(lastImport({ ...base, finished_at: "2026-11-20T10:00:00Z" })).toBe(
    "dernier import le 20 novembre 2026, 0 nouvelle",
  );
});

test("totalLabel : total inconnu (base indisponible) → pas de faux « 0 »", () => {
  expect(totalLabel(null)).toBe("Nombre d'activités indisponible");
  expect(totalLabel(0)).toBe("0 activité");
  expect(totalLabel(777)).toBe("777 activités");
});

test("importBanner : compte les nouvelles, pas un total", () => {
  expect(importBanner(0)).toBe("Import de l'historique en cours… (0 nouvelle)");
  expect(importBanner(42)).toBe("Import de l'historique en cours… (42 nouvelles)");
});
