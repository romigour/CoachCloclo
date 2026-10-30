import { render, screen, within } from "@testing-library/svelte";
import { expect, test } from "vitest";
import KpiRow from "./KpiRow.svelte";

test("delta is rounded before choosing its sign", () => {
  render(KpiRow, {
    kpis: [
      { key: "hours", value: 10, delta: 0.12 },
      { key: "run_km", value: 5, delta: -0.08 },
      { key: "sessions", value: 3, delta: -0.004 },
      { key: "d_plus", value: 0, delta: null },
    ],
  });
  const delta = (label: string) => within(screen.getByRole("group", { name: label }));
  expect(delta("Heures").getByText("▲ +12 %")).toBeInTheDocument();
  expect(delta("Km de course").getByText("▼ −8 %")).toBeInTheDocument();
  expect(delta("Séances").getByText("= 0 %")).toBeInTheDocument();
  expect(delta("D+").getByText("—")).toBeInTheDocument();
});
