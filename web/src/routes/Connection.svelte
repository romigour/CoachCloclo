<script lang="ts">
  import { onMount } from "svelte";

  let { onchanged }: { onchanged: () => void } = $props();

  // Chargé à la demande : libsql ne doit pas entrer dans le build de bureau.
  const turso = () => import("../lib/turso");

  type Creds = { url: string; token: string };

  let creds = $state<Creds | null>(null); // connexion enregistrée sur ce téléphone
  let host = $state("");
  let loaded = $state(false);
  let editing = $state(false);
  let url = $state("");
  let token = $state("");
  let error = $state("");
  let busy = $state(false);

  const showForm = $derived(loaded && (!creds || editing));
  const masked = $derived(creds ? "••••" + creds.token.slice(-4) : "");

  onMount(async () => {
    const t = await turso();
    creds = t.loadCredentials();
    host = creds ? t.normalizeHost(creds.url) : "";
    loaded = true;
  });

  function edit() {
    if (!creds) return;
    url = creds.url;
    token = creds.token;
    error = "";
    editing = true;
  }

  function cancel() {
    editing = false;
    error = "";
  }

  // L'ancienne connexion reste en place tant que la nouvelle n'est pas validée.
  async function submit() {
    if (busy) return;
    busy = true;
    error = "";
    try {
      const t = await turso();
      const next = { url: url.trim(), token: token.trim() };
      await t.checkConnection(next);
      t.saveCredentials(next);
      creds = next;
      host = t.normalizeHost(next.url);
      editing = false;
      url = "";
      token = "";
      onchanged();
    } catch (e) {
      error = e instanceof Error ? e.message : "Connexion impossible";
    } finally {
      busy = false;
    }
  }

  async function wipe() {
    if (!confirm("Effacer la connexion de ce téléphone ?")) return;
    const t = await turso();
    t.clearCredentials();
    creds = null;
    host = "";
    editing = false;
    url = "";
    token = "";
    error = "";
  }
</script>

{#if loaded}
  <section class="card stack">
    <h2>Connexion à ta base</h2>
    {#if creds && !editing}
      <p>Base : <code>{host}</code></p>
      <p>Jeton : <code>{masked}</code></p>
      <div class="row">
        <button type="button" onclick={edit}>Modifier</button>
        <button type="button" class="danger" onclick={wipe}>Effacer</button>
      </div>
    {:else if showForm}
      <p>
        Saisis l'URL de ta base Turso et un jeton en lecture seule, créé avec la commande
        <code>turso db tokens create &lt;base&gt; --read-only</code>. Ils restent enregistrés sur ce téléphone.
      </p>
      <form
        class="stack"
        onsubmit={(e) => {
          e.preventDefault();
          submit();
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
          <button class="primary" disabled={busy}>{busy ? "Vérification…" : "Valider"}</button>
          {#if editing}<button type="button" onclick={cancel}>Annuler</button>{/if}
        </div>
      </form>
    {/if}
  </section>
{/if}
