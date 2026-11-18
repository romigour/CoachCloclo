/**
 * Avertissement à montrer sur la page suivante : quand un changement d'objectif crée une proposition,
 * la page Objectifs redirige aussitôt vers elle et lui confie son avertissement (bloc, courses rapprochées).
 */
let pending = "";

/** Confie l'avertissement à la prochaine page qui le prendra (rien si vide). */
export function handOffNotice(text: string | null | undefined): void {
  pending = text ?? "";
}

/** Prend l'avertissement confié, une seule fois. */
export function takeNotice(): string {
  const text = pending;
  pending = "";
  return text;
}
