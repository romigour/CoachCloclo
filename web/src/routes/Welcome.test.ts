import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Welcome from "./Welcome.svelte";

let setup: Record<string, unknown>;
let calls: { url: string; method: string }[];

const base = {
  claude_cli: false,
  claude_auth: false,
  claude_step: "idle",
  claude_error: null,
  garmin: "auth_required",
  llm_mode: "cli",
};

beforeEach(() => {
  calls = [];
  setup = { ...base };
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    const body = url === "/api/setup/status" ? setup : { status: "started" };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const posted = (url: string) => calls.some((c) => c.url === url && c.method === "POST");

test("propose d'installer Claude quand le CLI est absent", async () => {
  render(Welcome, { onconnected: () => {} });
  expect(await screen.findByText("CoachCloclo utilise ton abonnement Claude")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Installer Claude" }));
  await waitFor(() => expect(posted("/api/setup/claude/install")).toBe(true));
});

test("affiche la progression puis le bouton de connexion", async () => {
  setup = { ...base, claude_step: "installing" };
  vi.useFakeTimers();
  render(Welcome, { onconnected: () => {} });
  await vi.advanceTimersByTimeAsync(100);
  expect(screen.getByText("Installation en cours…")).toBeTruthy();
  setup = { ...base, claude_cli: true, claude_step: "idle" };
  await vi.advanceTimersByTimeAsync(2000);
  expect(screen.getByRole("button", { name: "Se connecter à Claude" })).toBeTruthy();
});

test("affiche l'erreur et Réessayer quand l'installation échoue", async () => {
  setup = { ...base, claude_step: "failed", claude_error: "Réseau coupé" };
  render(Welcome, { onconnected: () => {} });
  expect(await screen.findByText("Réseau coupé")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() => expect(posted("/api/setup/claude/install")).toBe(true));
});

test("lance la connexion et passe à Garmin une fois connecté", async () => {
  setup = { ...base, claude_cli: true };
  vi.useFakeTimers();
  render(Welcome, { onconnected: () => {} });
  await vi.advanceTimersByTimeAsync(100);
  setup = { ...base, claude_cli: true, claude_step: "logging_in" }; // état renvoyé après le lancement
  await fireEvent.click(screen.getByRole("button", { name: "Se connecter à Claude" }));
  await vi.advanceTimersByTimeAsync(100);
  expect(posted("/api/setup/claude/login")).toBe(true);
  expect(screen.getByText(/Connexion en cours/)).toBeTruthy();
  setup = { ...base, claude_cli: true, claude_auth: true };
  await vi.advanceTimersByTimeAsync(2000);
  expect(screen.getByLabelText("E-mail Garmin")).toBeTruthy();
});

test("Passer pour l'instant mène à Garmin et est mémorisé", async () => {
  render(Welcome, { onconnected: () => {} });
  await fireEvent.click(await screen.findByRole("button", { name: "Passer pour l'instant" }));
  expect(await screen.findByLabelText("E-mail Garmin")).toBeTruthy();
  expect(localStorage.getItem("coach.claudeSkipped")).toBe("1");
});

test("saute l'étape Claude en mode clé API", async () => {
  setup = { ...base, llm_mode: "api" };
  render(Welcome, { onconnected: () => {} });
  expect(await screen.findByLabelText("E-mail Garmin")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Installer Claude" })).toBeNull();
});

test("l'étape Claude reste accessible même si elle a déjà été passée", async () => {
  localStorage.setItem("coach.claudeSkipped", "1");
  render(Welcome, { onconnected: () => {} });
  expect(await screen.findByRole("button", { name: "Installer Claude" })).toBeTruthy();
});
