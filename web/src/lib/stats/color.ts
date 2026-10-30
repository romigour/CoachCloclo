/** Couleur `#rrggbb` (ou `#rgb`) avec transparence ; toute autre valeur est rendue telle quelle. */
export function withAlpha(color: string, alpha: number): string {
  let hex = color.trim().replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(hex)) hex = [...hex].map((ch) => ch + ch).join("");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return color;
  const n = parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** Infobulles ECharts aux couleurs du thème (fond de carte, bordure, texte). */
export function tooltipTheme(c: { card: string; border: string; text: string }) {
  return { backgroundColor: c.card, borderColor: c.border, textStyle: { color: c.text } };
}
