<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type LanView } from "../lib/api";

  let view = $state<LanView | null>(null); // reste null sous `coach start` : le bloc est masqué
  let panel = $state<"none" | "enable" | "pin">("none");
  let pin = $state("");
  let confirm = $state("");
  let error = $state("");
  let busy = $state(false);
  let copied = $state("");

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  onMount(async () => {
    try {
      view = await api.lan();
    } catch {
      view = null;
    }
  });

  // Le serveur relance son écoute ~0,5 s après sa réponse : on patiente, puis on relit
  // en réessayant brièvement tant que la connexion est coupée.
  async function reread(): Promise<LanView | null> {
    await sleep(1000);
    for (let i = 0; i < 8; i++) {
      try {
        return await api.lan();
      } catch (e) {
        if (!(e instanceof ApiError && e.code === "network")) throw e;
        await sleep(1000);
      }
    }
    throw new ApiError("network", "Impossible de joindre le serveur CoachCloclo", 0);
  }

  function checkPins(): string | null {
    if (!/^\d{4,12}$/.test(pin)) return "Le PIN doit comporter de 4 à 12 chiffres";
    if (pin !== confirm) return "Les deux PIN ne sont pas identiques";
    return null;
  }

  async function send(enabled: boolean, newPin?: string) {
    busy = true;
    error = "";
    try {
      const sent = await api.setLan(enabled, newPin);
      view = sent;
      panel = "none";
      pin = confirm = "";
      view = (await reread()) ?? sent;
    } catch (e) {
      error = e instanceof Error ? e.message : "Opération impossible";
    } finally {
      busy = false;
    }
  }

  function toggle() {
    if (!view || !view.local || busy) return;
    error = "";
    if (view.enabled) {
      panel = "none";
      send(false);
    } else {
      panel = panel === "enable" ? "none" : "enable";
    }
  }

  function submit(e: Event) {
    e.preventDefault();
    if (!view) return;
    const needPin = panel === "pin" || !view.has_pin;
    if (needPin) {
      const problem = checkPins();
      if (problem) {
        error = problem;
        return;
      }
    }
    send(true, needPin ? pin : undefined);
  }

  function openPin() {
    error = "";
    pin = confirm = "";
    panel = "pin";
  }

  async function copy(address: string) {
    try {
      await navigator.clipboard.writeText(address);
      copied = address;
    } catch {
      copied = "";
    }
  }
</script>

{#if view}
  <section class="card stack">
    <h2>Accès depuis ton téléphone</h2>
    <label class="inline">
      <input
        type="checkbox"
        role="switch"
        checked={view.enabled}
        disabled={!view.local || busy}
        onclick={(e) => {
          e.preventDefault();
          toggle();
        }}
      />
      {view.enabled ? "Activé" : "Désactivé"}
    </label>
    {#if !view.local}
      <p>Modifiable seulement depuis l'ordinateur</p>
    {/if}

    {#if view.local && panel !== "none"}
      <form class="stack" onsubmit={submit}>
        {#if panel === "enable"}
          <p class="warning">Windows va te demander l'autorisation : coche <em>Réseaux privés</em> puis <em>Autoriser</em></p>
        {/if}
        {#if panel === "pin" || !view.has_pin}
          <label>
            PIN (4 à 12 chiffres)
            <input type="password" inputmode="numeric" autocomplete="new-password" bind:value={pin} />
          </label>
          <label>
            Confirmer le PIN
            <input type="password" inputmode="numeric" autocomplete="new-password" bind:value={confirm} />
          </label>
        {/if}
        {#if error}<p class="error" role="alert">{error}</p>{/if}
        <div class="row">
          <button class="primary" disabled={busy}>{panel === "pin" ? "Enregistrer le PIN" : "Activer"}</button>
          <button type="button" onclick={() => ((panel = "none"), (error = ""))}>Annuler</button>
        </div>
      </form>
    {:else if error}
      <p class="error" role="alert">{error}</p>
    {/if}

    {#if view.enabled}
      <ul class="plain">
        {#each view.addresses as address}
          <li>
            <code>{address}</code>
            {#if view.local}<button type="button" onclick={() => copy(address)}>Copier</button>{/if}
            {#if copied === address}<span class="ok">Copié</span>{/if}
          </li>
        {/each}
      </ul>
      {#if view.local && panel === "none"}
        <div class="row"><button type="button" onclick={openPin}>Changer le PIN</button></div>
      {/if}
      <p>Le téléphone n'arrive pas à se connecter ? Vérifie le pare-feu Windows</p>
    {/if}
  </section>
{/if}
