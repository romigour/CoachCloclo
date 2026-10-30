<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type SettingsView, type Status } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Icon from "../components/Icon.svelte";

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

<header class="page-head">
  <div>
    <p class="eyebrow">Connexions Garmin et Claude</p>
    <h1>Réglages</h1>
  </div>
</header>
<ErrorBanner {error} onpin={load} />

<div class="settings-grid">

<section class="card stack">
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

<section class="card stack">
  <h2>Connexion Garmin</h2>
  {#if loginId}
    <form class="stack" onsubmit={sendMfa}>
      <label>
        Code de vérification (MFA)
        <input bind:value={code} inputmode="numeric" autocomplete="one-time-code" required />
      </label>
      <div class="row"><button class="primary" disabled={busy}>Valider le code</button></div>
    </form>
  {:else}
    <form class="stack" onsubmit={login}>
      <label>
        E-mail Garmin
        <input type="email" bind:value={email} autocomplete="username" required />
      </label>
      <label>
        Mot de passe
        <input type="password" bind:value={password} autocomplete="current-password" required />
      </label>
      <div class="row"><button class="primary" disabled={busy}>Se connecter</button></div>
    </form>
  {/if}
  {#if loginMessage}<p class="error" role="alert">{loginMessage}</p>{/if}
</section>

<section class="card stack">
  <h2>Historique Garmin</h2>
  {#if status}
    {#if status.history.status === "running"}
      <p class="busy" role="status">Import en cours… ({status.history.imported} activités)</p>
    {:else if status.history.status === "error"}
      <p class="error">Import interrompu : {status.history.error ?? "erreur inconnue"}</p>
    {:else}
      <p>{status.history.imported} activités importées</p>
    {/if}
    <div class="row">
      <button type="button" onclick={reimport} disabled={status.history.status === "running" || status.garmin !== "ok"}>
        <Icon name="sync" size={15} /> Réimporter l'historique
      </button>
    </div>
  {:else}
    <p>Chargement…</p>
  {/if}
</section>

<section class="card stack">
  <h2>Mode Claude</h2>
  <form class="stack" onsubmit={saveSettings}>
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
    <div class="row">
      <button class="primary">Enregistrer</button>
      {#if saved}<span class="ok">Enregistré</span>{/if}
    </div>
  </form>
</section>
</div>
