import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import { checkSchema, toApiError } from "./db";
import { loadFixtureDb } from "./testing";

async function code(p: Promise<unknown>): Promise<string | undefined> {
  try {
    await p;
  } catch (e) {
    return e instanceof ApiError ? e.code : "other";
  }
  return undefined;
}

describe("checkSchema", () => {
  it("passe sur active.sql et between.sql", async () => {
    await expect(checkSchema(await loadFixtureDb("active"))).resolves.toBeUndefined();
    await expect(checkSchema(await loadFixtureDb("between"))).resolves.toBeUndefined();
  });

  it("schema_too_new si v > 1", async () => {
    const db = await loadFixtureDb("active");
    await db.execute(`UPDATE appstate SET value_json='{"v":2}' WHERE key='schema_version'`);
    expect(await code(checkSchema(db))).toBe("schema_too_new");
  });

  it("schema_outdated si version absente", async () => {
    const db = await loadFixtureDb("active");
    await db.execute(`DELETE FROM appstate WHERE key='schema_version'`);
    expect(await code(checkSchema(db))).toBe("schema_outdated");
  });

  it("schema_outdated si colonne manquante", async () => {
    const db = await loadFixtureDb("active");
    await db.execute("ALTER TABLE goal DROP COLUMN target_source");
    expect(await code(checkSchema(db))).toBe("schema_outdated");
  });
});

describe("toApiError", () => {
  it("traduit les erreurs", () => {
    expect(toApiError(new Error("SQLITE_ERROR: no such column: x")).code).toBe("schema_outdated");
    expect(toApiError(new Error("no such table: y")).code).toBe("schema_outdated");
    expect(toApiError(new TypeError("fetch failed")).code).toBe("unreachable");
    expect(toApiError(Object.assign(new Error("boom"), { status: 401 })).code).toBe("auth");
    expect(toApiError(Object.assign(new Error("boom"), { cause: { status: 403 } })).code).toBe("auth");
    expect(toApiError(new Error("whatever")).code).toBe("unreachable");
  });

  it("garde une ApiError telle quelle", () => {
    const e = new ApiError("auth", "x");
    expect(toApiError(e)).toBe(e);
  });
});
