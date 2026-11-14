import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { loadFixtureDb } from "./testing";
import { statsActivities, statsRecords } from "./stats";

const expected = JSON.parse(
  readFileSync(resolve(process.cwd(), "src/lib/turso/__fixtures__/expected.json"), "utf8"),
) as Record<string, any>;

describe.each(["active", "between"] as const)("statistiques (%s)", (s) => {
  it("activités", async () => {
    expect(await statsActivities(await loadFixtureDb(s))).toEqual(expected[s].stats_activities);
  });
  it("records", async () => {
    expect(await statsRecords(await loadFixtureDb(s))).toEqual(expected[s].stats_records);
  });
});

describe("statsActivities, JSON brut hostile", () => {
  it("raw_json invalide : champs extraits à null, la requête réussit", async () => {
    const { activities } = await statsActivities(await loadFixtureDb("active"));
    const a = activities.find((x) => x.garmin_id === 9003)!;
    expect(a).toMatchObject({ start: null, name: null, max_hr: null, vo2max: null, hr_zones_s: null });
  });
  it("maxHR booléen et vO2MaxValue chaîne : null", async () => {
    const { activities } = await statsActivities(await loadFixtureDb("active"));
    const a = activities.find((x) => x.garmin_id === 9004)!;
    expect(a.max_hr).toBeNull();
    expect(a.vo2max).toBeNull();
  });
  it("ne lit jamais raw_json entier", async () => {
    const db = await loadFixtureDb("active");
    const spy = vi.spyOn(db, "execute");
    await statsActivities(db);
    expect(spy).toHaveBeenCalledTimes(1);
    const arg = spy.mock.calls[0][0];
    const sql = typeof arg === "string" ? arg : arg.sql;
    expect(sql).not.toMatch(/SELECT\s+\*/i);
    for (const r of (await spy.mock.results[0].value).rows) expect(r).not.toHaveProperty("raw_json");
  });
});
