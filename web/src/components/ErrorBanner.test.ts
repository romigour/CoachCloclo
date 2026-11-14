import { render, screen } from "@testing-library/svelte";
import { expect, test } from "vitest";
import { ApiError } from "../lib/api";
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
