<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type StorageView } from "../lib/api";
  import { clearCache } from "../lib/cache";

  /** La base utilisée a pu changer (même après un échec) : l'appli relit ses données. */
  let { onswitched }: { onswitched?: () => void } = $props();

  const GUIDE = "https://github.com/romigour/CoachCloclo#stockage-dans-le-cloud-turso";

  let view = $state<StorageView | null>(null); // reste null si la route n'existe pas : le bloc est masqué
  let pcOnly = $state(false); // 403 : réglage réservé au PC
  let url = $state("");
  let token = $state("");
  let error = $state("");
  let busy = $state(false);

  onMount(async () => {
    try {
      view = await api.storage();
    } catch (e) {
      pcOnly = e instanceof ApiError && e.status === 403;
      view = null;
    }
  });

  /** Fin d'une bascule, désactivation ou effacement : aucune donnée de l'ancienne base ne doit réapparaître. */
  function switched() {
    busy = false;
    clearCache();
    onswitched?.();
  }

  // Après un échec, le serveur a pu changer d'état (ex. retour en local avant un effacement raté) : on relit.
  async function fail(e: unknown) {
    error = e instanceof Error ? e.message : "Opération impossible";
    try {
      view = await api.storage();
    } catch {
      // on garde l'affichage actuel
    }
  }

  async function enable() {
    if (busy) return;
    busy = true;
    error = "";
    try {
      try {
        view = await api.enableCloud(url.trim(), token.trim(), false);
      } catch (e) {
        if (!(e instanceof ApiError && e.code === "needs_confirmation")) throw e;
        if (!confirm(e.message)) return;
        view = await api.enableCloud(url.trim(), token.trim(), true);
      }
      token = "";
    } catch (e) {
      await fail(e);
    } finally {
      switched();
    }
  }

  async function disable() {
    busy = true;
    error = "";
    try {
      view = await api.disableCloud();
    } catch (e) {
      await fail(e);
    } finally {
      switched();
    }
  }

  async function wipe() {
    if (!confirm("Les données seront supprimées du cloud pour tous tes PC. Cette action est irréversible.")) return;
    busy = true;
    error = "";
    try {
      view = await api.wipeCloud();
    } catch (e) {
      await fail(e);
    } finally {
      switched();
    }
  }
</script>

{#if view}
  {#if view.mode === "turso"}
    <div class="set-row">
      <div class="set-label">
        <h3>Stockage des données</h3>
        <p>Tes données sont stockées dans le cloud : <code>{view.turso_url}</code></p>
        {#if error}<p class="error" role="alert">{error}</p>{/if}
      </div>
      <div class="set-ctl">
        <button type="button" disabled={busy} onclick={disable}>Revenir au stockage local</button>
      </div>
    </div>
    <div class="set-row danger-zone">
      <div class="set-label">
        <h3>Effacer les données du cloud</h3>
        <p>Supprime définitivement la base cloud.</p>
      </div>
      <div class="set-ctl">
        <button type="button" class="danger" disabled={busy} onclick={wipe}>Effacer mes données du cloud</button>
      </div>
    </div>
  {:else}
    <div class="set-row">
      <div class="set-label">
        <h3>Stockage des données</h3>
        <p>
          Tes données sont stockées sur ce PC. Tu peux les mettre dans une base cloud pour les retrouver sur tous tes PC.
          <a href={GUIDE} target="_blank" rel="noopener noreferrer">Lire le guide</a>
        </p>
      </div>
      <form
        class="set-extra boxed"
        onsubmit={(e) => {
          e.preventDefault();
          enable();
        }}
      >
        <div class="form-grid">
          <label>
            URL de la base
            <input type="text" autocomplete="off" placeholder="libsql://ma-base.turso.io" bind:value={url} required />
          </label>
          <label>
            Jeton d'accès
            <input type="password" autocomplete="off" bind:value={token} required />
          </label>
        </div>
        {#if error}<p class="error" role="alert">{error}</p>{/if}
        <div class="row end">
          <button class="primary" disabled={busy}>
            {busy ? "Transfert en cours…" : "Stocker mes données dans le cloud"}
          </button>
        </div>
      </form>
    </div>
  {/if}
{:else if pcOnly}
  <div class="set-row">
    <div class="set-label">
      <h3>Stockage des données</h3>
      <p>Disponible uniquement sur le PC</p>
    </div>
  </div>
{/if}
