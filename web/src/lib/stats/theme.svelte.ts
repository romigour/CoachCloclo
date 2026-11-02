// Couleurs du thème pour ECharts : themeColors() dépend du thème effectif (choix de
// l'utilisateur ou système) pour que les $derived des composants se recalculent au changement.
import type { Family } from "../api";
import { effectiveScheme } from "../theme.svelte";

const FAMILIES: Family[] = ["run", "trail", "bike", "swim", "strength", "walk", "other"];

export interface ThemeColors {
  text: string;
  surface: string;
  muted: string;
  border: string;
  accent: string;
  font: string;
  /** Rampe d'intensité --z1 … --z5 (du plus léger au plus marqué dans chaque thème). */
  zones: string[];
  families: Record<Family, string>;
}

// Lit les variables CSS de app.css au moment de l'appel (après le changement de thème).
export function themeColors(): ThemeColors {
  void effectiveScheme(); // dépendance réactive
  const css = getComputedStyle(document.documentElement);
  const get = (name: string) => css.getPropertyValue(name).trim();
  const families = {} as Record<Family, string>;
  for (const f of FAMILIES) families[f] = get(`--fam-${f}`);
  return {
    text: get("--text"),
    surface: get("--surface"),
    muted: get("--muted"),
    border: get("--border"),
    accent: get("--accent"),
    font: get("--font-text"),
    zones: [1, 2, 3, 4, 5].map((i) => get(`--z${i}`)),
    families,
  };
}
