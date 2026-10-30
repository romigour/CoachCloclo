// Thème clair/sombre réactif : un seul écouteur matchMedia alimente un $state module,
// lu par themeColors() pour que les $derived des composants se recalculent au changement.
import type { Family } from "../api";

const FAMILIES: Family[] = ["run", "trail", "bike", "swim", "strength", "walk", "other"];

export interface ThemeColors {
  text: string;
  muted: string;
  border: string;
  accent: string;
  families: Record<Family, string>;
}

const mq: MediaQueryList | null =
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

let scheme = $state<"light" | "dark">(mq?.matches ? "dark" : "light");

mq?.addEventListener?.("change", (e: MediaQueryListEvent) => {
  scheme = e.matches ? "dark" : "light";
});

// Lit les variables CSS de app.css au moment de l'appel (après le changement de thème).
export function themeColors(): ThemeColors {
  void scheme; // dépendance réactive
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
