<script lang="ts">
  import type { Kpi } from "../../lib/stats/kpis";
  import { fmtNumber } from "../../lib/stats/format";

  let { kpis }: { kpis: Kpi[] } = $props();

  const META: Record<Kpi["key"], { label: string; unit: string; decimals: number }> = {
    hours: { label: "Heures", unit: "h", decimals: 1 },
    run_km: { label: "Km de course", unit: "km", decimals: 1 },
    sessions: { label: "Séances", unit: "", decimals: 0 },
    d_plus: { label: "D+", unit: "m", decimals: 0 },
  };

  // Arrondi d'abord : une variation qui s'arrondit à 0 s'affiche « = 0 % », sans flèche.
  function delta(d: number | null): { text: string; dir: "up" | "down" | "flat" | "none" } {
    if (d === null) return { text: "—", dir: "none" };
    const pct = Math.round(d * 100);
    if (pct === 0) return { text: "= 0 %", dir: "flat" };
    return pct < 0 ? { text: `▼ −${-pct} %`, dir: "down" } : { text: `▲ +${pct} %`, dir: "up" };
  }
</script>

<div class="kpis">
  {#each kpis as k (k.key)}
    {@const m = META[k.key]}
    {@const d = delta(k.delta)}
    <div class="kpi" role="group" aria-label={m.label}>
      <span class="label">{m.label}</span>
      <span class="figure"><strong>{fmtNumber(k.value, m.decimals)}</strong>{#if m.unit}<span class="unit">{m.unit}</span>{/if}</span>
      <span class="delta {d.dir}" title={d.dir === "none" ? "Pas de comparaison possible" : "Par rapport à la période précédente de même durée"}>{d.text}</span>
    </div>
  {/each}
</div>

<style>
  .kpis {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  @media (min-width: 640px) {
    .kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  .kpi {
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px 18px;
    min-width: 0;
  }
  .label { color: var(--muted); font-size: 13px; font-weight: 500; }
  .figure { display: flex; align-items: baseline; gap: 4px; }
  strong {
    font-family: var(--font-display);
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.02em;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .unit { color: var(--muted); font-size: 14px; font-weight: 500; }
  .delta { align-self: flex-start; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; padding: 1px 8px; border-radius: 999px; }
  .delta.up { color: var(--accent-strong); background: var(--accent-soft); }
  .delta.down { color: var(--todo); background: var(--todo-soft); }
  .delta.none,
  .delta.flat { color: var(--muted); background: var(--sunken); }
</style>
