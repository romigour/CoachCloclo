import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import AdjustBanner from "./AdjustBanner.svelte";
import type { Cycle } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const pendingCycle: Cycle = {
  id: 1, status: "active", plan_start: "2026-11-02", end_date: "2027-02-07", sessions_per_week: 3,
  available_days: ["mardi", "jeudi", "samedi"], long_run_day: null, include_bike: false,
  plan_accepted: true, needs_generation: false, adjust_due: true,
};

function mock(status = 200, body: unknown = { proposal_id: 12 }) {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const f = vi.fn(async (_url: string, _init?: RequestInit) => {
    await gate;
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", f);
  return { f, release };
}

test("shown when goals changed on an accepted plan", () => {
  render(AdjustBanner, { cycle: pendingCycle });
  expect(screen.getByText("Tes objectifs ont changé")).toBeVisible();
  expect(screen.getByRole("button", { name: "Mettre à jour l'entraînement" })).toBeEnabled();
});

test.each([
  ["nothing pending", { adjust_due: false }],
  ["draft plan", { plan_accepted: false }],
  ["plan to regenerate", { needs_generation: true }],
])("hidden when %s", (_label, over) => {
  render(AdjustBanner, { cycle: { ...pendingCycle, ...over } });
  expect(screen.queryByText("Tes objectifs ont changé")).toBeNull();
});

test("hidden without a cycle", () => {
  render(AdjustBanner, { cycle: null });
  expect(screen.queryByText("Tes objectifs ont changé")).toBeNull();
});

test("the button requests one adjustment and hands over the proposal", async () => {
  const { f, release } = mock();
  const onproposal = vi.fn();
  render(AdjustBanner, { cycle: pendingCycle, onproposal });
  await fireEvent.click(screen.getByRole("button", { name: "Mettre à jour l'entraînement" }));
  expect(screen.getByText("Claude ajuste ton plan… (cela peut prendre une minute)")).toBeVisible();
  expect(screen.getByRole("button", { name: "Mettre à jour l'entraînement" })).toBeDisabled();
  release();
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(12));
  expect(f.mock.calls.map((c) => [c[0], c[1]?.method])).toEqual([["/api/cycle/adjust", "POST"]]);
});

test("an API error is shown and the button stays available", async () => {
  const { release } = mock(502, { error: "llm_unavailable", detail: "Claude indisponible" });
  const onproposal = vi.fn();
  render(AdjustBanner, { cycle: pendingCycle, onproposal });
  await fireEvent.click(screen.getByRole("button", { name: "Mettre à jour l'entraînement" }));
  release();
  await screen.findByText(/Claude indisponible/);
  expect(screen.getByRole("button", { name: "Mettre à jour l'entraînement" })).toBeEnabled();
  expect(onproposal).not.toHaveBeenCalled();
});
