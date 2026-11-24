# Chargement rapide des pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pages rapides en mode Turso et démarrage discret quand rien n'a changé.

**Architecture:** Lot 1 (tâches 1 à 5) : un pilote DBAPI HTTP (Hrana v2, `httpx`) remplace `libsql`, puis les lectures de `/plan`, `/status` et `/activities` sont groupées. Lot 2 (tâches 6 à 9) : état Garmin et phase de synchro sur des routes sans base, synchro qui n'écrit que les changements, cache mémoire dans le front. Le lot 1 est livrable seul.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy 2, httpx ; Svelte 5, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-11-24-chargement-rapide-design.md`

## Global Constraints

- Aucun changement de schéma (`SCHEMA_VERSION` reste 3) ; mode local et PWA mobile sans régression.
- Une écriture ou un `COMMIT` n'est jamais rejoué. Un `SELECT` hors transaction est rejoué une seule fois.
- Le jeton Turso n'apparaît dans aucun message, `repr` ni journal.
- `/api/plan` et `/api/status` : au plus 3 envois HTTP à la base.
- « Analyse de ta séance par Claude… » seulement en phase `claude` ; le bandeau « Synchronisation Garmin… » disparaît.
- Commentaires et docstrings en français, comme le reste du dépôt.
- Tests Python : `python -m pytest` avec `C:\GIT\CoachCloclo\.venv\Scripts\python.exe`, lancé depuis le worktree. Tests front : `npm test` dans `web/` (`npm ci` au préalable).
- Chaque commit finit par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Veille du PC : connexion gardée ouverte morte au réveil → la première lecture aboutit sans erreur affichée (tâche 1).
2. Coupure pendant un `COMMIT` → erreur visible, jamais de seconde écriture (tâche 1).
3. Bascule de base pendant qu'une lecture est en vol → l'ancienne réponse ne s'affiche pas et n'entre pas en cache (tâche 8).
4. Garmin déconnecté ou très lent → pages consultables, pas de renvoi vers les Réglages si l'utilisateur a déjà navigué (tâche 7).
5. Séance rattachée pendant une relecture du plan → la réponse antérieure au rattachement n'écrase pas l'affichage (tâche 8).

---

## Lot 1 : accès à la base

### Task 1: Pilote Hrana et faux serveur

**Files:**
- Create: `coach/storage/hrana.py` (module DBAPI), `tests/storage/fake_hrana.py`, `tests/storage/test_hrana.py`
- Modify: `pyproject.toml` (ajouter `httpx` aux dépendances ; le retirer du groupe dev)

**Interfaces:**
- Produces: `connect(base_url: str, *, auth_token: str, client: httpx.Client) -> Connection` ; `make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client` ; `Connection.prefetch(sqls: list[str]) -> None` ; `Connection.commit/rollback/close/cursor` ; `Cursor.execute/executemany/fetchone/fetchmany/fetchall/description/rowcount/lastrowid/close`.
- Produces: attributs DBAPI `paramstyle="qmark"`, `threadsafety=1`, `apilevel="2.0"`, `sqlite_version_info=(3, 45, 0)`, `sqlite_version="3.45.0"`, `Binary=bytes` ; exceptions PEP 249, plus `CloudNetworkError(OperationalError)` et `CloudAuthError(OperationalError)`.
- Produces (tests): `FakeHrana(path)` avec `.transport` (`httpx.MockTransport`), `.sends: int`, `.requests: list[dict]`, `.fail_next(kind: Literal["drop_before", "drop_after", "http_401", "http_500", "expire_baton"])`, `.delay_s: float`. Il exécute les requêtes sur un fichier SQLite, une connexion par flux.

Décisions de protocole :
- `POST {base}/v2/pipeline`, en-tête `Authorization: Bearer`. Arguments typés `null`/`integer` (valeur en chaîne)/`float`/`text`/`blob` (base64, décodage tolérant à l'absence de `=`) ; `bool` devient entier.
- Une pipeline Hrana continue après une erreur : tout envoi multiple est une requête `batch` dont chaque étape a la condition `{"type": "ok", "step": i-1}`. Les lectures préchargées n'ont pas de condition.
- Lecture = premier mot `SELECT`, `PRAGMA`, `EXPLAIN` ou `WITH`. Hors transaction, une lecture est suivie de `close` dans le même envoi.
- Première écriture : batch `[BEGIN, stmt]`, `baton` (et `base_url` si renvoyé) gardé. Ensuite tout passe par ce flux. `commit` = `COMMIT` + `close` ; `rollback` = `ROLLBACK` + `close`, en ignorant une panne réseau ; tous deux sans appel si aucun flux n'est ouvert.
- `executemany` : un batch par tranche d'environ 1 Mo d'arguments ; `rowcount` = somme.
- `PRAGMA table_info` et `RETURNING` renvoient leurs lignes normalement.
- `prefetch` envoie tout en un batch et garde les résultats par texte SQL ; `execute` d'un SQL sans paramètre les consomme une fois ; toute écriture vide le stock.
- Erreurs : code `SQLITE_CONSTRAINT*` → `IntegrityError` ; autre erreur SQL → `DatabaseError` ; HTTP 401/403 → `CloudAuthError` ; autre statut d'erreur, `httpx.TransportError`, flux expiré → `CloudNetworkError`.
- Rejeu : lecture hors transaction, sur `httpx.RemoteProtocolError`, `httpx.ReadError` ou `httpx.WriteError`.
- Client : `keepalive_expiry=300`, 20 connexions max, délai 30 s, certificats par défaut de `httpx` (`SSL_CERT_FILE` respecté).

- [ ] **Step 1: Écrire `FakeHrana` et les tests qui échouent**

Noms et assertions (fixture `conn` = `connect` sur `FakeHrana`) :

```python
def test_types_roundtrip():      # None, 2**62, 1.5, "é", b"\x00\xff", True -> 1
def test_read_is_one_send():     # 1 SELECT + commit() + close() : sends == 1, corps sans BEGIN
def test_first_write_begins():   # INSERT : batch [BEGIN, INSERT] ; puis commit : sends == 2 ; ligne visible d'une autre connexion
def test_rollback_discards()
def test_error_in_batch_skips_rest():  # executemany dont la 2e ligne viole UNIQUE : IntegrityError, puis rollback : 0 ligne
def test_rowcount_and_lastrowid()      # UPDATE touchant 2 lignes -> 2 ; INSERT OR IGNORE ignoré -> 0
def test_read_retried_once():          # drop_before : résultat correct, sends == 2 ; deux coupures : CloudNetworkError
def test_write_never_retried():        # drop_after sur INSERT : CloudNetworkError, sends == 1
def test_commit_never_retried():       # drop_after sur COMMIT : CloudNetworkError, un seul COMMIT reçu
def test_read_inside_transaction_not_retried()
def test_expired_stream_fails_transaction():  # expire_baton : CloudNetworkError, puis rollback() sans erreur
def test_auth_error_hides_token():     # CloudAuthError ; "secret-token" absent de str(e), repr(conn), caplog (niveau DEBUG)
def test_sql_error_is_not_operational()  # SELECT * FROM absente : DatabaseError, pas OperationalError
def test_prefetch_consumed():          # prefetch([a, b]) puis execute(a), execute(b) : sends == 1 ; re-execute(a) : sends == 2
def test_write_drops_prefetched()
def test_concurrent_reads_do_not_block():  # delay_s=0.3, 5 fils : total < 0.9 s
```

- [ ] **Step 2:** `python -m pytest tests/storage/test_hrana.py -v` → FAIL (module absent).
- [ ] **Step 3:** Implémenter `coach/storage/hrana.py`.
- [ ] **Step 4:** Même commande → tout PASS.
- [ ] **Step 5:** Commit `feat(storage): pilote HTTP Hrana pour les bases distantes`.

### Task 2: Brancher le dialecte, retirer `libsql`

**Files:**
- Modify: `coach/storage/libsql_dialect.py`, `coach/storage/cloud_errors.py`, `pyproject.toml`, `uv.lock`, `packaging/windows/coachcloclo.spec`, `README.md` (si le paquet y est cité)
- Test: `tests/storage/test_libsql_dialect.py`, `test_lock.py`, `test_transfer.py`, `test_source.py`, `test_turso_live.py` (commentaires), `tests/plan/test_repo.py:529`, `tests/api/test_app.py:1844`

**Interfaces:**
- Consumes: tâche 1.
- Produces: `remote_engine(url: str, token: str, *, transport: httpx.BaseTransport | None = None) -> Engine` ; URL SQLAlchemy `sqlite+libsql://…` inchangée ; `NullPool`, sans `pool_pre_ping` ni `pool_recycle` ; client HTTP partagé du moteur, fermé à l'événement `engine_disposed`.
- `is_cloud_failure` : `CloudUnreachable`, `sqlalchemy.exc.OperationalError` (inchangé), et erreurs brutes `CloudNetworkError`/`CloudAuthError`. `is_auth_failure` : `CloudAuthError`, brute ou dans `exc.orig`. Le décodage des messages « Hrana: » disparaît.

- [ ] **Step 1: Adapter les tests**
  - Les fixtures `sqlite+libsql:///fichier` deviennent `remote_engine("libsql://x.turso.io", "tok", transport=FakeHrana(tmp_path / "c.db").transport)` ; les assertions de verrou, copie, migrations et `IntegrityError` restent.
  - `test_remote_engine_options` : `NullPool`, `_pre_ping` faux. `test_remote_pool_is_queue_pool` et `test_insecure_http` supprimés (https seulement).
  - `test_libsql_network_error_returns_503` lève `CloudNetworkError`.
  - Nouveaux :
```python
def test_repo_read_is_one_send():     # Repo(engine).latest_snapshot() : sends augmente de 1
def test_unique_violation_wrapped():  # sqlalchemy.exc.IntegrityError
def test_store_summaries_survives_duplicate()  # insertion concurrente simulée : pas d'exception, 0 ajout
def test_gpx_blob_roundtrip()         # 3 Mo, octets identiques
def test_network_and_auth_messages():  # PROBE_UNREACHABLE_MSG et BAD_TOKEN_MSG via TursoSource.engine()
def test_dispose_closes_client()
def test_slow_read_does_not_block_version():  # delay_s=0.5 sur /api/plan dans un fil ; /api/version < 0.2 s
```
- [ ] **Step 2:** `python -m pytest tests/storage tests/plan/test_repo.py tests/api -q` → FAIL.
- [ ] **Step 3:** Implémenter ; retirer `libsql` de `pyproject.toml` et de `hiddenimports` (ajouter `coach.storage.hrana`) ; `uv lock`. `uv` n'est pas dans le PATH du poste : `python -m pip install uv` dans un venv temporaire du scratchpad.
- [ ] **Step 4:** `python -m pytest -q` → PASS ; `git grep -n "import libsql"` → aucun résultat.
- [ ] **Step 5:** Commit `feat(storage): base cloud via le pilote HTTP, paquet libsql retiré`.

### Task 3: Lectures groupées dans `Repo`

**Files:** Modify `coach/plan/repo.py` ; Test `tests/plan/test_repo.py`

**Interfaces:**
- Produces: `Repo.read_batch(*statements: Select) -> list[list]` : entités ou scalaires (une colonne), dans l'ordre ; résultat identique à une exécution séparée.
- Produces: fonctions de module `active_cycle_stmt()`, `upcoming_goals_stmt()`, `past_goals_stmt()`, `recent_done_goals_stmt(today: date, days: int = 14)`, `last_done_cycle_stmt(before: date)`, `sessions_stmt(cycle_id: int, week_index: int | None = None)`, `open_injury_stmt(cycle_id: int)`, `pending_proposal_stmt()`, `count_activities_stmt()`, `state_stmt(key: str)` (entité `AppState`) ; les méthodes existantes les réutilisent.

Mécanisme : si la connexion brute a `prefetch`, compiler chaque requête avec `literal_binds=True`, précharger, puis exécuter le même texte (entités via `select(Model).from_statement(text(sql))`, `:` échappés). Sinon exécuter les requêtes une à une. `expire_on_commit=False`. N'accepte que des valeurs produites par l'appli (entiers, dates, constantes).

- [ ] **Step 1: Tests** paramétrés SQLite / `FakeHrana` :
```python
def test_read_batch_matches_single_reads():  # chaque *_stmt, types date et bool compris
def test_read_batch_is_one_send():           # FakeHrana : 5 requêtes, sends += 1
def test_read_batch_empty_results():         # [] et 0
def test_read_batch_value_with_colon_and_quote():  # state_stmt("a:b'c")
```
- [ ] **Step 2:** `python -m pytest tests/plan/test_repo.py -q` → FAIL. **Step 3:** Implémenter. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(repo): lectures groupées en un envoi`.

### Task 4: `/status`, `/plan`, `/activities` et tours

**Files:** Modify `coach/api/app.py`, `coach/plan/repo.py`, `coach/services/laps.py`, `coach/services/history.py` ; Test `tests/api/test_app.py`, `tests/services/test_laps.py`

**Interfaces:**
- Consumes: `read_batch` et les `*_stmt`.
- Produces: `Repo.activities_between(start: date, end: date) -> list[Activity]` et `Repo.activities_missing_laps() -> list[Activity]` (rattachées, sans ligne `ActivityLaps`), tous deux avec `defer(Activity.raw_json)` ; `parse_state(raw: dict | None) -> HistoryState` dans `history.py`. Réponses JSON inchangées.

- [ ] **Step 1: Tests**
```python
def test_plan_at_most_3_sends()      # base FakeHrana, cycle + objectifs + horizon + arrêt ouvert
def test_status_at_most_3_sends()    # cycle actif, puis sans cycle (last_cycle rempli)
def test_activities_at_most_3_sends()
def test_cloud_and_local_json_identical()  # /plan, /status, /activities?week=1 : mêmes données des deux côtés
def test_activities_do_not_load_raw_json()  # "raw_json" absent des SQL reçus
def test_missing_laps_single_query()  # 3 activités rattachées dont 1 avec tours : 2 renvoyées, sends == 1
```
- [ ] **Step 2:** `python -m pytest tests/api tests/services/test_laps.py -q` → FAIL.
- [ ] **Step 3:** Implémenter. `_prox`, objectifs du cycle et horizon se déduisent de la liste `upcoming_goals` déjà lue ; `has_activities` de `count_activities`. `fetch_missing_laps` garde sa limite de 20 et l'arrêt sur limite Garmin.
- [ ] **Step 4:** `python -m pytest -q` → PASS.
- [ ] **Step 5:** Commit `perf(api): plan, statut et activités en quelques envois`.

### Task 5: Mesure sur la base réelle (lecture seule)

**Files:** aucun fichier du dépôt.

- [ ] **Step 1:** Demander à l'utilisateur l'accord avant de lancer une instance du worktree sur sa base : l'ouverture exécute `prepare_engine`, qui réécrit `schema_version` (même valeur). Sans accord : mesurer avec `remote_engine` et des lectures `Repo` seulement.
- [ ] **Step 2:** Mesurer `plan`, `status`, `zones`, `cycle/events`, `activities` (5 fois, connexion chaude), et trois `plan` simultanés. Attendu : < 0,3 s chacun, sauf `status`, qui construit encore le client Garmin jusqu'à la tâche 6. Noter avant/après dans le compte rendu, objectif manqué compris.

---

## Lot 2 : démarrage et affichage

### Task 6: État Garmin, phase de synchro, synchro sans écriture inutile

**Files:** Modify `coach/api/app.py`, `coach/services/sync.py`, `context.py`, `rest_hr.py`, `history.py` ; Test `tests/api/test_app.py`, `tests/services/test_sync.py`, `test_rest_hr.py`, `test_history.py`, `tests/mobile_fixtures.py` si `DESKTOP_STATUS_KEYS` change

**Interfaces:**
- Produces: `GET /api/garmin/state` → `{"garmin": "ok" | "auth_required" | "unavailable"}` ; `GET /api/sync/phase` → `{"phase": "garmin" | "claude" | null}` (ajouté à `NO_DB_PATHS`) ; `/api/status` sans clé `garmin` (base indisponible comprise).
- Produces: `sync(repo, garmin, llm, *, now, on_phase: Callable[[str], None] = lambda _: None)` ; `SyncResult.changed: bool`. `refresh_records` → `Literal["failed", "unchanged", "replaced"]` (appelants adaptés).
- `changed` vrai si : activité ajoutée, séance manquée, proposition, renvoi à la montre, tours récupérés, instantané ou records modifiés, objectif ou cycle clos, retrait Garmin repris.

- [ ] **Step 1: Tests**
```python
def test_status_does_not_build_garmin()   # garmin="down" : status 200, fabrique non appelée, "garmin" absent
def test_garmin_state_route()             # ok, auth_required, unavailable
def test_phase_without_db()               # base indisponible : 200, phase null
def test_sync_phases_in_order()           # avec séance à analyser : ["garmin", "claude"] ; sans : ["garmin"]
def test_phase_reset_after_error()        # Garmin lève : phase null ensuite
def test_second_sync_writes_only_state_and_lock():
    # 2 synchros identiques le même jour ; tables écrites à la 2e (before_cursor_execute) == {"appstate", "garminlock"}
    # clé AppState écrite : "sync" seule ; result.changed is False ; LLM non appelé
def test_changed_hr_rest_adds_snapshot()  # changed True, nouvelle ligne
def test_new_day_adds_snapshot()
def test_changed_records_replaced() ; def test_nights_not_rewritten_when_equal()
def test_new_activity_sets_changed() ; def test_closed_goal_sets_changed()
```
- [ ] **Step 2:** `python -m pytest tests/api tests/services -q` → FAIL.
- [ ] **Step 3:** Implémenter. Instantané « identique » : mêmes champs que `latest_snapshot()`, hors `id`, date comprise ; l'instantané existant est alors renvoyé. La phase vit dans `app.state`, remise à `None` dans le `finally` de `post_sync`. `on_phase("claude")` juste avant `_propose`.
- [ ] **Step 4:** `python -m pytest -q` → PASS. **Step 5:** Commit `feat(sync): phases, état Garmin séparé, rien d'écrit sans changement`.

### Task 7: Démarrage sans attendre Garmin

**Files:** Modify `web/src/App.svelte`, `web/src/lib/api.ts`, `web/src/components/Sidebar.svelte`, `web/src/routes/Setup.svelte` ; Test `web/src/App.test.ts`, tests de ces composants

**Interfaces:**
- Produces: `type GarminState = "checking" | "ok" | "auth_required" | "unavailable"` ; `api.garminState(): Promise<Exclude<GarminState, "checking">>` ; `api.syncPhase(): Promise<"garmin" | "claude" | null>` ; `Status.garmin` supprimé ; prop `garmin: GarminState` sur `Sidebar` ; `SyncResult.changed: boolean`. Sidebar en `checking` : « Vérification de Garmin… », sans bouton ni lien.

Règles :
- `start()` affiche dès que `status` répond. S'il n'y a ni cycle, ni objectif, ni activité, il attend `setupStatus` et `garminState` avant de choisir la page (comme aujourd'hui).
- Sinon accueil immédiat ; ensuite renvoi vers `#/welcome` (installation incomplète) ou `#/setup` (`auth_required`) seulement si aucune route n'était demandée et que le hash est encore celui de l'accueil automatique.
- Un échec de `garminState` vaut `unavailable`. La synchro part quand l'état est `ok`, après le premier chargement du contenu (`requestAnimationFrame` suivi de la fin des lectures de page en cours, 5 s au plus).
- Pendant la synchro, sondage de `syncPhase` chaque seconde (arrêté à la fin) ; bandeau Claude en phase `claude` seulement. `version++` seulement si `r.changed` ; `refresh()` toujours, car il révèle un import lancé.
- Après connexion Garmin réussie, l'état est relu avant de synchroniser.

- [ ] **Step 1: Tests** (adapter les tests existants qui attendent les bandeaux)
```ts
test("affiche la semaine avant la réponse de Garmin")
test("aucun bandeau pendant la phase garmin")
test("bandeau Claude en phase claude seulement, retiré à la fin")
test("le sondage de phase s'arrête après la synchro, réussie ou non")
test("synchro sans changement : /api/plan non relu")
test("garmin auth_required sans route demandée : renvoi vers #/setup")
test("garmin auth_required après navigation : pas de renvoi")
test("route demandée au lancement : pas de renvoi")
test("premier lancement : attend l'installation puis #/welcome")
test("garminState en échec : unavailable, pages consultables")
```
- [ ] **Step 2:** `npm test` → FAIL. **Step 3:** Implémenter. **Step 4:** `npm test` et `npm run build` → OK.
- [ ] **Step 5:** Commit `feat(web): démarrage immédiat et synchro discrète`.

### Task 8: Cache mémoire et lectures parallèles

**Files:** Create `web/src/lib/cache.ts`, `web/src/lib/cache.test.ts` ; Modify `web/src/lib/api.ts`, `Week.svelte`, `Program.svelte`, `Stats.svelte`, `Goal.svelte`, `Proposal.svelte`, `EventList.svelte`, `StorageSettings.svelte`, `App.svelte` ; Test leurs tests

**Interfaces:**
- Produces:
```ts
export function load<T>(key: string, fetcher: () => Promise<T>, apply: (value: T) => void): Promise<void>;
export function noteWrite(): void;   // appelé par request() à la fin de toute méthode autre que GET, réussie ou non
export function clearCache(): void;
export function pendingLoads(): Promise<void>; // fin des lectures en cours (utilisé par App, tâche 7)
```
- `load` : applique la valeur en cache tout de suite, relit, applique la nouvelle. Deux `load` de même clé en vol partagent la requête. Une écriture pendant la lecture : réponse ignorée et lecture relancée. `clearCache` pendant la lecture : réponse ignorée, promesse résolue sans `apply`. Échec : promesse rejetée, cache intact.
- Clés : `plan`, `events`, `activities:{semaine}`, `stats`, `records`, `proposal`. Les pages vérifient aussi que la semaine affichée est toujours celle de la réponse.
- `clearCache` : bascule, désactivation ou effacement du stockage, `connected`, `cleared`, saisie du PIN, passage en erreur de stockage.

- [ ] **Step 1: Tests**
```ts
test("valeur en cache appliquée avant la relecture")
test("deux lectures simultanées : une requête")
test("une écriture pendant la lecture : ancienne réponse ignorée, relue")
test("clearCache pendant la lecture : rien d'appliqué ni gardé")
test("échec : ancienne valeur gardée, erreur remontée")
test("pendingLoads se résout après la dernière lecture, même en échec")
// pages
test("Week : retour sur la page, plan affiché sans attendre")
test("Week : /plan et /cycle/events partent ensemble")
test("Week : une seule lecture /activities par affichage")
test("Week : changement rapide de semaine, la réponse tardive ne s'affiche pas")
test("bascule de stockage : les anciennes données ne réapparaissent pas")
test("lecture seule : même comportement")
```
- [ ] **Step 2:** `npm test` → FAIL. **Step 3:** Implémenter ; dans `Week`, l'indice de semaine est un `$derived` numérique (l'effet ne se relance pas à chaque nouveau plan, mais suit `version`), et `events` est préchargé avec le plan.
- [ ] **Step 4:** `npm test`, `npm run build`, `npm run build:mobile` → OK.
- [ ] **Step 5:** Commit `feat(web): pages déjà vues affichées tout de suite`.

### Task 9: Vérification finale

**Files:** Modify `README.md` (stockage cloud : accès HTTP, données gardées en mémoire le temps de la session), si concerné.

- [ ] **Step 1:** `python -m pytest -q`, `npm test`, `npm run build`, `npm run build:mobile` → tout vert.
- [ ] **Step 2:** Avec l'accord de l'utilisateur (tâche 5), lancer l'appli du worktree sur un autre port. Attention : la synchro de démarrage écrit dans la base et peut appeler Claude ou la montre. Sans accord : base locale de test. Vérifier dans le navigateur : semaine < 1 s, aucun bandeau sans changement, retour de page immédiat.
- [ ] **Step 3:** Reporter les mesures avant/après dans le compte rendu. Construire l'installateur si `pyinstaller` est disponible ; sinon signaler que l'exécutable n'est pas vérifié.
- [ ] **Step 4:** Commit `docs: chargement rapide` s'il y a eu un changement.
