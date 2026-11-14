# Version mobile PWA en lecture seule — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un second build du front Svelte (« mobile ») publié sur GitHub Pages, qui lit directement la base Turso et affiche Aujourd'hui / Plan / Statistiques sans aucune action d'écriture.

**Architecture:** `api.ts` garde ses signatures ; quand `READONLY` (build `--mode mobile`), ses lectures délèguent par import dynamique à `web/src/lib/turso/`, qui exécute des `SELECT` écrits en dur via `@libsql/client/web` et reconstruit le JSON de l'API Python ; ses écritures lèvent `ApiError("readonly")`. Les écrans existants masquent leurs actions avec `{#if !READONLY}`. Des fixtures générées par l'API Python sur une base d'exemple garantissent la fidélité du portage.

**Tech Stack:** Svelte 5, TypeScript, Vite 6, Vitest, `@libsql/client` (web en prod, node `:memory:` en test), Python/pytest pour les fixtures, GitHub Actions + `actions/deploy-pages`.

**Spec:** `docs/superpowers/specs/2026-11-14-pwa-readonly-mobile-design.md`

## Global Constraints

- Aucune modification du Python applicatif ni du schéma ; seuls des tests / scripts Python s'ajoutent.
- Le build de bureau (`npm run build` → `coach/web_dist`) garde son comportement et ne contient pas le client libsql.
- Build mobile : `npm run build:mobile` → `web/dist-mobile` (ignoré par git), `base: "/CoachCloclo/app/"`.
- `web/src/lib/turso/` n'exporte que des lectures nommées ; aucune fonction générique d'exécution SQL n'est exportée hors du dossier.
- Le jeton n'apparaît jamais dans une URL, un log ou le bundle ; stockage `localStorage`, clé `coach.turso`, valeur `{"url": string, "token": string}`, accès en try/catch.
- Codes d'erreur et textes exacts :
  - `readonly` : « Action indisponible en lecture seule »
  - `auth` : « Jeton Turso refusé »
  - `unreachable` : « Base Turso injoignable »
  - `schema_too_new` : « Base plus récente que cette version mobile : recharge la page pour la mettre à jour »
  - `schema_outdated` : « Mets à jour l'appli de bureau puis relance-la une fois »
- Version de schéma connue : `SCHEMA_VERSION = 1` (comme `coach/plan/repo.py`).
- Texte proposition en attente : « Une proposition d'ajustement t'attend sur l'ordinateur ».
- Aide jeton : `turso db tokens create <base> --read-only`.
- « Aujourd'hui » = date locale du téléphone : `todayIso()` de `web/src/lib/dates.ts` (`turso/index.ts` le passe à `status`).
- Dates en base : texte `YYYY-MM-DD` ; booléens : entiers 0/1 (à convertir en `boolean`).

## Review Focus

1. `raw_json` illisible (texte non JSON) sur une activité → la ligne de stats sort avec les champs bruts à `null`, sans faire échouer toute la requête (`json_extract` lève sur JSON invalide : garder par `json_valid`). Test : Tâche 5.
2. Valeur booléenne ou texte dans `raw_json` (`"maxHR": true`, `"vO2MaxValue": "52"`) → `null`, comme `_finite` (exclut les booléens) ; `json_extract` renverrait `1`. Test : Tâche 5.
3. Base migrée par une ancienne appli de bureau (colonne absente) → message `schema_outdated`, pas d'erreur SQL brute, au démarrage comme en cours d'usage. Test : Tâche 3.
4. URL saisie sous forme `libsql://…`, `https://…/`, hôte nu en majuscules → même hôte normalisé. Test : Tâche 3.
5. `localStorage` indisponible (navigation privée) → l'écran de connexion s'affiche et fonctionne pour la session, sans exception. Test : Tâche 3.

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `web/src/lib/mode.ts` (créé) | `export const READONLY = import.meta.env.MODE === "mobile";` |
| `web/src/lib/turso/credentials.ts` (créé) | lire / écrire / effacer `{url, token}`, normaliser l'hôte |
| `web/src/lib/turso/db.ts` (créé) | type `Db` (sous-ensemble `execute` du client libsql), ouverture du client web, traduction des erreurs, vérif. schéma |
| `web/src/lib/turso/mappers.ts` (créé) | ports de `_cycle_dict`, `_goal_dict`, `_session_dict`, `_event_dict`, `_activity_row` |
| `web/src/lib/turso/reads.ts` (créé) | `status`, `plan`, `events`, `activities`, `zones` |
| `web/src/lib/turso/stats.ts` (créé) | `statsActivities`, `statsRecords` |
| `web/src/lib/turso/index.ts` (créé) | façade publique liée au client enregistré |
| `web/src/lib/turso/__fixtures__/` (créé, généré) | `active.sql`, `between.sql`, `expected.json` |
| `tests/mobile_fixtures.py` (créé) | construit les bases d'exemple et les réponses Python |
| `tests/api/test_mobile_fixtures.py` (créé) | échoue si les fixtures commitées sont périmées |
| `web/src/routes/Connection.svelte` (créé) | saisie / modification / effacement de la connexion |
| `web/src/lib/api.ts`, `App.svelte`, `Sidebar.svelte`, `Today.svelte`, `Plan.svelte`, `SessionCard.svelte`, `InjuryBanner.svelte`, `EventList.svelte`, `Stats.svelte`, `stats/Races.svelte` (modifiés) | branchement + masquage |
| `web/vite.config.ts`, `web/package.json`, `web/public/manifest.webmanifest`, `web/src/sw.ts`, `web/src/main.ts`, `web/index.html`, `.gitignore` (modifiés) | build mobile |
| `.github/workflows/pages.yml` (créé), `.github/workflows/ci.yml`, `README.md`, `docs/guide/index.html` (modifiés) | publication et doc |

---

### Task 1: Mode `READONLY` et build mobile

**Files:**
- Create: `web/src/lib/mode.ts`
- Modify: `web/vite.config.ts`, `web/package.json`, `web/public/manifest.webmanifest`, `web/src/sw.ts`, `web/src/main.ts`, `web/index.html`, `.gitignore`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `READONLY: boolean` exporté par `web/src/lib/mode.ts` (les tests le simulent par `vi.mock("…/lib/mode", () => ({ READONLY: true }))`).

- [ ] **Step 1: Créer `mode.ts`** avec la ligne de la table ci-dessus.
- [ ] **Step 2: `vite.config.ts` devient une fonction de `mode`** : si `mode === "mobile"`, `base: "/CoachCloclo/app/"`, `build.outDir: "dist-mobile"` (relatif à `web/`), pas de proxy ; sinon config actuelle inchangée. Script npm `"build:mobile": "vite build --mode mobile"`. Ajouter `web/dist-mobile/` à `.gitignore`.
- [ ] **Step 3: Chemins relatifs à la base.**
  - `manifest.webmanifest` : `start_url: "./"`, `scope: "./"`, icônes `"icon-192.png"` / `"icon-512.png"` (relatives au manifest : même résultat sur le bureau, servi à `/`).
  - `index.html` : liens `manifest`, icônes et `apple-touch-icon` sans `/` initial.
  - `main.ts` : `register(import.meta.env.BASE_URL + "sw.js")`.
  - `sw.ts` : `SHELL` résolu contre `self.registration.scope` (`new URL(p, scope).href` pour `"./"`, `"manifest.webmanifest"`, icônes, `"logo.svg"`) ; le filtre `/api` compare à `new URL("api", scope).pathname` ; le secours hors ligne utilise l'URL de la coquille résolue.
- [ ] **Step 4: Vérifier le build de bureau.**
  Run: `cd web && npm test && npm run build` — Expected: tests verts, `coach/web_dist/index.html` référence `manifest.webmanifest`.
- [ ] **Step 5: Vérifier le build mobile.**
  Run: `cd web && npm run build:mobile && grep -o 'src="/CoachCloclo/app/assets/[^"]*"' dist-mobile/index.html` — Expected: au moins une ligne.
- [ ] **Step 6: CI** — dans `ci.yml`, étape « Front », ajouter `npm run build:mobile` après `npm run build`.
- [ ] **Step 7: Commit** — `feat(web): build mobile (--mode mobile, base /CoachCloclo/app/)`.

---

### Task 2: Fixtures partagées Python → TS

**Files:**
- Create: `tests/mobile_fixtures.py`, `tests/api/test_mobile_fixtures.py`, `web/src/lib/turso/__fixtures__/{active.sql,between.sql,expected.json}`

**Interfaces:**
- Produces:
  - `active.sql`, `between.sql` : scripts SQL complets (`sqlite3.Connection.iterdump()` d'une base créée par `make_engine`, donc schéma réel + `appstate.schema_version`).
  - `expected.json` : `{"active": {...}, "between": {...}}`, chaque scénario ayant les clés `status`, `plan`, `events`, `activities` (objet `{"<week>": [...]}` pour chaque semaine du plan), `zones`, `stats_activities`, `stats_records` — réponses JSON des routes `/api/status`, `/api/plan`, `/api/cycle/events`, `/api/activities?week=N`, `/api/zones`, `/api/stats/activities`, `/api/stats/records`. Dans `status`, les clés `garmin`, `llm_mode`, `storage` sont retirées (propres au bureau).
  - Commande de régénération : `uv run python -m tests.mobile_fixtures`.

- [ ] **Step 1: Écrire `tests/mobile_fixtures.py`** avec `build(scenario: str, path: Path) -> None` (peuple une base via `Repo`) et `main()` (écrit les 3 fichiers). Requêtes HTTP via `TestClient(create_app(lan=False, garmin_factory=…, llm_factory=…, repo=repo))`, avec les mêmes faux Garmin/LLM que `tests/api/test_app.py`. Données à couvrir :
  - **active** : un cycle `active` accepté de 3 semaines dont `plan_start` est un lundi fixe (2026-03-02) ; séances de statuts variés (todo, exported, done, missed, sync_error, une séance vélo, une avec `scheduled_date`, une avec étapes groupées `repeat`) ; 2 objectifs dans le cycle + 1 au-delà (horizon) + 1 `done` + 1 `archived` (absent partout) ; imprévus : blessure ouverte, `light_week` avec `days_json`, `fatigue` avec `session_id` ; une proposition `pending` ; 2 instantanés athlète de dates différentes (le plus récent gagne pour `zones`) ; activités : course appariée (`match_source` auto), vélo libre, une avec `raw_json` invalide (`"pas du json"`), une avec `maxHR: true` et `vO2MaxValue: "52"`, une avec `eventType.typeKey = "race"` sans ligne `race`, une avec `race` renseignée, une avec `race.excluded = 1`, une avec `duration_s = 0`, une avec les 5 `hrTimeInZone_i` et une avec seulement 4 ; 2 records ; `appstate.history = {"status": "done", "imported": 42, "error": null}`.
  - **between** : aucun cycle actif, un cycle `done` terminé en 2020 (pour un `last_cycle` indépendant de la date du jour), un objectif `active` futur (2099), aucune activité.
- [ ] **Step 2: Générer** — Run: `uv run python -m tests.mobile_fixtures` — Expected: les 3 fichiers existent, `expected.json` contient `"active"` et `"between"`.
- [ ] **Step 3: Écrire `tests/api/test_mobile_fixtures.py::test_fixtures_a_jour`** : régénère dans `tmp_path` et `assert` que chaque fichier est identique octet pour octet au fichier commité (message d'échec : « Fixtures mobiles périmées : uv run python -m tests.mobile_fixtures »).
- [ ] **Step 4: Run** `uv run pytest tests/api/test_mobile_fixtures.py -v` — Expected: PASS. Puis modifier un champ dans `expected.json`, relancer — Expected: FAIL ; restaurer.
- [ ] **Step 5: Commit** — `test: fixtures partagées pour la version mobile`.

---

### Task 3: Connexion Turso, erreurs et vérification du schéma

**Files:**
- Create: `web/src/lib/turso/credentials.ts`, `web/src/lib/turso/db.ts`, `web/src/lib/turso/credentials.test.ts`, `web/src/lib/turso/db.test.ts`
- Modify: `web/package.json` (dépendance `@libsql/client`, version exacte épinglée comme les autres)

**Interfaces:**
- Produces:
  - `type Credentials = { url: string; token: string }`
  - `normalizeHost(url: string): string` — même règle que `turso_host` Python : retire le schéma, `/` final, minuscules, trim.
  - `loadCredentials(): Credentials | null`, `saveCredentials(c: Credentials): void`, `clearCredentials(): void` — repli en mémoire si `localStorage` lève.
  - `type Db = { execute(stmt: string | { sql: string; args: (string | number | null)[] }): Promise<{ rows: Record<string, unknown>[] }> }`
  - `openDb(c: Credentials): Db` — `createClient({ url: "https://" + normalizeHost(c.url), authToken: c.token })` de `@libsql/client/web`, enveloppé pour traduire les erreurs.
  - `toApiError(e: unknown): ApiError` — 401/403 ou message d'authentification → `auth` ; échec réseau (`TypeError`, `fetch failed`) → `unreachable` ; `no such column` / `no such table` → `schema_outdated` ; sinon `unreachable`.
  - `REQUIRED_COLUMNS: Record<string, string[]>` — chaque colonne lue par les tâches 4 et 5, par table.
  - `checkSchema(db: Db): Promise<void>` — lit `appstate.schema_version` : absente → `schema_outdated`, `v > 1` → `schema_too_new` ; puis `PRAGMA table_info(<table>)` pour chaque table de `REQUIRED_COLUMNS` : colonne manquante → `schema_outdated`.
  - `checkConnection(c: Credentials): Promise<void>` — `openDb` + `checkSchema`, lève l'`ApiError` traduite.

- [ ] **Step 1: Tests `credentials.test.ts`**
  - `normalizeHost` : `"libsql://Base-Org.turso.io"`, `"https://base-org.turso.io/"`, `" base-org.turso.io "` → tous `"base-org.turso.io"`.
  - aller-retour `saveCredentials` → `loadCredentials` ; `clearCredentials` → `null`.
  - `localStorage.setItem` / `getItem` qui lèvent (`vi.spyOn(Storage.prototype, …)`) : `saveCredentials` ne lève pas et `loadCredentials()` renvoie la valeur gardée en mémoire.
- [ ] **Step 2: Tests `db.test.ts`** sur un client `@libsql/client` `:memory:` chargé avec `active.sql` (helper `loadFixtureDb(name): Promise<Db>` dans `web/src/lib/turso/testing.ts`, réutilisé par les tâches 4 et 5) :
  - `checkSchema` passe sur `active.sql`.
  - `UPDATE appstate SET value_json='{"v":2}' WHERE key='schema_version'` → rejette avec `code === "schema_too_new"`.
  - `DELETE FROM appstate WHERE key='schema_version'` → `schema_outdated`.
  - `ALTER TABLE goal DROP COLUMN target_source` → `schema_outdated`.
  - `toApiError(new Error("SQLITE_ERROR: no such column: x"))` → `schema_outdated` ; `toApiError(new TypeError("fetch failed"))` → `unreachable` ; erreur porteuse d'un statut 401 → `auth`.
- [ ] **Step 3: Run** `cd web && npx vitest run src/lib/turso` — Expected: FAIL (modules absents).
- [ ] **Step 4: Implémenter** `credentials.ts`, `db.ts`, `testing.ts` selon les interfaces.
- [ ] **Step 5: Run** `cd web && npx vitest run src/lib/turso` — Expected: PASS.
- [ ] **Step 6: Commit** — `feat(mobile): connexion Turso, erreurs et contrôle du schéma`.

---

### Task 4: Lectures plan, imprévus, activités, zones, statut

**Files:**
- Create: `web/src/lib/turso/mappers.ts`, `web/src/lib/turso/reads.ts`, `web/src/lib/turso/reads.test.ts`

**Interfaces:**
- Consumes: `Db`, `loadFixtureDb` (Tâche 3) ; types `Status`, `Plan`, `CoachEvent`, `Activity`, `Zones` d'`api.ts`.
- Produces (chaque fonction renvoie exactement le JSON de la route Python homonyme) :
  - `plan(db: Db): Promise<Plan>`
  - `events(db: Db): Promise<CoachEvent[]>`
  - `activities(db: Db, week: number): Promise<Activity[]>`
  - `zones(db: Db): Promise<Zones | null>`
  - `status(db: Db, today: string): Promise<Status>` — `garmin: "unavailable"`, `llm_mode: "cli"`, `storage: null`, `history` lu dans `appstate` clé `history` (absent ou invalide → `{status: "idle", imported: 0, error: null}`), `pending_proposal_id` = dernière proposition `pending`.
- Ports à respecter (requêtes `Repo`, mêmes filtres et ordres) : `active_cycle`, `upcoming_goals`, `past_goals`, `last_done_cycle(today)` (seulement sans cycle actif), `goals_in`, `horizon_goals`, `open_injury`, `sessions` (ordre `week_index, order`), `events` (ordre `start_date DESC, id DESC`), `activities_since`, `has_activities`, `latest_snapshot` (ordre `date DESC, id DESC`), `pending_proposal` ; `week_monday = plan_start + 7·(week_index − 1)` jours.

- [ ] **Step 1: Tests `reads.test.ts`** — pour chaque scénario de `expected.json` (`active`, `between`) :
  - `expect(await plan(db)).toEqual(expected[s].plan)`
  - `expect(await events(db)).toEqual(expected[s].events)`
  - pour chaque clé `week` de `expected[s].activities` : `expect(await activities(db, Number(week))).toEqual(expected[s].activities[week])`
  - `expect(await zones(db)).toEqual(expected[s].zones)`
  - `const { garmin, llm_mode, storage, ...rest } = await status(db, "2026-11-14"); expect(rest).toEqual(expected[s].status)`
- [ ] **Step 2: Run** `cd web && npx vitest run src/lib/turso/reads.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implémenter** `mappers.ts` puis `reads.ts`. Les dates restent des chaînes ISO, les booléens 0/1 deviennent `boolean`, les champs `*_json` sont parsés (`available_days`, `steps`, `days`, `gpx_summary`).
- [ ] **Step 4: Run** le même test — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(mobile): lectures plan, imprévus, activités, zones et statut`.

---

### Task 5: Lectures des statistiques

**Files:**
- Create: `web/src/lib/turso/stats.ts`, `web/src/lib/turso/stats.test.ts`

**Interfaces:**
- Consumes: `Db`, `loadFixtureDb`.
- Produces: `statsActivities(db: Db): Promise<{ activities: StatActivity[] }>`, `statsRecords(db: Db): Promise<{ records: PersonalRecord[] }>`.
- Règles (port de `stat_row` / `coach/stats/normalize.py`) :
  - une seule requête `activity LEFT JOIN race`, ordre `date, id` ;
  - champs bruts extraits en SQL, jamais `raw_json` entier : pour chaque chemin (`$.startTimeLocal`, `$.activityName`, `$.maxHR`, `$.vO2MaxValue`, `$.hrTimeInZone_1`…`_5`, `$.eventType.typeKey`), `CASE WHEN json_valid(raw_json) AND json_type(raw_json) = 'object' THEN … END`, en sélectionnant aussi `json_type(raw_json, <chemin>)` pour les numériques ;
  - numérique retenu seulement si `json_type` ∈ {`integer`, `real`} (port de `_finite`, booléens exclus) ; `duration_s`, `distance_m` via `_positive` (> 0) ; `start` / `name` : chaîne seulement ;
  - `family` : table `FAMILIES` de `normalize.py` recopiée, inconnu → `"other"` ;
  - `hr_zones_s` : les 5 valeurs si toutes numériques, sinon `null` ;
  - `race` : ligne `race` non exclue → ses 7 champs ; pas de ligne et `eventType.typeKey === "race"` → 7 champs à `null` ; sinon `null`.

- [ ] **Step 1: Tests `stats.test.ts`**
  - pour chaque scénario : `expect(await statsActivities(db)).toEqual(expected[s].stats_activities)` et idem `statsRecords`.
  - activité au `raw_json` invalide de la fixture : `start`, `name`, `max_hr`, `vo2max`, `hr_zones_s` à `null` et la requête réussit.
  - activité `maxHR: true` / `vO2MaxValue: "52"` : `max_hr === null`, `vo2max === null`.
  - la requête envoyée ne lit pas `raw_json` entier : espionner `db.execute` et vérifier que le SQL ne contient pas `SELECT *` ni `raw_json,` en colonne de résultat (assertion : `!/\braw_json\s*(,|\bFROM)/i.test(sql)`).
- [ ] **Step 2: Run** `cd web && npx vitest run src/lib/turso/stats.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implémenter** `stats.ts`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(mobile): lectures des statistiques`.

---

### Task 6: Branchement dans `api.ts`

**Files:**
- Create: `web/src/lib/turso/index.ts`, `web/src/lib/api.readonly.test.ts`
- Modify: `web/src/lib/api.ts`

**Interfaces:**
- Consumes: tout `web/src/lib/turso/*`, `READONLY`.
- Produces:
  - `turso/index.ts` exporte `status()`, `plan()`, `events()`, `activities(week)`, `zones()`, `statsActivities()`, `statsRecords()` (sans `db` : ouvre le client sur `loadCredentials()`, mis en cache tant que les identifiants ne changent pas ; sans identifiants → `ApiError("auth", "Jeton Turso refusé")`) et ré-exporte `checkConnection`, `loadCredentials`, `saveCredentials`, `clearCredentials`, `normalizeHost`. Le premier appel après ouverture exécute `checkSchema`.
  - Toute erreur traduite par `toApiError`.
  - `turso.status()` : sur `ApiError` `auth` / `unreachable` / `schema_*`, renvoie le `Status` minimal du Python (cycle `null`, listes vides, `history` idle) avec `storage: { code, detail }`, pour réutiliser la page « Données indisponibles ».
  - Dans `api.ts` : les 7 lectures font `if (READONLY) return (await import("./turso")).<nom>(…)` ; toutes les autres entrées de `api` lèvent `new ApiError("readonly", "Action indisponible en lecture seule")` quand `READONLY` (enveloppe unique autour de l'objet, pas 40 `if`). `setupStatus`, `update`, `lan` renvoient `null` en lecture seule (pas d'erreur : App les lit au démarrage).

- [ ] **Step 1: Tests `api.readonly.test.ts`** avec `vi.mock("./mode", () => ({ READONLY: true }))` et `vi.mock("./turso", …)` :
  - `await expect(api.sync()).rejects.toMatchObject({ code: "readonly" })` ; idem `api.createEvent({} as never)`, `api.match(1, null)`, `api.saveRace(1, {})`, `api.deleteEvent(1)`, `api.importHistory()`.
  - `fetch` n'est jamais appelé (`vi.spyOn(globalThis, "fetch")` → `not.toHaveBeenCalled()`).
  - `await api.plan()` renvoie la valeur du mock `turso.plan`.
  - `await api.setupStatus()` → `null`.
- [ ] **Step 2: Run** `cd web && npx vitest run src/lib/api` — Expected: le nouveau test FAIL, `api.test.ts` existant PASS.
- [ ] **Step 3: Implémenter** `turso/index.ts` et le branchement.
- [ ] **Step 4: Run** `cd web && npm test` — Expected: PASS.
- [ ] **Step 5: Vérifier l'absence du client dans le build de bureau** — Run: `cd web && npm run build && ! grep -rl "hrana" ../coach/web_dist` — Expected: aucune sortie, code 0. Puis `npm run build:mobile && grep -rl "hrana" dist-mobile` — Expected: au moins un fichier.
- [ ] **Step 6: Commit** — `feat(mobile): api.ts lit Turso en lecture seule`.

---

### Task 7: Écrans en lecture seule

**Files:**
- Modify: `web/src/App.svelte`, `web/src/components/Sidebar.svelte`, `web/src/routes/Today.svelte`, `web/src/routes/Plan.svelte`, `web/src/components/SessionCard.svelte`, `web/src/components/InjuryBanner.svelte`, `web/src/components/EventList.svelte`, `web/src/routes/Stats.svelte`, `web/src/components/stats/Races.svelte`
- Test: `web/src/readonly.test.ts`

**Interfaces:**
- Consumes: `READONLY`, `api` (Tâche 6), `loadCredentials` (via `api`/`turso`), route `connection` (Tâche 8 fournit le composant ; ici seulement la route et le lien).

Masquages (`{#if !READONLY}`) :
- `App` : `ROUTES` en lecture seule = `today`, `plan`, `stats`, `connection` ; pas de synchro auto, pas de `UpdateBanner` ; sans identifiants → `#/connection` ; accueil `today` si `status.cycle?.plan_accepted`, sinon `stats` ; page « Données indisponibles » : lien « Modifier la connexion » vers `#/connection` au lieu des Réglages ; message « cycle terminé » sans lien.
- `Sidebar` : liens Aujourd'hui, Plan, Statistiques, Connexion ; bloc Garmin et bouton de synchro masqués ; Jour J, Proposition, Objectifs, Réglages masqués.
- `Today` / `Plan` : « Signaler un imprévu », `EventDialog`, « Générer » masqués ; carte proposition → `<p class="proposal-card">` avec le texte exact des contraintes, sans lien.
- `InjuryBanner` : bandeau visible, boutons (Réessayer, Signaler la reprise, Confirmer, Annuler) masqués.
- `EventList` : liste visible, « Supprimer » et la question de recalcul (Oui / Non) masqués.
- `SessionCard` : envoi montre, changer de jour, retirer, réessayer, correction du rattachement, dépliage prévu / réalisé et `ExportDialog` masqués ; étapes et statut visibles.
- `Stats` : import / reprise de l'historique masqués ; `Races` : « Ajouter une compétition », « Modifier » et `RaceEditDialog` masqués.

- [ ] **Step 1: Tests `readonly.test.ts`** (`vi.mock("./lib/mode", () => ({ READONLY: true }))`, `api` mocké avec les données de `expected.json` scénario `active`) :
  - rendu de `Today`, `Plan`, `Stats`, `Sidebar` : `screen.queryByRole("button", { name: /imprévu|générer|montre|changer de jour|retirer|réessayer|supprimer|importer|reprendre|compétition|modifier|synchro|reprise/i })` → `null` pour chacun.
  - `Plan` affiche la liste des imprévus (texte d'un imprévu de la fixture présent).
  - `Today` affiche « Une proposition d'ajustement t'attend sur l'ordinateur » et aucun lien `#/proposal`.
  - `Sidebar` : liens `#/today`, `#/plan`, `#/stats`, `#/connection` présents ; `#/goal`, `#/setup`, `#/race`, `#/proposal` absents.
  - `App` sans identifiants : `location.hash === "#/connection"` après montage.
- [ ] **Step 2: Run** `cd web && npx vitest run src/readonly.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implémenter** les masquages listés.
- [ ] **Step 4: Run** `cd web && npm test` — Expected: PASS (les tests existants, en mode bureau, restent verts).
- [ ] **Step 5: Commit** — `feat(mobile): écrans en lecture seule`.

---

### Task 8: Écran « Connexion »

**Files:**
- Create: `web/src/routes/Connection.svelte`, `web/src/routes/Connection.test.ts`
- Modify: `web/src/App.svelte` (rendu de la route `connection`, rappel `onchanged` → `refresh()` puis accueil)

**Interfaces:**
- Consumes: `checkConnection`, `loadCredentials`, `saveCredentials`, `clearCredentials`, `normalizeHost` (via `import("../lib/turso")`, dynamique pour rester hors du build de bureau).
- Produces: `<Connection onchanged={() => void} />`.

Comportement :
- Sans identifiants : formulaire URL + jeton (`type="password"`, `autocomplete="off"`), bouton « Valider » ; aide avec la commande du jeton en lecture seule.
- « Valider » : `checkConnection` ; succès → `saveCredentials` puis `onchanged()` ; échec → message de l'`ApiError` dans le formulaire, rien n'est enregistré.
- Avec identifiants : affiche `normalizeHost(url)` et le jeton masqué (`••••` + 4 derniers caractères), boutons « Modifier » (formulaire prérempli ; l'ancienne connexion reste tant que la nouvelle n'est pas validée) et « Effacer » (`confirm("Effacer la connexion de ce téléphone ?")` → `clearCredentials()`, formulaire vide).

- [ ] **Step 1: Tests `Connection.test.ts`** (`turso` mocké) :
  - `checkConnection` résolu → `saveCredentials` appelé avec `{url, token}` saisis et `onchanged` appelé.
  - `checkConnection` rejeté avec `ApiError("auth", "Jeton Turso refusé")` → texte « Jeton Turso refusé » affiché, `saveCredentials` non appelé.
  - identifiants présents → hôte affiché, jeton complet absent du DOM (`queryByText(token)` → `null`).
  - « Modifier » puis échec de validation → `saveCredentials` non appelé, l'ancienne connexion reste affichée après « Annuler ».
  - « Effacer » + `confirm` vrai → `clearCredentials` appelé, champ URL vide.
- [ ] **Step 2: Run** `cd web && npx vitest run src/routes/Connection.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implémenter** `Connection.svelte` dans le style des cartes existantes (`card stack`, `row`, `primary`, `danger`).
- [ ] **Step 4: Run** `cd web && npm test` — Expected: PASS.
- [ ] **Step 5: Essai manuel** — `cd web && npx vite --mode mobile`, ouvrir `http://localhost:5173/CoachCloclo/app/`, saisir une base Turso de test et un jeton en lecture seule : Aujourd'hui, Plan, Statistiques s'affichent ; « Effacer » ramène au formulaire.
- [ ] **Step 6: Commit** — `feat(mobile): écran de connexion Turso`.

---

### Task 9: Publication GitHub Pages et documentation

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify: `README.md`, `docs/guide/index.html`

**Interfaces:**
- Consumes: `npm run build:mobile` (Tâche 1).

- [ ] **Step 1: Écrire `pages.yml`**
  - `on`: `push` de tags `v*` ; `push` sur `master` avec `paths: ["docs/**"]` ; `workflow_dispatch`.
  - `permissions`: `contents: read`, `pages: write`, `id-token: write` ; `concurrency: { group: pages, cancel-in-progress: false }`.
  - Job build : checkout du commit déclencheur (guide) ; `actions/jekyll-build-pages` sur `docs/` → `_site` (respecte `docs/_config.yml`) ; second checkout `fetch-depth: 0` dans `release/`, puis `git -C release checkout $(git -C release describe --tags --abbrev=0 --match 'v*')` ; dans `release/web` : `npm ci && npm run build:mobile` ; copie de `release/web/dist-mobile` vers `_site/app` ; `actions/upload-pages-artifact` (`path: _site`).
  - Job deploy : `actions/deploy-pages`, environnement `github-pages`.
- [ ] **Step 2: Valider la syntaxe** — Run: `uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/pages.yml` — Expected: `ok`.
- [ ] **Step 3: Documentation** — `README.md` et `docs/guide/index.html` : section « Version mobile » (URL `https://romigour.github.io/CoachCloclo/app/`, installation sur l'écran d'accueil, création du jeton avec `turso db tokens create <base> --read-only`, ce qu'on peut consulter, mise à jour de l'appli de bureau si le message le demande).
- [ ] **Step 4: Commit** — `ci(pages): publie le guide et la version mobile`.
- [ ] **Step 5: Signaler à l'utilisateur** l'action manuelle : Settings → Pages → Source « GitHub Actions » (à faire avant le premier déploiement), puis lancer le workflow par `workflow_dispatch`.
