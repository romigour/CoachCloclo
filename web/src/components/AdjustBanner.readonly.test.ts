import { render, screen } from "@testing-library/svelte";
import { expect, test, vi } from "vitest";
import AdjustBanner from "./AdjustBanner.svelte";
import type { Cycle } from "../lib/api";

vi.mock("../lib/mode", () => ({ READONLY: true }));

const pendingCycle: Cycle = {
  id: 1, status: "active", plan_start: "2026-11-02", end_date: "2027-02-07", sessions_per_week: 3,
  available_days: ["mardi", "jeudi", "samedi"], long_run_day: null, include_bike: false,
  plan_accepted: true, needs_generation: false, adjust_due: true,
};

test("read-only mode tells to update from the computer, without a button", () => {
  render(AdjustBanner, { cycle: pendingCycle });
  expect(screen.getByText("Tes objectifs ont changé")).toBeVisible();
  expect(screen.getByText("À faire depuis l'ordinateur")).toBeVisible();
  expect(screen.queryByRole("button")).toBeNull();
});
