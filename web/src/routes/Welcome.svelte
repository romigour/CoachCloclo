<script lang="ts">
  import { onMount } from "svelte";
  import { api, claudeSkipped, skipClaude, type SetupStatus } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import GarminLogin from "../components/GarminLogin.svelte";

  /** Appelé quand Garmin est connecté : l'App synchronise puis ouvre la page d'accueil. */
  let { onconnected }: { onconnected?: () => void | Promise<void> } = $props();

  let setup = $state<SetupStatus | null>(null);
  let skipped = $state(claudeSkipped());
  let error = $state<unknown>(null);
  let loaded = $state(false);

  async function load() {
    try {
      setup = await api.setupStatus();
      error = null;
    } catch (e) {
      error = e;
    } finally {
      loaded = true;
    }
  }
  onMount(load);

  const claudeStep = $derived(!!setup && setup.llm_mode === "cli" && !setup.claude_auth && !skipped);
  const working = $derived(setup?.claude_step === "installing" || setup?.claude_step === "logging_in");

  // Sondage toutes les 2 s tant que Claude s'installe ou que la connexion est en cours.
  $effect(() => {
    if (!working) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  });

  async function run(action: () => Promise<unknown>) {
    error = null;
    try {
      await action();
    } catch (e) {
      error = e;
      return;
    }
    await load();
  }

  const install = () => run(api.installClaude);
  const login = () => run(api.loginClaude);

  function skip() {
    skipClaude();
    skipped = true;
  }
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">Première configuration</p>
    <h1>Bienvenue</h1>
  </div>
</header>
<ErrorBanner {error} />

{#if loaded && !setup && !error}
  <section class="card stack"><p>L'assistant de configuration n'est pas disponible dans ce mode.</p></section>
{:else if setup && claudeStep}
  <section class="card stack">
    <h2>Étape 1 : Claude</h2>
    <p>CoachCloclo utilise ton abonnement Claude</p>
    {#if setup.claude_step === "installing"}
      <p class="busy" role="status">Installation en cours…</p>
    {:else if setup.claude_step === "logging_in"}
      <p class="busy" role="status">Connexion en cours… termine la connexion dans la page qui s'est ouverte dans ton navigateur.</p>
    {:else}
      {#if setup.claude_step === "failed"}
        <p class="error" role="alert">{setup.claude_error ?? "Une erreur est survenue"}</p>
      {/if}
      <div class="row">
        {#if setup.claude_step === "failed"}
          <button class="primary" onclick={setup.claude_cli ? login : install}>Réessayer</button>
        {:else if !setup.claude_cli}
          <button class="primary" onclick={install}>Installer Claude</button>
        {:else}
          <button class="primary" onclick={login}>Se connecter à Claude</button>
        {/if}
        <button type="button" onclick={skip}>Passer pour l'instant</button>
      </div>
    {/if}
  </section>
{:else if setup}
  <section class="card stack">
    <h2>Étape 2 : Garmin</h2>
    {#if setup.garmin === "ok"}
      <p>Garmin est connecté.</p>
      <div class="row"><button class="primary" onclick={() => onconnected?.()}>Continuer</button></div>
    {:else}
      <p>Connecte ton compte Garmin pour récupérer tes activités.</p>
      <GarminLogin {onconnected} />
    {/if}
  </section>
{/if}
