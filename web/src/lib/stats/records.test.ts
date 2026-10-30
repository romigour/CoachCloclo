import { describe, expect, it } from "vitest";
import type { PersonalRecord } from "../api";
import { garminActivityUrl, recordRows } from "./records";

const rec = (kind: PersonalRecord["kind"], value: number, id: number | null = 1, date: string | null = "2025-01-01"): PersonalRecord => ({
  kind, value, garmin_activity_id: id, date,
});

describe("recordRows", () => {
  it("ordre fixe, allure sur la distance nominale", () => {
    const rows = recordRows([rec("longest_run", 32500), rec("10k", 2700), rec("5k", 1234), rec("1mile", 400)]);
    expect(rows.map((r) => r.kind)).toEqual(["1mile", "5k", "10k", "longest_run"]);
    expect(rows[0].paceSKm).toBeCloseTo(400 / 1.609344);
    expect(rows[1]).toMatchObject({ label: "5 km", timeS: 1234, distanceKm: null });
    expect(rows[1].paceSKm).toBeCloseTo(246.8);
  });
  it("plus longue sortie : distance en km, pas de temps ni d'allure", () => {
    const [r] = recordRows([rec("longest_run", 32500)]);
    expect(r).toMatchObject({ label: "Plus longue sortie", timeS: null, paceSKm: null, distanceKm: 32.5 });
  });
  it("semi et marathon", () => {
    const rows = recordRows([rec("marathon", 3 * 3600), rec("half", 5400)]);
    expect(rows.map((r) => r.label)).toEqual(["Semi", "Marathon"]);
    expect(rows[0].paceSKm).toBeCloseTo(5400 / 21.0975);
    expect(rows[1].paceSKm).toBeCloseTo(10800 / 42.195);
  });
  it("lien Garmin seulement si l'activité est connue", () => {
    const [a, b] = recordRows([rec("1k", 200, 42), rec("5k", 1200, null)]);
    expect(a.url).toBe("https://connect.garmin.com/modern/activity/42");
    expect(b.url).toBeNull();
  });
  it("ignore une valeur non positive", () => {
    expect(recordRows([rec("5k", 0)])).toEqual([]);
  });
});

describe("garminActivityUrl", () => {
  it("URL Garmin Connect", () => {
    expect(garminActivityUrl(123)).toBe("https://connect.garmin.com/modern/activity/123");
  });
});
