/** Axes communs aux graphiques temporels. */
import { fmtMonthTick } from "./format";
import type { ThemeColors } from "./theme.svelte";

export function timeAxes(c: ThemeColors, yFormat: (v: number) => string) {
  return {
    grid: { top: 12, left: 4, right: 12, bottom: 4, containLabel: true },
    xAxis: {
      type: "time",
      axisLabel: { color: c.muted, formatter: fmtMonthTick, hideOverlap: true },
      axisLine: { lineStyle: { color: c.border } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: c.muted, formatter: yFormat },
      splitLine: { lineStyle: { color: c.border, type: "dashed" } },
    },
  };
}
