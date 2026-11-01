// Enregistrement modulaire d'ECharts (seulement ce qui sert) et lecture des couleurs du thème.
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

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
  MarkAreaComponent,
  MarkLineComponent,
  SVGRenderer,
]);

export { echarts };

// themeColors() vit dans theme.svelte.ts (état réactif) ; ré-exporté ici pour garder un chemin stable.
export { themeColors, type ThemeColors } from "./theme.svelte";
