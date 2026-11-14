<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, claudeSkipped, setupDone, type SetupStatus, type Status } from "./lib/api";
  import { loadZones } from "./lib/zones.svelte";
  import { READONLY } from "./lib/mode";
  import ErrorBanner from "./components/ErrorBanner.svelte";
  import UpdateBanner from "./components/UpdateBanner.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import Welcome from "./routes/Welcome.svelte";
  import Setup from "./routes/Setup.svelte";
  import Goal from "./routes/Goal.svelte";
  import Today from "./routes/Today.svelte";
  import Plan from "./routes/Plan.svelte";
  import Proposal from "./routes/Proposal.svelte";
  import Race from "./routes/Race.svelte";
  import Stats from "./routes/Stats.svelte";

  type Route = "today" | "plan" | "race" | "stats" | "goal" | "setup" | "proposal" | "welcome" | "connection";
  // En lecture seule (PWA mobile) : seules les pages de consultation et la connexion existent.
  const ROUTES: readonly Route[] = READONLY
    ? ["today", "plan", "stats", "connection"]
    : ["today", "plan", "race", "stats", "goal", "setup", "proposal", "welcome"];

  let route = $state<Route | null>(parse());
  let raceGoalId = $state<number | null>(parseGoalId()); // #/race/{id} : objectif choisi depuis la page Objectifs
  let status = $state<Status | null>(null);
  let setupAvailable = $state(false); // appli de bureau : l'écran d'accueil existe
  let error = $state<unknown>(null);
  let version = $state(0);
  let ready = $state(false);
  let syncing = $state(false);
  let lastSync = $state<Date | null>(null);
  let autoSyncStarted = false; // une seule synchro automatique par chargement de l'app

  function parse(): Route | null {
    const name = location.hash.replace(/^#\//, "").replace(/^race\/\d+$/, "race");
    return (ROUTES as readonly string[]).includes(name) ? (name as Route) : null;
  }

  function parseGoalId(): number | null {
    const m = /^#\/race\/(\d+)$/.exec(location.hash);
    return m ? Number(m[1]) : null;
  }

  // base indisponible (cloud injoignable, schéma trop récent) : page dédiée plutôt que les pages vides
  const storageError = $derived(status?.storage ?? null);

  // cycle terminé et objectifs encore à venir : le cycle suivant est à préparer (page Objectifs)
  const toPrepare = $derived(!!status && status.cycle === null && status.goals.length > 0);

  /** Page d'accueil : le plan en cours d'abord, sinon le cycle suivant à préparer, sinon les statistiques,
   * sinon l'objectif à fixer. */
  function home(): string {
    if (READONLY) return status?.cycle?.plan_accepted ? "#/today" : "#/stats";
    if (status?.garmin === "auth_required") return "#/setup";
    if (status?.cycle?.plan_accepted) return "#/today";
    if (toPrepare) return "#/goal";
    return status?.has_activities ? "#/stats" : "#/goal";
  }

  /** Connexion Turso enregistrée : on relit les données puis on va à l'accueil. */
  async function connected() {
    version++; // relit les zones et recharge les pages (première connexion ou changement de base)
    await refresh();
    location.hash = home();
  }

  /** Connexion effacée : on reste sur la page de connexion et on oublie l'état de l'ancienne base. */
  function cleared() {
    status = null;
    error = null;
    location.hash = "#/connection";
  }

  /** Lecture seule : toute route inconnue ou sans identifiants est renvoyée vers l'accueil ou la connexion. */
  async function guard() {
    const { loadCredentials } = await import("./lib/turso");
    if (!loadCredentials()) {
      if (location.hash !== "#/connection") location.hash = "#/connection";
    } else if (!parse()) {
      location.hash = home();
    }
  }

  /** Relit l'état ; `clear` efface l'erreur affichée (pas depuis le sondage, qui la ferait disparaître). */
  async function refresh(clear = true) {
    try {
      const next = await api.status();
      // Fin d'import (réussie ou non) observée via le sondage : les statistiques doivent être rechargées.
      const ended = next.history.status === "done" || next.history.status === "error";
      if (status?.history.status === "running" && ended) version++;
      status = next;
      if (clear) error = null;
    } catch (e) {
      error = e;
    }
  }

  /** État de l'écran d'accueil ; `null` sous `coach start` (404) ou si la lecture échoue. */
  async function readSetup(): Promise<SetupStatus | null> {
    try {
      return await api.setupStatus();
    } catch {
      return null;
    }
  }

  async function start() {
    if (READONLY) {
      // Import dynamique : libsql ne doit pas entrer dans le bundle bureau.
      const { loadCredentials } = await import("./lib/turso");
      if (!loadCredentials()) {
        location.hash = "#/connection";
        route = parse();
        ready = true;
        return;
      }
    }
    const [setup] = await Promise.all([readSetup(), refresh()]);
    setupAvailable = setup !== null;
    ready = true;
    if (!READONLY && !autoSyncStarted && !error && !storageError && status?.garmin === "ok") {
      autoSyncStarted = true;
      sync();
    }
    if (!route) {
      // Configuration incomplète : l'écran d'accueil, même si /api/status a échoué.
      if (setup && !setupDone(setup, claudeSkipped())) location.hash = "#/welcome";
      else if (!error && !storageError) location.hash = home();
      // Lecture seule : la lecture a échoué, la page de connexion évite une page blanche.
      else if (READONLY && error) location.hash = "#/connection";
    }
  }

  /** « Réessayer » sur la page de base indisponible : relit l'état, puis oriente si la base est revenue. */
  async function retryStorage() {
    await refresh();
    if (!storageError && !error && !route) location.hash = home();
  }

  // Zones au démarrage puis après chaque synchro ou fin d'import (nouvel instantané possible).
  $effect(() => {
    void version;
    loadZones();
  });

  // Pendant l'import de l'historique, on relit l'état toutes les 5 s ; l'intervalle s'arrête dès que l'état change.
  const importRunning = $derived(status?.history.status === "running");
  $effect(() => {
    if (!importRunning) return;
    const timer = setInterval(() => refresh(false), 5000);
    return () => clearInterval(timer);
  });

  onMount(() => {
    const onhash = () => {
      route = parse();
      raceGoalId = parseGoalId();
      error = null;
      if (READONLY && route !== "connection") guard();
    };
    window.addEventListener("hashchange", onhash);
    start();
    return () => window.removeEventListener("hashchange", onhash);
  });

  /** Renvoie `false` si la synchro a échoué (l'erreur est alors affichée). */
  async function sync(): Promise<boolean> {
    if (syncing) return true;
    syncing = true;
    try {
      await api.sync();
      lastSync = new Date();
      version++;
      await refresh();
      return true;
    } catch (e) {
      failed(e);
      return false;
    } finally {
      syncing = false;
    }
  }

  /** Connexion Garmin réussie depuis les Réglages : synchronise (même si une synchro a déjà eu lieu) puis oriente. */
  async function garminConnected() {
    await refresh();
    autoSyncStarted = true;
    if (status?.has_activities) {
      // Activités déjà là : on les montre tout de suite, la synchro se fait en arrière-plan.
      location.hash = home();
      sync();
      return;
    }
    // Premier lancement : la synchro ramène les activités récentes et lance l'import de l'historique.
    // En cas d'échec on reste sur les Réglages : changer de page effacerait le message d'erreur.
    if (!(await sync())) return;
    location.hash = home();
  }

  function failed(e: unknown) {
    error = e;
  }

  async function importHistory() {
    try {
      await api.importHistory();
      refresh();
    } catch (e) {
      // Un import est déjà en cours : on se contente de relire l'état.
      if (e instanceof ApiError && e.code === "history_running") refresh();
      else failed(e);
    }
  }
</script>

<div class="shell">
  <Sidebar {route} {status} {syncing} {lastSync} onsync={sync} />

  <main class="content">
    {#if !READONLY}<UpdateBanner />{/if}
    <ErrorBanner {error} onpin={start} {setupAvailable} />

    {#if syncing}
      <p class="card busy" role="status">
        {status?.cycle ? "Analyse de ta séance par Claude…" : "Synchronisation Garmin…"}
      </p>
    {/if}

    {#if ready && !(error && (error as { code?: string }).code === "pin_required")}
      {#if storageError && route !== "setup" && route !== "welcome" && route !== "connection"}
        <section class="card stack" role="alert">
          <h2>Données indisponibles</h2>
          <p>{storageError.detail}</p>
          <div class="row">
            <button type="button" class="primary" onclick={retryStorage}>Réessayer</button>
            {#if READONLY}
              <a href="#/connection">Modifier la connexion</a>
            {:else}
              <a href="#/setup">Ouvrir les Réglages</a>
            {/if}
          </div>
        </section>
      {:else if READONLY && route === "connection"}
        <!-- Import dynamique gardé par READONLY : libsql reste hors du build de bureau. -->
        {#await import("./routes/Connection.svelte") then { default: Connection }}
          <Connection onchanged={connected} oncleared={cleared} />
        {:catch}
          <section class="card stack" role="alert">
            <p>Impossible de charger l'écran de connexion.</p>
            <div class="row"><button type="button" class="primary" onclick={() => location.reload()}>Réessayer</button></div>
          </section>
        {/await}
      {:else if route === "welcome"}
        <Welcome onconnected={garminConnected} />
      {:else if route === "setup"}
        <Setup onchanged={refresh} onconnected={garminConnected} />
      {:else if route === "goal"}
        <Goal onchanged={refresh} />
      {:else if (route === "today" || route === "plan") && toPrepare}
        <p class="card">
          Ton cycle est terminé et une course t'attend encore.
          {#if !READONLY}<a href="#/goal">Préparer le cycle suivant</a>{/if}
        </p>
      {:else if route === "today"}
        <Today {version} {status} onerror={failed} />
      {:else if route === "plan"}
        <Plan {version} onerror={failed} />
      {:else if route === "race"}
        {#if status?.next_goal}
          <Race
            goals={status.goals}
            goalId={raceGoalId ?? status.next_goal.id}
            cycle={status.cycle}
            onerror={failed}
            onchanged={refresh}
          />
        {:else}
          <p class="card">Aucun objectif actif : le jour J se prépare à partir d'un objectif. <a href="#/goal">Créer un objectif</a></p>
        {/if}
      {:else if route === "stats"}
        <Stats {version} history={status?.history ?? null} onimport={importHistory} />
      {:else if route === "proposal"}
        <Proposal onchanged={refresh} />
      {/if}
    {/if}
  </main>
</div>
