import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { loadFixtureDb } from "./testing";
import { activities, events, plan, raceView, status, trailActivities, zones } from "./reads";

// `proximity_label` (blocs et courses rapprochées) n'est calculé que par le serveur : la lecture seule ne l'a pas.
const expected = JSON.parse(
  readFileSync(resolve(process.cwd(), "src/lib/turso/__fixtures__/expected.json"), "utf8"),
  (key, value) => (key === "proximity_label" ? undefined : value),
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
  it("sorties trail", async () => {
    expect(await trailActivities(await loadFixtureDb(s), "2026-03-01")).toEqual(expected[s].trail);
  });
  it("zones", async () => {
    expect(await zones(await loadFixtureDb(s))).toEqual(expected[s].zones);
  });
  it("status", async () => {
    const { llm_mode, storage, ...rest } = await status(await loadFixtureDb(s), "2026-11-14");
    expect(llm_mode).toBe("cli");
    expect(storage).toBeNull();
    expect(rest).toEqual(expected[s].status);
  });
});

it("sorties trail : les plus anciennes sont écartées", async () => {
  expect(await trailActivities(await loadFixtureDb("active"), "2026-03-18")).toEqual([]);
});

it("status : finished_at non chaîne → null sans invalider le reste", async () => {
  const db = await loadFixtureDb("active");
  await db.execute({
    sql: "UPDATE appstate SET value_json = ? WHERE key = 'history'",
    args: ['{"status":"done","imported":1,"error":null,"finished_at":12}'],
  });
  const { history } = await status(db, "2026-11-14");
  expect(history.finished_at).toBeNull();
  expect(history.imported).toBe(1);
  expect(history.status).toBe("done");
});

describe("raceView", () => {
  it("matches the Python view", async () => {
    const db = await loadFixtureDb("active");
    for (const [goalId, view] of Object.entries(expected.active.race)) {
      expect(await raceView(db, Number(goalId))).toEqual(view);
    }
  });

  it("est null sans stratégie, sans copie ou avec une copie illisible", async () => {
    const db = await loadFixtureDb("active");
    expect(await raceView(db, 99)).toBeNull();
    expect(await raceView(await loadFixtureDb("between"), 1)).toBeNull();
    await db.execute("UPDATE racestrategy SET view_json = NULL WHERE goal_id = 1");
    expect(await raceView(db, 1)).toBeNull();
    for (const bad of ["pas du json", "null", "[]", '{"plan":{}}', '{"plan":{},"guide":{}}', '{"plan":1,"guide":{},"settings":{}}']) {
      await db.execute({ sql: "UPDATE racestrategy SET view_json = ? WHERE goal_id = 1", args: [bad] });
      expect(await raceView(db, 1)).toBeNull();
    }
  });
});
