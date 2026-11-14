import { afterEach, describe, expect, it, vi } from "vitest";
import { clearCredentials, loadCredentials, normalizeHost, saveCredentials } from "./credentials";

afterEach(() => {
  vi.restoreAllMocks();
  clearCredentials();
});

describe("normalizeHost", () => {
  it.each(["libsql://Base-Org.turso.io", "https://base-org.turso.io/", " base-org.turso.io "])("%s", (u) => {
    expect(normalizeHost(u)).toBe("base-org.turso.io");
  });
});

describe("credentials", () => {
  it("aller-retour puis effacement", () => {
    saveCredentials({ url: "a.turso.io", token: "t" });
    expect(loadCredentials()).toEqual({ url: "a.turso.io", token: "t" });
    clearCredentials();
    expect(loadCredentials()).toBeNull();
  });

  it("repli en mémoire si localStorage lève", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => saveCredentials({ url: "b.turso.io", token: "u" })).not.toThrow();
    expect(loadCredentials()).toEqual({ url: "b.turso.io", token: "u" });
  });
});
