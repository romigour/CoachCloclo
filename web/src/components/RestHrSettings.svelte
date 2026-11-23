<script lang="ts">
  import { onMount } from "svelte";
  import { api, type RestHrView } from "../lib/api";
  import { READONLY } from "../lib/mode";

  // synchro en cours : la saisie serait refusée (409), le bouton attend la fin
  let { syncing = false }: { syncing?: boolean } = $props();

  const SOURCES: Record<string, (v: RestHrView) => string> = {
    nights: (v) => `${v.value} bpm, moyenne de ${v.nights} nuits avec la montre`,
    manual: (v) => `${v.value} bpm, saisie à la main`,
    last_good: (v) => `${v.value} bpm, dernière moyenne des nuits (pas assez de nuits récentes)`,
    garmin: (v) => `${v.value} bpm, valeur Garmin (porte ta montre la nuit pour plus de précision)`,
  };

  let view = $state<RestHrView | null>(null); // reste null si la lecture échoue : la ligne est masquée
  let draft = $state<number | null>(null); // null (champ vide) = calcul automatique
  let error = $state("");
  let note = $state("");
  let busy = $state(false);

  const valid = $derived(draft === null || (Number.isInteger(draft) && draft >= 30 && draft <= 100));

  onMount(async () => {
    if (READONLY) return;
    try {
      view = await api.restHr();
      draft = view.manual;
    } catch {
      view = null;
    }
  });

  async function save() {
    if (!view || busy || syncing || !valid) return;
    busy = true;
    error = "";
    note = "";
    try {
      const r = await api.saveRestHr(draft);
      view = r;
      draft = r.manual;
      if (!r.applied) note = "Enregistrée : elle s'appliquera à la prochaine synchro";
      else if (r.resent > 0) {
        note = `${r.resent} ${r.resent > 1 ? "séances mises" : "séance mise"} à jour sur ta montre`;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Enregistrement impossible";
    } finally {
      busy = false;
    }
  }
</script>

{#if !READONLY && view}
  <div class="set-row">
    <div class="set-label">
      <label for="rest-hr">FC repos</label>
      {#if view.value !== null && view.source}<p>{SOURCES[view.source](view)}</p>{/if}
      {#if view.manual !== null && view.auto_value !== null}
        <p>Calcul automatique : {view.auto_value} bpm ({view.auto_nights} nuits)</p>
      {/if}
      {#if note}<p role="status">{note}</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </div>
    <div class="set-ctl">
      <input
        id="rest-hr"
        type="number"
        min="30"
        max="100"
        step="1"
        placeholder="Auto"
        bind:value={draft}
        disabled={busy}
      />
      <button type="button" onclick={save} disabled={busy || syncing || !valid}>Enregistrer</button>
    </div>
  </div>
{/if}
