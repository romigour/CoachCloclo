<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type SettingsView, type Status } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";

  let { onchanged, onconnected }: { onchanged?: () => void; onconnected?: () => void } = $props();

  let status = $state<Status | null>(null);
  let settings = $state<SettingsView | null>(null);
  let error = $state<unknown>(null);

  let email = $state("");
  let password = $state("");
  let loginId = $state<string | null>(null);
  let code = $state("");
  let loginMessage = $state("");
  let busy = $state(false);

  let mode = $state<"cli" | "api">("cli");
  let apiKey = $state("");
  let model = $state("");
  let saved = $state(false);

  async function load() {
    try {
      status = await api.status();
      settings = await api.settings();
      mode = settings.llm_mode;
      model = settings.anthropic_model ?? "";
    } catch (e) {
      error = e;
    }
  }
  onMount(load);

  const GARMIN_LABEL = {
    ok: "Connecté",
    auth_required: "Connexion requise",
    unavailable: "Indisponible",
  } as const;

  async function login(e: Event) {
    e.preventDefault();
    busy = true;
    loginMessage = "";
    error = null;
    try {
      const r = await api.login(email, password);
      password = "";
      if (r.status === "needs_mfa") loginId = r.login_id ?? null;
      else await connected();
    } catch (err) {
      if (err instanceof ApiError && err.code === "garmin_login_failed") loginMessage = "Identifiants Garmin refusés";
      else error = err;
    } finally {
      busy = false;
    }
  }

  async function sendMfa(e: Event) {
    e.preventDefault();
    if (!loginId) return;
    busy = true;
    loginMessage = "";
    error = null;
    try {
      await api.mfa(loginId, code);
      loginId = null;
      code = "";
      await connected();
    } catch (err) {
      if (err instanceof ApiError && err.code === "garmin_login_failed") loginMessage = "Code refusé";
      else if (err instanceof ApiError && err.code === "mfa_expired") {
        loginId = null;
        loginMessage = "Connexion expirée, recommence";
      } else error = err;
    } finally {
      busy = false;
    }
  }

  async function connected() {
    await load();
    // L'app synchronise et choisit la page ; sans elle, on retombe sur objectif / plan.
    if (onconnected) return onconnected();
    onchanged?.();
    location.hash = status?.goal ? "#/plan" : "#/goal";
  }

  async function reimport() {
    error = null;
    try {
      await api.importHistory();
    } catch (err) {
      if (!(err instanceof ApiError && err.code === "history_running")) error = err;
    }
    await load();
    onchanged?.();
  }

  async function saveSettings(e: Event) {
    e.preventDefault();
    saved = false;
    error = null;
    try {
      settings = await api.saveSettings({
        llm_mode: mode,
        ...(apiKey ? { anthropic_api_key: apiKey } : {}),
        ...(model ? { anthropic_model: model } : {}),
      });
      apiKey = "";
      saved = true;
    } catch (err) {
      error = err;
    }
  }
</script>

<h1>Configuration</h1>
<ErrorBanner {error} onpin={load} />

<section class="card">
  <h2>État</h2>
  {#if status}
    <ul class="plain">
      <li>Garmin : <strong>{GARMIN_LABEL[status.garmin]}</strong></li>
      <li>Claude : <strong>{status.llm_mode === "cli" ? "Claude Code (CLI)" : "Clé API"}</strong></li>
      <li>Objectif : <strong>{status.goal ? `${status.goal.distance_km} km (${status.goal.type})` : "aucun"}</strong></li>
    </ul>
  {:else}
    <p>Chargement…</p>
  {/if}
</section>

<section class="card">
  <h2>Connexion Garmin</h2>
  {#if loginId}
    <form onsubmit={sendMfa}>
      <label>
        Code de vérification (MFA)
        <input bind:value={code} inputmode="numeric" autocomplete="one-time-code" required />
      </label>
      <button class="primary" disabled={busy}>Valider le code</button>
    </form>
  {:else}
    <form onsubmit={login}>
      <label>
        E-mail Garmin
        <input type="email" bind:value={email} autocomplete="username" required />
      </label>
      <label>
        Mot de passe
        <input type="password" bind:value={password} autocomplete="current-password" required />
      </label>
      <button class="primary" disabled={busy}>Se connecter</button>
    </form>
  {/if}
  {#if loginMessage}<p class="error" role="alert">{loginMessage}</p>{/if}
</section>

<section class="card">
  <h2>Historique Garmin</h2>
  {#if status}
    <p>
      {#if status.history.status === "running"}
        Import en cours… ({status.history.imported} activités)
      {:else if status.history.status === "error"}
        <span class="error">Import interrompu : {status.history.error ?? "erreur inconnue"}</span>
      {:else}
        {status.history.imported} activités importées
      {/if}
    </p>
    <button type="button" onclick={reimport} disabled={status.history.status === "running" || status.garmin !== "ok"}>
      Réimporter l'historique
    </button>
  {:else}
    <p>Chargement…</p>
  {/if}
</section>

<section class="card">
  <h2>Mode Claude</h2>
  <form onsubmit={saveSettings}>
    <label class="inline"><input type="radio" bind:group={mode} value="cli" /> Claude Code (CLI)</label>
    <label class="inline"><input type="radio" bind:group={mode} value="api" /> Clé API Anthropic</label>
    {#if mode === "api"}
      <label>
        Clé API {settings?.has_api_key ? "(déjà enregistrée, laisse vide pour la garder)" : ""}
        <input type="password" bind:value={apiKey} autocomplete="off" />
      </label>
      <label>
        Modèle (facultatif)
        <input bind:value={model} />
      </label>
    {/if}
    <button class="primary">Enregistrer</button>
    {#if saved}<span class="ok">Enregistré</span>{/if}
  </form>
</section>
