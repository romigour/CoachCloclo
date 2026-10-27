import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError } from "./api";

afterEach(() => vi.unstubAllGlobals());

function stub(status: number, body: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status })));
}

test("string detail becomes the message", async () => {
  stub(401, JSON.stringify({ code: "garmin_login_failed", detail: "Identifiants Garmin refusés" }));
  const err = await api.login("a@b.c", "x").catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("garmin_login_failed");
  expect(err.message).toBe("Identifiants Garmin refusés");
});

test("list detail is flattened into a readable message", async () => {
  stub(422, JSON.stringify({ code: "invalid", detail: [{ loc: ["body", "distance_km"], msg: "Field required" }, { loc: [], msg: "autre" }] }));
  const err = await api.status().catch((e) => e);
  expect(err.code).toBe("invalid");
  expect(err.message).toBe("distance_km : Field required ; autre");
});

test("non-JSON body falls back to a generic error", async () => {
  stub(502, "<html>Bad gateway</html>");
  const err = await api.status().catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("http_502");
  expect(err.status).toBe(502);
  expect(err.message).toBeTruthy();
});
