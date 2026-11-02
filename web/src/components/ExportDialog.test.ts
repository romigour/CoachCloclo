import { render, screen, waitFor, fireEvent } from "@testing-library/svelte";
import { beforeEach, expect, test, vi } from "vitest";
import ExportDialog from "./ExportDialog.svelte";
import type { Session } from "../lib/api";

const session: Session = {
  id: 7, order: 1, type: "seuil", title: "Seuil 3x10", description: "", target_kind: "pace",
  status: "todo", suggested_day: "jeudi", sport: "run", scheduled_date: null, chaining_note: null, steps: [], sync_error: null,
};

const calls: { url: string; method: string; body?: string; headers?: Record<string, string> }[] = [];

function mockApi(routes: Record<string, unknown>) {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string, headers: init?.headers as Record<string, string> });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  }));
}

beforeEach(() => vi.unstubAllGlobals());

test("ExportDialog shows warning but keeps button enabled", async () => {
  mockApi({ "export-check": { warnings: ["Séance dure à moins de 48 h"] } });
  render(ExportDialog, { session, weekMonday: "2026-11-09", today: "2026-11-04" });
  expect(await screen.findByText(/48 h/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Envoyer" })).toBeEnabled();
});

test("ExportDialog offers only the 7 days of the week, suggested day preselected", async () => {
  mockApi({ "export-check": { warnings: [] } });
  render(ExportDialog, { session, weekMonday: "2026-11-09", today: "2026-11-04" });
  const select = screen.getByRole("combobox") as HTMLSelectElement;
  expect(Array.from(select.options).map((o) => o.value)).toEqual([
    "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15",
  ]);
  expect(select.value).toBe("2026-11-12");
  await waitFor(() => expect(calls.some((c) => c.url.includes("date=2026-11-12"))).toBe(true));
});

test("ExportDialog re-checks on change then exports with CSRF header", async () => {
  mockApi({ "export-check": { warnings: [] }, "/export": { warnings: [] } });
  const ondone = vi.fn();
  render(ExportDialog, { session, weekMonday: "2026-11-09", today: "2026-11-04", ondone });
  await fireEvent.change(screen.getByRole("combobox"), { target: { value: "2026-11-14" } });
  await waitFor(() => expect(calls.some((c) => c.url.includes("date=2026-11-14"))).toBe(true));
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  await waitFor(() => expect(ondone).toHaveBeenCalled());
  const post = calls.find((c) => c.method === "POST")!;
  expect(post.url).toBe("/api/sessions/7/export");
  expect(JSON.parse(post.body!)).toEqual({ date: "2026-11-14" });
  expect(post.headers?.["X-Coach"]).toBe("1");
});

test("a missed session preselects the suggested day, not its past scheduled date", () => {
  mockApi({ "export-check": { warnings: [] } });
  render(ExportDialog, { session: { ...session, status: "missed", scheduled_date: "2026-11-10" }, weekMonday: "2026-11-09", today: "2026-11-04" });
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("2026-11-12");
});

test("ExportDialog never offers a day before today", async () => {
  mockApi({ "export-check": { warnings: [] } });
  render(ExportDialog, { session: { ...session, suggested_day: "mardi" }, weekMonday: "2026-11-09", today: "2026-11-12" });
  const select = screen.getByRole("combobox") as HTMLSelectElement;
  expect(Array.from(select.options).map((o) => o.value)).toEqual([
    "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15",
  ]);
  expect(select.value).toBe("2026-11-12");
});

test("ExportDialog on a past week offers no day and disables the action", () => {
  mockApi({ "export-check": { warnings: [] } });
  render(ExportDialog, { session, weekMonday: "2026-11-09", today: "2026-11-20", mode: "move" });
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.getByText(/semaine est passée/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Déplacer" })).toBeDisabled();
});
