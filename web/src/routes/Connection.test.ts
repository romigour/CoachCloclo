import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "../lib/api";
import Connection from "./Connection.svelte";

const turso = vi.hoisted(() => ({
  checkConnection: vi.fn(),
  loadCredentials: vi.fn(),
  saveCredentials: vi.fn(),
  clearCredentials: vi.fn(),
  normalizeHost: vi.fn((u: string) => u.replace(/^libsql:\/\//, "")),
}));
vi.mock("../lib/turso", () => turso);

const saved = { url: "libsql://ma-base.turso.io", token: "secret-token-abcd1234" };

beforeEach(() => {
  turso.checkConnection.mockReset().mockResolvedValue(undefined);
  turso.loadCredentials.mockReset().mockReturnValue(null);
  turso.saveCredentials.mockReset();
  turso.clearCredentials.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

async function fill(url: string, token: string) {
  await fireEvent.input(await screen.findByLabelText("URL de la base"), { target: { value: url } });
  await fireEvent.input(screen.getByLabelText("Jeton d'accès"), { target: { value: token } });
}

test("valide puis enregistre les identifiants saisis", async () => {
  const onchanged = vi.fn();
  render(Connection, { onchanged });
  expect(await screen.findByText(/turso db tokens create <base> --read-only/)).toBeTruthy();
  await fill("libsql://x.turso.io", "tok");
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  expect(turso.checkConnection).toHaveBeenCalledWith({ url: "libsql://x.turso.io", token: "tok" });
  expect(turso.saveCredentials).toHaveBeenCalledWith({ url: "libsql://x.turso.io", token: "tok" });
});

test("affiche l'erreur et n'enregistre rien si la validation échoue", async () => {
  turso.checkConnection.mockRejectedValue(new ApiError("auth", "Jeton Turso refusé"));
  const onchanged = vi.fn();
  render(Connection, { onchanged });
  await fill("libsql://x.turso.io", "bad");
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  expect(await screen.findByText("Jeton Turso refusé")).toBeTruthy();
  expect(turso.saveCredentials).not.toHaveBeenCalled();
  expect(onchanged).not.toHaveBeenCalled();
});

test("affiche l'hôte et masque le jeton", async () => {
  turso.loadCredentials.mockReturnValue(saved);
  render(Connection, { onchanged: () => {} });
  expect(await screen.findByText("ma-base.turso.io")).toBeTruthy();
  expect(screen.queryByText(saved.token)).toBeNull();
  expect(screen.getByText("••••1234")).toBeTruthy();
});

test("Modifier puis échec : l'ancienne connexion reste après Annuler", async () => {
  turso.loadCredentials.mockReturnValue(saved);
  turso.checkConnection.mockRejectedValue(new ApiError("unreachable", "Base Turso injoignable"));
  render(Connection, { onchanged: () => {} });
  await fireEvent.click(await screen.findByRole("button", { name: "Modifier" }));
  expect((screen.getByLabelText("URL de la base") as HTMLInputElement).value).toBe(saved.url);
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  expect(await screen.findByText("Base Turso injoignable")).toBeTruthy();
  expect(turso.saveCredentials).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  expect(await screen.findByText("ma-base.turso.io")).toBeTruthy();
});

test("Effacer avec confirmation vide la connexion et le formulaire", async () => {
  turso.loadCredentials.mockReturnValue(saved);
  const confirmFn = vi.fn(() => true);
  vi.stubGlobal("confirm", confirmFn);
  render(Connection, { onchanged: () => {} });
  await fireEvent.click(await screen.findByRole("button", { name: "Effacer" }));
  expect(confirmFn).toHaveBeenCalledWith("Effacer la connexion de ce téléphone ?");
  await waitFor(() => expect(turso.clearCredentials).toHaveBeenCalled());
  expect((await screen.findByLabelText("URL de la base") as HTMLInputElement).value).toBe("");
});
