<script lang="ts">
  import { onMount } from "svelte";
  import { api, type LlmUsageRow, type LlmUsageView } from "../lib/api";

  let view = $state<LlmUsageView | null>(null);
  let failed = $state(false);

  const EUR = new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const WHEN = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const INT = new Intl.NumberFormat("fr-FR");

  function eur(v: number | null): string {
    return v === null ? "—" : `≈ ${EUR.format(v)}`;
  }

  function plural(n: number, word: string): string {
    return `${n} ${word}${n > 1 ? "s" : ""}`;
  }

  function detail(r: LlmUsageRow): string {
    const parts = [
      `${INT.format(r.input_tokens)} tokens en entrée`,
      `${INT.format(r.output_tokens)} en sortie`,
      `${Math.round(r.duration_ms / 1000)} s`,
    ];
    if (r.model) parts.push(r.model);
    return parts.join(" · ");
  }

  onMount(async () => {
    try {
      const got = await api.llmUsage();
      if (!Array.isArray(got?.recent) || !got.month) throw new Error("réponse inattendue");
      view = got;
    } catch {
      failed = true;
    }
  });
</script>

<section class="card stack">
  <h2>Consommation Claude</h2>
  {#if failed}
    <p class="empty">Consommation indisponible pour le moment</p>
  {:else if view}
    {#if view.recent.length === 0}
      <p class="empty">Aucune génération enregistrée pour l'instant</p>
    {:else}
      <p>
        Ce mois-ci : {plural(view.month.generations, "génération")} · {plural(view.month.adjustments, "ajustement")}
        · {eur(view.month.cost_eur)}
      </p>
      {#if view.avg_generation_eur !== null}
        <p>Coût moyen d'une génération de plan : {eur(view.avg_generation_eur)}</p>
      {/if}
      <h3>Dernières actions</h3>
      <ul class="usage-list">
        {#each view.recent as r (r.created_at + r.kind + r.attempts)}
          <li>
            <details>
              <summary>
                <span class="meta">{WHEN.format(new Date(r.created_at))}</span>
                <span>{r.kind === "generation" ? "Génération de plan" : "Ajustement"}</span>
                <span class="cost">{eur(r.cost_eur)}</span>
                {#if r.attempts > 1}<span class="pill">{r.attempts} essais</span>{/if}
                {#if r.status === "failed"}<span class="pill">échec</span>{/if}
              </summary>
              <p class="meta">{detail(r)}</p>
            </details>
          </li>
        {/each}
      </ul>
    {/if}
    <p class="meta">Estimation équivalent API, convertie à ≈ 0,92 €/$. En abonnement, ce n'est pas ce que tu paies.</p>
  {/if}
</section>

<style>
  .usage-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
  .usage-list summary { cursor: pointer; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; }
  .usage-list details p { margin: 4px 0 0; }
  .cost { margin-left: auto; font-variant-numeric: tabular-nums; }
  h3 { margin: 0; font-size: 15px; }
  p { margin: 0; }
</style>
