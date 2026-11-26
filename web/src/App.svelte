<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, claudeSkipped, setupDone, type GarminState, type SetupStatus, type Status } from "./lib/api";
  import { clearCache, noteWrite, pendingLoads } from "./lib/cache";
  import { loadZones, resetZones } from "./lib/zones.svelte";
  import { READONLY } from "./lib/mode";
  import { parseTab } from "./lib/stats/tabs";
  import ErrorBanner from "./components/ErrorBanner.svelte";
  import UpdateBanner from "./components/UpdateBanner.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import Welcome from "./routes/Welcome.svelte";
  import Setup from "./routes/Setup.svelte";
  import Goal from "./routes/Goal.svelte";
  import Program from "./routes/Program.svelte";
  import Week from "./routes/Week.svelte";
  import Proposal from "./routes/Proposal.svelte";
  import Race from "./routes/Race.svelte";
  import Stats from "./routes/Stats.svelte";

  type Route = "week" | "program" | "race" | "stats" | "goal" | "setup" | "proposal" | "welcome" | "connection";
  // En lecture seule (PWA mobile) : seules les pages de consultation et la connexion existent.
  const ROUTES: readonly Route[] = READONLY
    ? ["week", "program", "race", "stats", "connection"]
    : ["week", "program", "race", "stats", "goal", "setup", "proposal", "welcome"];
  // anciennes adresses (Aujourd'hui, Programme) : fusionnées dans « Ma semaine »
  const ALIASES: Record<string, Route> = { today: "week", plan: "week" };

  let route = $state<Route | null>(parse());
  let raceGoalId = $state<number | null>(parseGoalId()); // #/race/{id} : objectif choisi depuis la page Objectifs
  let statsTab = $state(parseTab(location.hash)); // #/stats/{sous-page}
  let status = $state<Status | null>(null);
  let garmin = $state<GarminState>("checking");
  let garminReads = 0; // numéro de la dernière lecture de l'état Garmin : une réponse plus ancienne est ignorée
  let starts = 0; // numéro du dernier démarrage (premier chargement, PIN saisi) : la suite d'un plus ancien est ignorée
  let setupAvailable = $state(false); // appli de bureau : l'écran d'accueil existe
  let error = $state<unknown>(null);
  let version = $state(0);
  let base = $state(1); // change quand le stockage a pu changer
  let generation = 0; // change avec la base : une lecture de l'état partie avant est ignorée
  let ready = $state(false);
  let syncing = $state(false);
  let resentNote = $state(""); // séances renvoyées à la montre par la dernière synchro
  let lastSync = $state<Date | null>(null);
  let posting = $state(false); // POST /api/sync en cours : la phase est lue chaque seconde
  let phase = $state<"garmin" | "claude" | null>(null);
  let autoSyncStarted = false; // une seule synchro automatique par chargement de l'app

  function parse(): Route | null {
    const raw = location.hash.replace(/^#\//, "").replace(/^race\/\d+$/, "race").replace(/^stats\/.*$/, "stats");
    const name = ALIASES[raw] ?? raw;
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

  /** Accueil selon les données : le plan en cours d'abord, sinon le cycle suivant à préparer, sinon les
   * statistiques, sinon l'objectif à fixer. */
  function dataHome(): string {
    if (READONLY) return status?.cycle?.plan_accepted ? "#/week" : "#/stats";
    if (status?.cycle?.plan_accepted) return "#/week";
    if (toPrepare) return "#/goal";
    return status?.has_activities ? "#/stats" : "#/goal";
  }

  /** Page d'accueil : les Réglages si Garmin est à reconnecter. */
  function home(): string {
    return !READONLY && garmin === "auth_required" ? "#/setup" : dataHome();
  }

  /** La base a pu changer : oublie l'état de l'ancienne, y compris les lectures en vol. */
  function forgetBase() {
    generation++;
    status = null;
    clearCache();
    resetZones();
  }

  /** Connexion Turso enregistrée : on relit les données puis on va à l'accueil. */
  async function connected() {
    forgetBase();
    version++; // relit les zones et recharge les pages (première connexion ou changement de base)
    await refresh();
    location.hash = home();
  }

  /** Connexion effacée : on reste sur la page de connexion et on oublie l'état de l'ancienne base. */
  function cleared() {
    forgetBase();
    error = null;
    location.hash = "#/connection";
  }

  /** Stockage changé depuis les Réglages : zones, pages et état viennent de la nouvelle base. */
  function storageSwitched() {
    forgetBase();
    base++;
    version++;
    refresh();
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
    const mine = generation;
    try {
      const next = await api.status();
      if (mine !== generation) return;
      // Fin d'import (réussie ou non) observée via le sondage : les statistiques doivent être rechargées.
      const ended = next.history.status === "done" || next.history.status === "error";
      if (status?.history.status === "running" && ended) {
        noteWrite(); // l'import a écrit côté serveur : une lecture partie avant sa fin est dépassée
        version++;
      }
      if (next.storage && !status?.storage) clearCache(); // passage en erreur de stockage
      status = next;
      if (clear) error = null;
    } catch (e) {
      if (mine === generation) error = e;
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

  /** Relit l'état Garmin (un échec vaut `unavailable`) ; `null` si une lecture plus récente est partie. */
  async function readGarmin(): Promise<GarminState | null> {
    const mine = ++garminReads;
    let next: GarminState;
    try {
      next = await api.garminState();
    } catch {
      next = "unavailable";
    }
    if (mine !== garminReads) return null;
    garmin = next;
    return next;
  }

  let moves = 0; // changements de page faits par l'utilisateur
  let ownHash: string | null = null; // changement fait par `go`, dont l'événement n'est pas encore arrivé

  /** Change de page ; la route suit sans attendre l'événement `hashchange`. */
  function go(hash: string) {
    if (location.hash !== hash) ownHash = hash;
    location.hash = hash;
    route = parse();
    statsTab = parseTab(location.hash);
  }

  async function start() {
    const mine = ++starts;
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
    let reads: Promise<[SetupStatus | null, GarminState | null]> | null = null;
    let garminRead: Promise<GarminState | null> | null = null;
    if (!READONLY) {
      garmin = "checking";
      garminRead = readGarmin();
      const setupRead = readSetup().then((s) => {
        if (mine === starts) setupAvailable = s !== null;
        return s;
      });
      reads = Promise.all([setupRead, garminRead]);
    }
    // Base changée pendant la lecture : la réponse a été ignorée, on relit.
    let read: number;
    do {
      read = generation;
      await refresh();
    } while (read !== generation && mine === starts);
    if (mine !== starts) return;
    ready = true;
    const usable = !!status && !error && !storageError;
    if (!reads || !garminRead) {
      if (!route) {
        if (usable) location.hash = home();
        // La lecture a échoué, la page de connexion évite une page blanche.
        else if (error) location.hash = "#/connection";
      }
      return;
    }
    const content = !!status && (!!status.cycle || status.goals.length > 0 || status.has_activities);
    const chosen = !route; // aucune page demandée : on la choisit
    if (chosen && usable && content) {
      go(dataHome());
    } else if (chosen) {
      // Premier lancement ou état illisible : l'installation et Garmin décident de la page.
      const [setup] = await reads;
      if (mine !== starts) return;
      if (!parse()) {
        // Configuration incomplète : l'écran d'accueil, même si /api/status a échoué.
        if (setup && !setupDone(setup, claudeSkipped())) go("#/welcome");
        else if (status && !error && !storageError) go(home());
      }
    }
    if (usable) autoSync(garminRead, mine);
    if (chosen && usable && content) reorient(reads, mine);
  }

  /** Accueil déjà affiché : renvoi vers l'installation ou Garmin s'il en manque, sauf si on a changé de page. */
  async function reorient(reads: Promise<[SetupStatus | null, GarminState | null]>, mine: number) {
    const shown = location.hash;
    const moved = moves;
    const [setup, state] = await reads;
    // `state` nul : Garmin a été reconnecté entre-temps, ces réponses ne valent plus.
    if (mine !== starts || state === null || moves !== moved || location.hash !== shown) return;
    if (setup && !setupDone(setup, claudeSkipped())) go("#/welcome");
    else if (state === "auth_required") go("#/setup");
  }

  /** Synchro de démarrage : Garmin connecté et contenu de la page chargé (5 s au plus). */
  async function autoSync(garminRead: Promise<GarminState | null>, mine: number) {
    if ((await garminRead) !== "ok" || mine !== starts) return;
    await contentLoaded();
    if (mine === starts && !autoSyncStarted && !storageError) sync();
  }

  /** Fin des lectures de la page affichée, 5 s au plus (une fenêtre masquée ne dessine rien). */
  async function contentLoaded() {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const limit = new Promise<void>((r) => (timer = setTimeout(r, 5000)));
    const drawn = new Promise<void>((r) => requestAnimationFrame(() => r()));
    await Promise.race([drawn.then(pendingLoads), limit]);
    clearTimeout(timer);
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

  // Pendant la synchro, la phase est lue chaque seconde ; une réponse arrivée après la fin est ignorée.
  $effect(() => {
    if (!posting) return;
    let active = true;
    let asking = false;
    const timer = setInterval(async () => {
      if (asking) return;
      asking = true;
      try {
        const next = await api.syncPhase();
        if (active) phase = next;
      } catch {
        // phase inconnue : on garde la précédente
      } finally {
        asking = false;
      }
    }, 1000);
    return () => {
      active = false;
      clearInterval(timer);
      phase = null;
    };
  });

  onMount(() => {
    const onhash = (e: HashChangeEvent) => {
      const target = e.newURL ? new URL(e.newURL).hash : location.hash; // l'adresse a pu changer depuis
      if (target === ownHash) ownHash = null;
      else if (target) moves++;
      route = parse();
      // Réglages ouverts : l'état Garmin a pu changer depuis le lancement (connexion revenue, session expirée).
      if (!READONLY && route === "setup" && garmin !== "checking") readGarmin();
      raceGoalId = parseGoalId();
      statsTab = parseTab(location.hash);
      error = null;
      if (READONLY && route !== "connection") guard();
    };
    window.addEventListener("hashchange", onhash);
    start();
    return () => {
      starts++; // plus de synchro de démarrage une fois l'application fermée
      window.removeEventListener("hashchange", onhash);
    };
  });

  /** Renvoie `false` si la synchro a échoué (l'erreur est alors affichée). */
  async function sync(): Promise<boolean> {
    if (syncing) return true;
    autoSyncStarted = true;
    syncing = posting = true;
    resentNote = "";
    try {
      const r = await api.sync().finally(() => (posting = false));
      if (r.resent > 0) {
        resentNote = `${r.resent} ${r.resent > 1 ? "séances mises" : "séance mise"} à jour sur ta montre (FC repos ${r.hr_rest})`;
      }
      lastSync = new Date();
      if (r.changed) version++;
      await refresh(); // toujours : la synchro a pu lancer un import
      return true;
    } catch (e) {
      failed(e);
      version++; // des données ont pu être écrites avant l'échec
      await refresh(false);
      return false;
    } finally {
      syncing = false;
    }
  }

  /** Connexion Garmin réussie depuis les Réglages : synchronise (même si une synchro a déjà eu lieu) puis oriente. */
  async function garminConnected() {
    autoSyncStarted = true;
    await Promise.all([refresh(), readGarmin()]);
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
    if (e instanceof ApiError && e.code === "garmin_auth") readGarmin();
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
  <Sidebar {route} {status} {garmin} {syncing} {lastSync} onsync={sync} />

  <main class="content">
    {#if !READONLY}<UpdateBanner />{/if}
    <ErrorBanner {error} onpin={start} {setupAvailable} />

    {#if phase === "claude"}
      <p class="card busy" role="status">Analyse de ta séance par Claude…</p>
    {/if}
    {#if resentNote}<p class="card busy" role="status">{resentNote}</p>{/if}

    {#if ready && !(error && (error as { code?: string }).code === "pin_required")}
      <!-- Autre base : la page affichée repart de zéro (les Réglages gardent leur message). -->
      {#key route === "setup" ? 0 : base}
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
          <Setup onchanged={refresh} onswitched={storageSwitched} onconnected={garminConnected} {syncing} {garmin} />
        {:else if route === "goal"}
          <Goal onchanged={refresh} />
        {:else if (route === "week" || route === "program") && toPrepare}
          <p class="card">
            Ton cycle est terminé et une course t'attend encore.
            {#if !READONLY}<a href="#/goal">Préparer le cycle suivant</a>{/if}
          </p>
        {:else if route === "week"}
          <Week {version} {status} onerror={failed} />
        {:else if route === "program"}
          <Program {version} />
        {:else if route === "race"}
          {#if status?.next_goal}
            <Race
              goals={status.goals}
              goalId={raceGoalId ?? status.next_goal.id}
              cycle={status.cycle}
              onerror={failed}
              onchanged={refresh}
            />
          {:else if !status && !error}
            <p class="busy">Chargement…</p>
          {:else if status}
            <p class="card">
              Aucun objectif actif : le jour J se prépare à partir d'un objectif.
              {#if !READONLY}<a href="#/goal">Créer un objectif</a>{/if}
            </p>
          {/if}
        {:else if route === "stats"}
          <Stats {version} tab={statsTab} history={status?.history ?? null} onimport={importHistory} />
        {:else if route === "proposal"}
          <Proposal onchanged={refresh} />
        {/if}
      {/key}
    {/if}
  </main>
</div>
