<script lang="ts">
  import type { AidPassage, AidStation, Passage } from "../../lib/api";

  let {
    stations,
    passages,
    canReimport = true,
    onchange,
    onreimport,
  }: {
    stations: AidStation[];
    passages: AidPassage[];
    canReimport?: boolean;
    onchange: (stations: AidStation[]) => void;
    onreimport: () => void;
  } = $props();

  const DEFAULT_STOP = { eau: 1, complet: 3 } as const;
  const STATUS_CLASS = { ok: "done", serré: "todo", "hors délai": "missed" } as const;

  const hasTarget = $derived(passages.some((p) => p.target));

  // Les colonnes calculées viennent du dernier plan enregistré : elles ne valent que pour
  // une ligne inchangée depuis (sinon « — » jusqu'à l'enregistrement).
  function passageFor(st: AidStation, i: number): AidPassage | null {
    const p = passages[i];
    return p && JSON.stringify(p.station) === JSON.stringify(st) ? p : null;
  }

  function patch(i: number, change: Partial<AidStation>) {
    onchange(stations.map((s, j) => (j === i ? { ...s, ...change } : s)));
  }
  const setKind = (i: number, kind: AidStation["kind"]) => patch(i, { kind, stop_min: DEFAULT_STOP[kind] });
  const setCutoff = (i: number, v: string) => patch(i, { cutoff: v || null });
  const remove = (i: number) => onchange(stations.filter((_, j) => j !== i));
  function add() {
    const last = stations.at(-1)?.km ?? 0;
    onchange([...stations, { km: Math.round((last + 5) * 10) / 10, name: "Ravitaillement", kind: "complet", cutoff: null, stop_min: DEFAULT_STOP.complet }]);
  }
</script>

{#snippet passageCell(p: Passage | null | undefined)}
  {#if p}
    <td>{p.clock}</td>
    <td>{p.margin_min === null ? "—" : `${p.margin_min > 0 ? "+" : ""}${p.margin_min} min`}</td>
    <td>{#if p.status}<span class="pill {STATUS_CLASS[p.status]}">{p.status}</span>{:else}—{/if}</td>
  {:else}
    <td>—</td><td>—</td><td>—</td>
  {/if}
{/snippet}

<div class="scroll">
  <table aria-label="Ravitaillements">
    <thead>
      <tr>
        <th>Km</th><th>Nom</th><th>Type</th><th>Barrière</th><th>Arrêt (min)</th>
        <th>Heure prévue</th><th>Marge</th><th>Statut</th>
        {#if hasTarget}<th>Heure visée</th><th>Marge visée</th><th>Statut visé</th>{/if}
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each stations as st, i (i)}
        {@const p = passageFor(st, i)}
        <tr>
          <td><input class="num" type="number" step="0.1" min="0" aria-label="Km du ravitaillement {i + 1}" value={st.km} oninput={(e) => patch(i, { km: e.currentTarget.valueAsNumber })} /></td>
          <td><input aria-label="Nom du ravitaillement {i + 1}" value={st.name} oninput={(e) => patch(i, { name: e.currentTarget.value })} /></td>
          <td>
            <select aria-label="Type du ravitaillement {i + 1}" value={st.kind} onchange={(e) => setKind(i, e.currentTarget.value as AidStation["kind"])}>
              <option value="eau">eau</option>
              <option value="complet">complet</option>
            </select>
          </td>
          <td><input type="time" aria-label="Barrière du ravitaillement {i + 1}" value={st.cutoff ?? ""} oninput={(e) => setCutoff(i, e.currentTarget.value)} /></td>
          <td><input class="num" type="number" min="0" aria-label="Arrêt du ravitaillement {i + 1} (min)" value={st.stop_min} oninput={(e) => patch(i, { stop_min: e.currentTarget.valueAsNumber })} /></td>
          {@render passageCell(p?.predicted)}
          {#if hasTarget}{@render passageCell(p?.target)}{/if}
          <td><button type="button" class="danger" aria-label="Supprimer le ravitaillement {i + 1}" onclick={() => remove(i)}>Supprimer</button></td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
{#if stations.length === 0}<p class="meta">Aucun ravitaillement.</p>{/if}
<div class="row">
  <button type="button" onclick={add}>Ajouter un ravitaillement</button>
  <button type="button" onclick={onreimport} disabled={!canReimport}>Réimporter depuis le GPX</button>
</div>

<style>
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--divider); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 13px; }
  .num { width: 5.5em; }
</style>
