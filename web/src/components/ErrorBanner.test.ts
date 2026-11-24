import { fireEvent, render, screen } from "@testing-library/svelte";
import { expect, test, vi } from "vitest";
import { ApiError } from "../lib/api";
import { load } from "../lib/cache";
import ErrorBanner from "./ErrorBanner.svelte";

test("cloud_unreachable affiche le message du serveur et un lien vers les Réglages", () => {
  render(ErrorBanner, { error: new ApiError("cloud_unreachable", "Base cloud injoignable", 503) });
  expect(screen.getByRole("alert").textContent).toContain("Base cloud injoignable");
  expect((screen.getByRole("link", { name: "Ouvrir les Réglages" }) as HTMLAnchorElement).getAttribute("href")).toBe("#/setup");
});

test("schema_too_new affiche le message et un lien vers les Réglages", () => {
  render(ErrorBanner, { error: new ApiError("schema_too_new", "Mets à jour CoachCloclo sur ce PC", 409) });
  expect(screen.getByRole("alert").textContent).toContain("Mets à jour CoachCloclo sur ce PC");
  expect((screen.getByRole("link", { name: "Ouvrir les Réglages" }) as HTMLAnchorElement).getAttribute("href")).toBe("#/setup");
});

test("saisie du PIN : le cache est vidé avant la relecture", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 })));
  await load("plan", async () => "ancien", () => {});
  const apply = vi.fn();
  const onpin = vi.fn(() => void load("plan", async () => "nouveau", apply));
  render(ErrorBanner, { error: new ApiError("pin_required", "PIN requis", 401), onpin });
  await fireEvent.input(screen.getByLabelText("Code PIN"), { target: { value: "1234" } });
  await fireEvent.click(screen.getByRole("button", { name: "Entrer" }));
  await vi.waitFor(() => expect(apply.mock.calls).toEqual([["nouveau"]]));
  vi.unstubAllGlobals();
});
