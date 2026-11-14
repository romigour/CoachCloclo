<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type StorageView } from "../lib/api";

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
      busy = false;
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
      busy = false;
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
      busy = false;
    }
  }
</script>

{#if view}
  <section class="card stack">
    <h2>Stockage des données</h2>
    {#if view.mode === "turso"}
      <p>Tes données sont stockées dans le cloud : <code>{view.turso_url}</code></p>
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <div class="row">
        <button type="button" disabled={busy} onclick={disable}>Revenir au stockage local</button>
        <button type="button" class="danger" disabled={busy} onclick={wipe}>Effacer mes données du cloud</button>
      </div>
    {:else}
      <p>
        Tes données sont stockées sur ce PC. Tu peux les mettre dans une base cloud pour les retrouver sur tous tes PC.
        <a href={GUIDE} target="_blank" rel="noopener noreferrer">Lire le guide</a>
      </p>
      <form
        class="stack"
        onsubmit={(e) => {
          e.preventDefault();
          enable();
        }}
      >
        <label>
          URL de la base
          <input type="text" autocomplete="off" placeholder="libsql://ma-base.turso.io" bind:value={url} required />
        </label>
        <label>
          Jeton d'accès
          <input type="password" autocomplete="off" bind:value={token} required />
        </label>
        {#if error}<p class="error" role="alert">{error}</p>{/if}
        <div class="row">
          <button class="primary" disabled={busy}>
            {busy ? "Transfert en cours…" : "Stocker mes données dans le cloud"}
          </button>
        </div>
      </form>
    {/if}
  </section>
{:else if pcOnly}
  <section class="card stack">
    <h2>Stockage des données</h2>
    <p>Disponible uniquement sur le PC</p>
  </section>
{/if}
