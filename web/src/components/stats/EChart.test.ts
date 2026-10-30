import { render } from "@testing-library/svelte";
import { vi, it, expect } from "vitest";

const chart = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
const init = vi.fn(() => chart);
vi.mock("../../lib/stats/echarts", () => ({ echarts: { init: (...a: unknown[]) => (init as any)(...a) } }));

import EChart from "./EChart.svelte";

it("un changement d'option rappelle setOption sans ré-init ni dispose", async () => {
  const { rerender, unmount } = render(EChart, { option: { a: 1 }, label: "L" });
  expect(init).toHaveBeenCalledTimes(1);
  expect(chart.setOption).toHaveBeenLastCalledWith({ a: 1 }, true);
  await rerender({ option: { a: 2 }, label: "L" });
  expect(chart.setOption).toHaveBeenCalledTimes(2);
  expect(chart.setOption).toHaveBeenLastCalledWith({ a: 2 }, true);
  expect(init).toHaveBeenCalledTimes(1);
  expect(chart.dispose).not.toHaveBeenCalled();
  unmount();
  expect(chart.dispose).toHaveBeenCalledTimes(1);
});
