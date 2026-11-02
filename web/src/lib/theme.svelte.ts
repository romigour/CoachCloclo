// Thème clair/sombre : choix de l'utilisateur (auto, clair, sombre) mémorisé dans le navigateur.
// `data-theme` sur <html> porte toujours le thème effectif, que app.css lit ; le script inline
// d'index.html le pose avant le premier affichage avec la même règle.

export type ThemeChoice = "auto" | "light" | "dark";
type Scheme = "light" | "dark";

/** Clé `localStorage` du choix ; à garder identique dans index.html. */
const KEY = "coach.theme";

const mq: MediaQueryList | null =
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto";
  }
}

let choice = $state<ThemeChoice>(readChoice());
let system = $state<Scheme>(mq?.matches ? "dark" : "light");

function apply() {
  if (typeof document !== "undefined") document.documentElement.dataset.theme = effectiveScheme();
}

mq?.addEventListener?.("change", (e: MediaQueryListEvent) => {
  system = e.matches ? "dark" : "light";
  apply();
});
apply();

export function themeChoice(): ThemeChoice {
  return choice;
}

/** Thème réellement affiché (réactif) : le choix forcé, sinon celui du système. */
export function effectiveScheme(): Scheme {
  return choice === "auto" ? system : choice;
}

export function setThemeChoice(next: ThemeChoice): void {
  choice = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // stockage indisponible : le choix ne vaut que jusqu'au rechargement
  }
  apply();
}
