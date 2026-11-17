import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import DiagnosticSettings from "./DiagnosticSettings.svelte";

type View = { trace_claude: boolean; trace_garmin: boolean; logs_dir: string; can_open: boolean };

let view: View;
let puts: unknown[];
let putStatus: number;
let opened: number;
let getStatus: number;

beforeEach(() => {
  view = { trace_claude: false, trace_garmin: false, logs_dir: "C:\\Data\\logs", can_open: false };
  puts = [];
  putStatus = 200;
  getStatus = 200;
  opened = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/diagnostics" && init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        puts.push(body);
        if (putStatus !== 200) return new Response(JSON.stringify({ detail: "panne" }), { status: putStatus });
        view = { ...view, ...body };
        return new Response(JSON.stringify(view), { status: 200 });
      }
      if (url === "/api/diagnostics") return new Response(JSON.stringify(view), { status: getStatus });
      if (url === "/api/logs/open" && init?.method === "POST") {
        opened++;
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
});

test("affiche les interrupteurs et enregistre un changement", async () => {
  render(DiagnosticSettings);
  const claude = await screen.findByLabelText("Journal Claude");
  expect(claude).not.toBeChecked();
  await fireEvent.click(claude);
  await waitFor(() => expect(puts).toEqual([{ trace_claude: true }]));
  await waitFor(() => expect(screen.getByLabelText("Journal Claude")).toBeChecked());
  expect(screen.getByText("C:\\Data\\logs")).toBeInTheDocument();
});

test("bouton d'ouverture seulement si can_open", async () => {
  render(DiagnosticSettings);
  await screen.findByLabelText("Journal Garmin");
  expect(screen.queryByText("Ouvrir le dossier des journaux")).toBeNull();
});

test("ouvre le dossier", async () => {
  view.can_open = true;
  render(DiagnosticSettings);
  await fireEvent.click(await screen.findByText("Ouvrir le dossier des journaux"));
  await waitFor(() => expect(opened).toBe(1));
});

test("rétablit la case si l'enregistrement échoue", async () => {
  putStatus = 500;
  render(DiagnosticSettings);
  const garmin = await screen.findByLabelText("Journal Garmin");
  await fireEvent.click(garmin);
  await waitFor(() => expect(puts).toHaveLength(1));
  await waitFor(() => expect(screen.getByLabelText("Journal Garmin")).not.toBeChecked());
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

test("carte masquée si la lecture échoue", async () => {
  getStatus = 500;
  const { container } = render(DiagnosticSettings);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  await Promise.resolve();
  expect(container.querySelector("section")).toBeNull();
});
