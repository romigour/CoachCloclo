import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { loadFixtureDb } from "./testing";
import { activities, events, plan, status, zones } from "./reads";

const expected = JSON.parse(
  readFileSync(resolve(process.cwd(), "src/lib/turso/__fixtures__/expected.json"), "utf8"),
) as Record<string, any>;

describe.each(["active", "between"] as const)("lectures (%s)", (s) => {
  it("plan", async () => {
    expect(await plan(await loadFixtureDb(s))).toEqual(expected[s].plan);
  });
  it("events", async () => {
    expect(await events(await loadFixtureDb(s))).toEqual(expected[s].events);
  });
  it("activities", async () => {
    const db = await loadFixtureDb(s);
    for (const week of Object.keys(expected[s].activities)) {
      expect(await activities(db, Number(week))).toEqual(expected[s].activities[week]);
    }
  });
  it("zones", async () => {
    expect(await zones(await loadFixtureDb(s))).toEqual(expected[s].zones);
  });
  it("status", async () => {
    const { garmin, llm_mode, storage, ...rest } = await status(await loadFixtureDb(s), "2026-11-14");
    expect(garmin).toBe("unavailable");
    expect(llm_mode).toBe("cli");
    expect(storage).toBeNull();
    expect(rest).toEqual(expected[s].status);
  });
});
