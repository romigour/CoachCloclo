<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type SettingsView, type Status } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import GarminLogin from "../components/GarminLogin.svelte";
  import LanSettings from "../components/LanSettings.svelte";
  import StorageSettings from "../components/StorageSettings.svelte";
  import UpdateSettings from "../components/UpdateSettings.svelte";
  import ThemeSettings from "../components/ThemeSettings.svelte";
  import ClaudeUsage from "../components/ClaudeUsage.svelte";
  import RestHrSettings from "../components/RestHrSettings.svelte";
  import DiagnosticSettings from "../components/DiagnosticSettings.svelte";
  import Icon from "../components/Icon.svelte";
  import { lastImport, newCount, totalLabel } from "../lib/history";

  let {
    onchanged,
    onswitched,
    onconnected,
    syncing = false,
  }: { onchanged?: () => void; onconnected?: () => void; onswitched?: () => void; syncing?: boolean } = $props();

  let status = $state<Status | null>(null);
  let settings = $state<SettingsView | null>(null);
  let error = $state<unknown>(null);

  let wizard = $state(false); // appli de bureau : l'assistant de configuration existe

  let mode = $state<"cli" | "api">("cli");
  let apiKey = $state("");
  let model = $state("");
  let saved = $state(false);

  let bases = $state(0); // change quand le stockage a pu changer : les blocs lus dans la base repartent de zéro
  let reading = 0; // numéro de la dernière lecture : une réponse plus ancienne est ignorée

  async function load() {
    const mine = ++reading;
    try {
      const s = await api.status();
      if (mine !== reading) return;
      status = s;
      const v = await api.settings();
      if (mine !== reading) return;
      settings = v;
      mode = v.llm_mode;
      model = v.anthropic_model ?? "";
    } catch (e) {
      if (mine === reading) error = e;
    }
  }

  /** Stockage changé : plus rien de l'ancienne base à l'écran, puis tout est relu. */
  function switched() {
    bases++;
    status = null;
    error = null;
    load();
    onswitched?.();
  }
  async function loadWizard() {
    try {
      wizard = (await api.setupStatus()) !== null;
    } catch {
      wizard = false;
    }
  }
  onMount(() => {
    load();
    loadWizard();
  });

  const GARMIN_LABEL = {
    ok: "Connecté",
    auth_required: "Connexion requise",
    unavailable: "Indisponible",
  } as const;

  async function connected() {
    garminForm = false;
    await load();
    // L'app synchronise et choisit la page ; sans elle, on retombe sur objectif / plan.
    if (onconnected) return onconnected();
    onchanged?.();
    location.hash = status?.cycle ? "#/week" : "#/goal";
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

  /** Le mode s'enregistre dès qu'on le change, sauf la clé API à saisir la première fois. */
  async function pickMode(next: "cli" | "api") {
    mode = next;
    if (next === "cli" || settings?.has_api_key) await saveSettings();
  }

  let garminForm = $state(false); // connecté : formulaire replié derrière « Changer de compte »

  const SECTIONS = [
    { id: "connexions", label: "Connexions" },
    { id: "claude", label: "Claude" },
    { id: "donnees", label: "Données" },
    { id: "application", label: "Application" },
    { id: "diagnostic", label: "Diagnostic" },
  ] as const;
  let current = $state<string>("connexions");

  let pinnedUntil = 0; // après un clic, le défilement doux ne doit pas déplacer la sélection

  function goTo(id: string) {
    current = id;
    pinnedUntil = Date.now() + 1000;
    document.getElementById(`set-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /** Section courante : la dernière dont le titre est passé sous le haut de l'écran ; tout en bas, la dernière. */
  function track() {
    if (Date.now() < pinnedUntil) return;
    const doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 4) {
      current = SECTIONS[SECTIONS.length - 1].id;
      return;
    }
    let found: string = SECTIONS[0].id;
    for (const s of SECTIONS) {
      const el = document.getElementById(`set-${s.id}`);
      if (el && el.getBoundingClientRect().top <= 120) found = s.id;
    }
    current = found;
  }

  onMount(() => {
    window.addEventListener("scroll", track, { passive: true });
    return () => window.removeEventListener("scroll", track);
  });

  async function saveSettings(e?: Event) {
    e?.preventDefault();
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

<div class="settings-wrap">
<div class="settings">
  <nav class="settings-nav" aria-label="Sections des réglages">
    {#each SECTIONS as s (s.id)}
      <button type="button" aria-current={current === s.id ? "true" : undefined} onclick={() => goTo(s.id)}>{s.label}</button>
    {/each}
  </nav>

  <div class="settings-body">
    <section class="set-group" id="set-connexions" aria-labelledby="set-connexions-h">
      <header>
        <h2 id="set-connexions-h">Connexions</h2>
        <p class="meta">Les comptes que CoachCloclo utilise.</p>
      </header>
      <div class="set-list">
        <div class="set-row">
          <div class="set-label">
            <h3>Connexion Garmin</h3>
            {#if status?.garmin === "ok"}
              <p>Compte Garmin Connect relié. Saisis un autre compte pour en changer.</p>
            {:else}
              <p>Connecte ton compte Garmin Connect pour importer tes activités.</p>
            {/if}
          </div>
          <div class="set-ctl">
            {#if status}
              <span class="state-pill" class:ok={status.garmin === "ok"} class:ko={status.garmin !== "ok"}>
                {GARMIN_LABEL[status.garmin]}
              </span>
            {/if}
            {#if status?.garmin === "ok" && !garminForm}
              <button type="button" onclick={() => (garminForm = true)}>Changer de compte</button>
            {/if}
          </div>
          {#if status && (status.garmin !== "ok" || garminForm)}
            <div class="set-extra boxed">
              <GarminLogin onconnected={connected} oncancel={garminForm ? () => (garminForm = false) : undefined} />
            </div>
          {/if}
        </div>
        {#if wizard}
          <div class="set-row">
            <div class="set-label">
              <h3>Assistant de configuration</h3>
              <p>Installer ou reconnecter Claude, puis Garmin.</p>
            </div>
            <div class="set-ctl"><a class="button" href="#/welcome">Ouvrir l'assistant</a></div>
          </div>
        {/if}
      </div>
    </section>

    <section class="set-group" id="set-claude" aria-labelledby="set-claude-h">
      <header>
        <h2 id="set-claude-h">Claude</h2>
        <p class="meta">Comment le plan est généré, et ce que ça coûte.</p>
      </header>
      <div class="set-list">
        <div class="set-row">
          <div class="set-label">
            <h3 id="mode-claude">Mode Claude</h3>
            <p>
              {mode === "cli" ? "Claude Code installé sur ce PC, avec ton abonnement." : "Appels directs à l'API Anthropic avec ta clé."}
              {#if saved}<span class="ok">Enregistré</span>{/if}
            </p>
          </div>
          <div class="set-ctl">
            <div class="segmented" role="radiogroup" aria-labelledby="mode-claude">
              <label>
                <input type="radio" name="llm-mode" value="cli" checked={mode === "cli"} onchange={() => pickMode("cli")} />
                <span>Claude Code (CLI)</span>
              </label>
              <label>
                <input type="radio" name="llm-mode" value="api" checked={mode === "api"} onchange={() => pickMode("api")} />
                <span>Clé API Anthropic</span>
              </label>
            </div>
          </div>
          {#if mode === "api"}
            <form class="set-extra boxed" onsubmit={saveSettings}>
              <div class="form-grid">
                <label>
                  Clé API {settings?.has_api_key ? "(déjà enregistrée, laisse vide pour la garder)" : ""}
                  <input type="password" bind:value={apiKey} autocomplete="off" />
                </label>
                <label>
                  Modèle (facultatif)
                  <input bind:value={model} />
                </label>
              </div>
              <div class="row end"><button class="primary">Enregistrer</button></div>
            </form>
          {/if}
        </div>
        {#key bases}<ClaudeUsage />{/key}
      </div>
    </section>

    <section class="set-group" id="set-donnees" aria-labelledby="set-donnees-h">
      <header>
        <h2 id="set-donnees-h">Données</h2>
        <p class="meta">Ton historique d'activités et l'endroit où il est stocké.</p>
      </header>
      <div class="set-list">
        <div class="set-row">
          <div class="set-label">
            <h3>Historique Garmin</h3>
            {#if !status}
              <p>Chargement…</p>
            {:else if status.history.status === "running"}
              <p class="busy" role="status">Import en cours… ({newCount(status.history.imported)})</p>
            {:else if status.history.status === "error"}
              <p class="error">Import interrompu : {status.history.error ?? "erreur inconnue"}</p>
            {:else}
              {@const last = lastImport(status.history)}
              <p>{totalLabel(status.history.total)}</p>
              {#if last}<p class="meta">{last}</p>{/if}
            {/if}
          </div>
          {#if status}
            <div class="set-ctl">
              <button type="button" onclick={reimport} disabled={status.history.status === "running" || status.garmin !== "ok"}>
                <Icon name="sync" size={15} /> Réimporter l'historique
              </button>
            </div>
          {/if}
        </div>
        {#key bases}<RestHrSettings {syncing} />{/key}
        <StorageSettings onswitched={switched} />
      </div>
    </section>

    <section class="set-group" id="set-application" aria-labelledby="set-application-h">
      <header>
        <h2 id="set-application-h">Application</h2>
        <p class="meta">Apparence, mises à jour et accès depuis ton téléphone.</p>
      </header>
      <div class="set-list">
        <ThemeSettings />
        <UpdateSettings />
        <LanSettings />
      </div>
    </section>

    <section class="set-group" id="set-diagnostic" aria-labelledby="set-diagnostic-h">
      <header>
        <h2 id="set-diagnostic-h">Diagnostic</h2>
        <p class="meta">Enregistre le détail des échanges pour comprendre un échec. Les mots de passe et clés sont masqués.</p>
      </header>
      <DiagnosticSettings />
    </section>
  </div>
</div>
</div>
