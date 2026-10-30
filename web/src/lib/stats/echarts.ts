// Enregistrement modulaire d'ECharts (seulement ce qui sert) et lecture des couleurs du thème.
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { Family } from "../api";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  CalendarComponent,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  SVGRenderer,
]);

export { echarts };

const FAMILIES: Family[] = ["run", "trail", "bike", "swim", "strength", "walk", "other"];

export interface ThemeColors {
  text: string;
  muted: string;
  border: string;
  accent: string;
  families: Record<Family, string>;
}

// Lit les variables CSS de app.css (clair ou sombre selon prefers-color-scheme).
export function themeColors(): ThemeColors {
  const css = getComputedStyle(document.documentElement);
  const get = (name: string) => css.getPropertyValue(name).trim();
  const families = {} as Record<Family, string>;
  for (const f of FAMILIES) families[f] = get(`--fam-${f}`);
  return {
    text: get("--text"),
    muted: get("--muted"),
    border: get("--border"),
    accent: get("--accent"),
    families,
  };
}
