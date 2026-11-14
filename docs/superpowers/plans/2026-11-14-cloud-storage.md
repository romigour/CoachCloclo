# Stockage cloud optionnel : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** option « Stocker mes données dans le cloud » qui fait d'une base Turso de l'utilisateur
l'unique lieu de stockage des données partagées, avec bascule local ↔ cloud dans les deux sens.

**Architecture :** toutes les données partagées passent dans la base, en mode local aussi : GPX,
état d'import d'historique, état de synchro, verrou Garmin, version de schéma. Une « source de
données » (`LocalSource` ou `TursoSource`) fournit le moteur SQLAlchemy. Le `Repo` et les services
ignorent laquelle est utilisée. La bascule copie la base table par table d'une source à l'autre,
la vérifie, puis remplace `app.state.repo` à chaud. Un verrou en base, posé autour de toute
écriture Garmin, empêche deux PC d'écrire sur la montre en même temps.

**Tech Stack :** Python 3.12, FastAPI, SQLModel/SQLAlchemy 2, `sqlalchemy-libsql` (dialecte
`sqlite+libsql`, pilote `libsql-experimental`), Svelte + Vitest, PyInstaller.

**Spec :** `docs/superpowers/specs/2026-11-14-cloud-storage-design.md`

## Global Constraints

- Par défaut `storage_mode = "local"` : une installation existante ou neuve fonctionne comme avant, sans action.
- Restent locaux et ne vont jamais en base : tokens Garmin, `llm_mode`, `anthropic_api_key`,
  `anthropic_model`, `pin_hash`, `lan_enabled`, logs, `desktop.json`, `claude-cwd`, `ca-bundle.pem`,
  `storage_mode`, `turso_url`, `turso_token`.
- Le jeton Turso n'est jamais renvoyé par l'API (seulement `has_turso_token`) ni écrit dans les logs.
- Aucune donnée locale supprimée avant qu'une copie soit vérifiée (nombre de lignes identique par table) et le marqueur de fin écrit.
- Désactiver le cloud n'efface jamais la base cloud ; seul « Effacer mes données du cloud » la vide.
- Verrou pris par un autre PC : synchro, import ou export manuel → HTTP 409, code `garmin_locked`,
  message exact « Synchronisation en cours sur un autre PC ». Action métier → la modification en
  base passe, et les séances restent en `sync_error` avec ce message.
- Base dont le schéma est plus récent que l'app → code `schema_too_new`, message exact
  « Mets à jour CoachCloclo sur ce PC ». Base cloud injoignable → HTTP 503, code `cloud_unreachable`.
- Pages Stats et Plan chargées en moins de 2 s en mode cloud, historique complet compris.
- Textes de l'interface en français, comme le reste de l'app.

## Review Focus

1. **Import d'historique en cours sur le PC 1 quand le PC 2 démarre** : le PC 2 ne doit ni le marquer « Import interrompu », ni lancer un second import (tests dans la tâche 6).
2. **Copie vers le cloud coupée au milieu** (réseau perdu) : on reste en local, `coach.db` intact, et la base cloud sans marqueur compte comme vide au prochain essai (tests dans la tâche 5).
3. **Jeton Turso invalide ou URL fausse à l'activation** : message clair, mode inchangé, aucun fichier supprimé (test dans la tâche 7).
4. **PC à l'ancienne version sur une base cloud migrée** : refus avec `schema_too_new`, aucune écriture (tests dans les tâches 2 et 7).
5. **Base cloud injoignable en cours d'usage** : 503 `cloud_unreachable` sur l'API et bandeau dans l'interface, pas une erreur 500 (tests dans les tâches 7 et 8).

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `coach/storage/__init__.py` | paquet |
| `coach/storage/source.py` | `DataSource`, `LocalSource`, `TursoSource`, `source_from_settings` |
| `coach/storage/transfer.py` | `is_empty`, `copy_all`, `verify_copy`, `wipe`, marqueur de fin |
| `coach/storage/lock.py` | verrou Garmin en base, `LockedGarmin`, `machine_id` |
| `coach/storage/switch.py` | `enable_cloud`, `disable_cloud`, `wipe_cloud` |
| `coach/storage/legacy.py` | reprise unique de `gpx/`, `history.json`, `last_sync_at`/`proposal_due` |
| `coach/plan/models.py` | + `AppState`, `GpxFile`, `GarminLock` |
| `coach/plan/repo.py` | + accès à ces tables, `SCHEMA_VERSION`, `SchemaTooNew` |
| `coach/config.py` | + `storage_mode`, `turso_url`, `turso_token` ; − `last_sync_at`, `proposal_due` (lus seulement par la reprise) |
| `coach/services/history.py`, `sync.py`, `adjust.py`, `goals.py`, `race_strategy.py` | état et GPX lus en base |
| `coach/api/app.py` | source au démarrage, routes `/storage*`, erreurs 409/503, repo remplaçable à chaud |
| `coach/doctor.py` | vérification de la base cloud |
| `web/src/components/StorageSettings.svelte` (+ test), `web/src/lib/api.ts`, `web/src/routes/Setup.svelte`, `web/src/components/ErrorBanner.svelte` | interface |
| `packaging/windows/coachcloclo.spec`, `pyproject.toml`, `README.md` | dépendance, empaquetage, guide Turso |

---

### Task 1 : essai Turso (point d'arrêt)

**Files :**
- Modify : `pyproject.toml`, `uv.lock` (dépendance `sqlalchemy-libsql`)
- Create : `tests/storage/__init__.py`, `tests/storage/test_turso_live.py`

**Interfaces :**
- Produces : l'URL SQLAlchemy validée pour Turso, notée en tête de `test_turso_live.py` et réutilisée par la tâche 4. Forme attendue : `sqlite+libsql://<hôte>?secure=true` avec `connect_args={"auth_token": <jeton>}`.

- [ ] **Step 1 :** `uv add sqlalchemy-libsql`. Vérifier que `libsql-experimental` s'installe en wheel sous Windows (`uv sync` sans compilation Rust).
- [ ] **Step 2 :** écrire `test_turso_live.py` (marqué `live`, lit `COACH_TURSO_URL` et `COACH_TURSO_TOKEN`, et passe le test s'ils sont absents) :
  - `test_turso_migrations` : `make_engine` sur la base distante crée les tables, puis un second appel rejoue `_migrate` sans erreur (`PRAGMA table_info` et `ALTER TABLE` passent) ;
  - `test_turso_transaction_rollback` : une exception dans `repo.transaction()` n'écrit rien ;
  - `test_turso_stats_latency` : insérer 1 500 `Activity` (fabrique `make_activity`), puis vérifier que `repo.all_activities()` et `repo.races()` prennent ensemble moins de 2 s.
- [ ] **Step 3 :** depuis le **PC du travail**, avec une base Turso de test, lancer `uv run pytest -m live tests/storage -v`. Attendu : 3 tests PASS.
- [ ] **Step 4 : point d'arrêt.** Si le réseau bloque, si le pilote ne passe pas les migrations ou les transactions, ou si la latence dépasse 2 s même après regroupement des requêtes : **arrêter et faire un compte rendu à l'utilisateur** (pistes : réplique embarquée, autre hébergeur compatible SQLite). Ne pas commencer la tâche 2.
- [ ] **Step 5 :** commit `chore: dépendance sqlalchemy-libsql et essai réel Turso`.

### Task 2 : tables d'état, de GPX et de verrou, version de schéma

**Files :**
- Modify : `coach/plan/models.py`, `coach/plan/repo.py`
- Test : `tests/plan/test_repo.py`

**Interfaces :**
- Produces (dans `coach.plan.models`) :
  - `AppState(key: str PK, value_json: str)` ;
  - `GpxFile(goal_id: int PK, data: bytes)` ;
  - `GarminLock(id: int PK = 1, holder: str, expires_at: datetime)`.
- Produces (dans `coach.plan.repo`) :
  - `SCHEMA_VERSION = 1` et `class SchemaTooNew(Exception)` ;
  - `Repo.get_state(key: str) -> dict | None` et `Repo.set_state(key: str, value: dict) -> None` ;
  - `Repo.gpx(goal_id: int) -> bytes | None` et `Repo.save_gpx(db: DbSession, goal_id: int, data: bytes) -> None`, à appeler dans la transaction de l'objectif.
- Clés `AppState` réservées : `"schema_version"` (`{"v": int}`), `"history"`, `"sync"`, `"copy_complete"`.

- [ ] **Step 1 : tests.**
  - `test_state_roundtrip` : `set_state("sync", {"a": 1})` puis `get_state("sync") == {"a": 1}` ; `get_state("x") is None`.
  - `test_gpx_roundtrip`.
  - `test_make_engine_writes_schema_version` : après `make_engine`, `get_state("schema_version") == {"v": SCHEMA_VERSION}`.
  - `test_make_engine_refuses_newer_schema` : base avec `{"v": SCHEMA_VERSION + 1}` → `make_engine` lève `SchemaTooNew` et la valeur reste inchangée.
- [ ] **Step 2 :** `uv run pytest tests/plan/test_repo.py -v`. Attendu : FAIL (noms absents).
- [ ] **Step 3 :** implémenter. À la fin de `make_engine` : lire la version ; plus grande que `SCHEMA_VERSION` → lever `SchemaTooNew` **avant** `create_all` et `_migrate` ; sinon écrire `SCHEMA_VERSION`. Chaque changement de schéma futur incrémente `SCHEMA_VERSION` (commentaire à côté de la constante).
- [ ] **Step 4 :** relancer les tests. Attendu : PASS, suite complète verte (`uv run pytest`).
- [ ] **Step 5 :** commit `feat(storage): tables d'état, GPX et verrou, version de schéma`.

### Task 3 : état partagé et GPX lus en base, reprise des fichiers existants

**Files :**
- Modify : `coach/services/history.py`, `coach/services/sync.py`, `coach/services/adjust.py:154`, `coach/services/goals.py:340-353`, `coach/services/race_strategy.py:46-50,128`, `coach/config.py`, `coach/api/app.py` (appels à `load_state`/`recover_orphan`)
- Create : `coach/storage/__init__.py`, `coach/storage/legacy.py`
- Test : `tests/services/test_history.py`, `tests/services/test_sync.py`, `tests/storage/test_legacy.py`, tests GPX existants des services goals et race_strategy

**Interfaces :**
- Consumes : `Repo.get_state` / `set_state` / `gpx` / `save_gpx` (tâche 2).
- Produces :
  - `load_state(repo: Repo) -> HistoryState` et `save_state(repo: Repo, s: HistoryState)` (clé `"history"`) ;
  - `class SyncState(BaseModel): last_sync_at: datetime | None = None; proposal_due: bool = False`, plus `load_sync_state(repo) -> SyncState` et `save_sync_state(repo, s)` dans `coach/services/sync.py` (clé `"sync"`) ;
  - `import_legacy_files(repo: Repo, home: Path) -> None` dans `coach/storage/legacy.py`.
- `Goal.gpx_path` n'est plus écrit. On garde la colonne, devenue inutile. Un objectif « a un GPX » si et seulement si `repo.gpx(goal.id)` n'est pas `None`.

- [ ] **Step 1 : tests.**
  - Adapter les tests existants de `history`, `sync` et `adjust` aux signatures qui prennent `repo`.
  - `test_goal_gpx_stored_in_db` : créer un objectif avec GPX → `repo.gpx(goal.id)` vaut les octets, et aucun fichier n'est créé sous `coach_home/gpx`.
  - `test_race_strategy_reads_gpx_from_db`.
  - `test_import_legacy_files` : `home` contient `history.json` (`status="done"`), un `settings.json` avec `last_sync_at` et `proposal_due=true`, et `gpx/7.gpx` pour un objectif 7 dont `gpx_path` pointe dessus. Après l'import, ces valeurs se retrouvent en base. Un 2ᵉ appel ne change rien, même si les fichiers ont été modifiés entre-temps (garde : `get_state("history")` déjà présent ⇒ ne rien faire pour l'historique, idem pour `"sync"` et pour chaque GPX déjà en base).
  - `test_import_legacy_ignores_missing_gpx_file`.
- [ ] **Step 2 :** lancer les tests. Attendu : FAIL.
- [ ] **Step 3 :** implémenter.
  - `Settings` garde `last_sync_at` et `proposal_due` en champs facultatifs, lus par `import_legacy_files` puis ignorés (ne plus les écrire).
  - `create_app` appelle `import_legacy_files(repo, data_dir())` uniquement si `repo` n'est pas injecté et que le mode est local.
  - `recover_orphan(repo)` reste tel quel ici ; le verrou arrive à la tâche 6.
- [ ] **Step 4 :** `uv run pytest`. Attendu : tout PASS.
- [ ] **Step 5 :** commit `feat(storage): état d'import, état de synchro et GPX stockés en base`.

### Task 4 : source de données interchangeable

**Files :**
- Create : `coach/storage/source.py`
- Modify : `coach/config.py`, `coach/api/app.py:308`, `coach/cli.py` et `coach/desktop/server.py` (là où `create_app` est appelé, si la source doit y être choisie)
- Test : `tests/storage/test_source.py`

**Interfaces :**
- Produces :
  - `class DataSource(Protocol)` : `kind: str` et `def engine(self) -> Engine` (applique `make_engine`, donc les migrations et le contrôle de version) ;
  - `LocalSource(path: Path)` et `TursoSource(url: str, token: str)` ;
  - `source_from_settings(s: Settings) -> DataSource` ;
  - `Settings` reçoit : `storage_mode: Literal["local", "turso"] = "local"`, `turso_url: str | None = None` et `turso_token: str | None = None`.
- Pour ajouter un futur hébergeur : nouvelle classe `XxxSource` + une valeur de `storage_mode`. Rien d'autre ne change.

- [ ] **Step 1 : tests.**
  - `test_default_source_is_local` : `Settings()` donne une `LocalSource(db_path())`.
  - `test_turso_source_from_settings` : `storage_mode="turso"` donne une `TursoSource` avec l'URL et le jeton.
  - `test_turso_source_engine_url` : URL `libsql://x.turso.io` → l'URL du moteur commence par `sqlite+libsql://x.turso.io` et le jeton passe dans `connect_args` (lire `engine.url`, sans réseau, en remplaçant `make_engine` par une fonction factice).
  - `test_turso_without_token_raises` : `ValueError`.
- [ ] **Step 2 :** lancer. Attendu : FAIL.
- [ ] **Step 3 :** implémenter. `TursoSource` accepte `libsql://` ou `https://` en entrée et normalise vers la forme validée à la tâche 1. `create_app` utilise `source_from_settings(load_settings()).engine()` quand `repo` n'est pas fourni.
- [ ] **Step 4 :** `uv run pytest`. Attendu : PASS.
- [ ] **Step 5 :** commit `feat(storage): source de données locale ou Turso`.

### Task 5 : copie, vérification et effacement d'une base

**Files :**
- Create : `coach/storage/transfer.py`
- Test : `tests/storage/test_transfer.py`

**Interfaces :**
- Produces :
  - `is_empty(engine: Engine) -> bool` : vrai si aucune table n'a de ligne **ou** si `"copy_complete"` est absent, en ignorant les lignes `schema_version` et `copy_complete` d'`AppState` ;
  - `copy_all(src: Engine, dst: Engine) -> None` : vide `dst`, puis copie toutes les tables de `SQLModel.metadata` dans l'ordre des dépendances (`metadata.sorted_tables`), et efface `copy_complete` côté `dst` au début ;
  - `verify_copy(src: Engine, dst: Engine) -> None` : lève `CopyMismatch(table)` si le nombre de lignes d'une table diffère, puis écrit `copy_complete` dans `dst` ;
  - `wipe(engine: Engine) -> None` : supprime toutes les lignes des tables applicatives, `schema_version` compris (l'app la réécrit à la prochaine ouverture).

- [ ] **Step 1 : tests**, avec deux bases SQLite temporaires.
  - `test_copy_and_verify_roundtrip` : une base remplie (cycle, séances, activités, GPX, état) est copiée, `verify_copy` passe, et `is_empty(dst)` est faux.
  - `test_copy_replaces_existing_rows` : `dst` contenait déjà d'autres lignes, il ne reste que celles de `src`.
  - `test_interrupted_copy_counts_as_empty` (Review Focus 2) : `copy_all` échoue au milieu (insertion d'une table remplacée par une fonction qui lève) → `is_empty(dst)` est vrai.
  - `test_verify_detects_mismatch` : une ligne supprimée dans `dst` → `CopyMismatch`.
  - `test_wipe_empties` : `is_empty` est vrai après `wipe`.
- [ ] **Step 2 :** lancer. Attendu : FAIL.
- [ ] **Step 3 :** implémenter avec SQLAlchemy Core (`select(table)` / `insert(table)` par lots de 500), sans ORM, pour copier aussi les colonnes héritées.
- [ ] **Step 4 :** lancer. Attendu : PASS.
- [ ] **Step 5 :** commit `feat(storage): copie vérifiée entre bases`.

### Task 6 : verrou Garmin entre PC

**Files :**
- Create : `coach/storage/lock.py`
- Modify : `coach/services/history.py` (`HistoryRunner`, `import_history`, `recover_orphan`), `coach/api/app.py` (`garmin_factory` enveloppé, `POST /sync`, `POST /history/import`, export manuel)
- Test : `tests/storage/test_lock.py`, `tests/services/test_history.py`, `tests/api/test_app.py`

**Interfaces :**
- Produces :
  - `machine_id() -> str` : `<nom d'hôte>-<8 caractères hexadécimaux aléatoires>`, créé une fois puis stocké dans `data_dir()/machine_id` (local) ;
  - `LOCK_MSG = "Synchronisation en cours sur un autre PC"` et `class GarminLocked(GarminUnavailable)`, dont le message vaut `LOCK_MSG` ;
  - `try_acquire(repo, holder: str, ttl: timedelta, now: datetime) -> bool` : l'accorde si le verrou est libre, expiré ou déjà détenu par `holder` ; prolonge `expires_at` ; l'opération est atomique (un seul `UPDATE … WHERE holder = :h OR expires_at < :now`, ou un `INSERT` si la ligne est absente) ;
  - `release(repo, holder)` : ne libère que si `holder` détient le verrou ;
  - `held_elsewhere(repo, holder, now) -> bool` ;
  - `@contextmanager garmin_lock(repo, holder, ttl)` : lève `GarminLocked` si refusé, libère à la sortie ;
  - `LockedGarmin(inner: GarminPort, repo_getter: Callable[[], Repo], holder: str)` : les méthodes d'écriture (`upload_workout`, `schedule`, `reschedule`, `unschedule`, `delete_workout`) appellent `try_acquire(ttl=WRITE_TTL)` et lèvent `GarminLocked` en cas de refus ; les lectures sont déléguées telles quelles.
- Durées : `WRITE_TTL = 2 min` (prolongée à chaque écriture, sans libération explicite), `SYNC_TTL = 15 min` pour `POST /sync`, `IMPORT_TTL = 5 min` pour l'import, prolongée à chaque page.
- `GarminLocked` hérite de `GarminUnavailable` : les chemins d'export existants (`_sync`, `sync_marked`) laissent donc déjà la séance en `sync_error` avec ce message, sans autre changement. Elle ne fait pas partie de `_EARLY_ERRORS`.

- [ ] **Step 1 : tests.**
  - `test_lock_free_then_held` : A l'obtient, B est refusé, puis B l'obtient après expiration.
  - `test_lock_reentrant_and_release_by_owner_only`.
  - `test_locked_garmin_write_raises_when_held_elsewhere` : les lectures passent quand même.
  - `test_business_export_with_lock_held_leaves_sync_error` : avec un cycle accepté et le verrou détenu par « autre-pc », accepter le plan (via l'API) répond 200 ; les séances sont en `sync_error` et leur `sync_error` contient `LOCK_MSG`.
  - `test_sync_endpoint_409_when_locked` : `POST /api/sync` renvoie 409, `{"code": "garmin_locked", "message": LOCK_MSG}`. Même chose pour `POST /api/history/import` et pour l'export manuel d'une séance.
  - `test_recover_orphan_keeps_running_import_of_other_pc` (Review Focus 1) : état `running` et verrou détenu ailleurs et non expiré → l'état reste `running`, et `HistoryRunner.start()` ne lance pas d'import (renvoie `False`, l'API répond 409).
  - `test_recover_orphan_marks_interrupted_when_lock_expired`.
- [ ] **Step 2 :** lancer. Attendu : FAIL.
- [ ] **Step 3 :** implémenter.
  - Dans `create_app` : `garmin_factory` est enveloppé par `LockedGarmin`, avec `repo_getter=lambda: app.state.repo` pour suivre la bascule à chaud.
  - `POST /sync` s'exécute dans `garmin_lock(SYNC_TTL)` ; `import_history` dans `garmin_lock(IMPORT_TTL)`, avec un `try_acquire` à chaque page.
  - Enregistrer `GarminLocked` → 409 `garmin_locked` dans `_register_errors`, **avant** `GarminUnavailable`.
- [ ] **Step 4 :** `uv run pytest`. Attendu : PASS.
- [ ] **Step 5 :** commit `feat(storage): verrou Garmin partagé entre PC`.

### Task 7 : activer, désactiver, effacer ; routes et erreurs

**Files :**
- Create : `coach/storage/switch.py`
- Modify : `coach/api/app.py`
- Test : `tests/storage/test_switch.py`, `tests/api/test_app.py`

**Interfaces :**
- Consumes : `DataSource` (tâche 4), `is_empty`, `copy_all`, `verify_copy`, `wipe` (tâche 5), `SchemaTooNew` (tâche 2).
- Produces (dans `coach/storage/switch.py`, toutes ces fonctions reçoivent les sources pour être testables) :
  - `class CloudStatus(BaseModel): mode: str; turso_url: str | None; has_turso_token: bool` ;
  - `probe(source: DataSource) -> Engine` : ouvre la base et fait une lecture et une écriture dans `AppState` (clé `"probe"`) ; lève `CloudUnreachable(message)` en cas d'échec réseau ou d'authentification, et laisse passer `SchemaTooNew` ;
  - `enable_cloud(current: Engine, cloud: DataSource, *, replace_local: bool) -> Engine | NeedsConfirmation` :
    - cloud vide (au sens de `is_empty`) : `copy_all(current, cloud_engine)` puis `verify_copy`, et renvoie le moteur cloud ;
    - cloud non vide et `replace_local` faux : renvoie `NeedsConfirmation` ;
    - cloud non vide et `replace_local` vrai : renvoie le moteur cloud tel quel ;
  - `disable_cloud(cloud: Engine, local: LocalSource) -> Engine` : écrit dans un fichier temporaire voisin de `coach.db`, fait `copy_all` + `verify_copy`, puis remplace `coach.db` atomiquement (`os.replace`) ;
  - `wipe_cloud(cloud: Engine) -> None` ;
  - `delete_local_files(home: Path) -> None` : supprime `coach.db`, `gpx/` et `history.json` s'ils existent.
- Routes (dans `create_app`, réservées à la boucle locale comme les réglages LAN, via `is_loopback`) :
  - `GET /api/storage` → `CloudStatus` ;
  - `POST /api/storage/cloud` avec le corps `{url, token, replace_local: bool = false}` :
    - 200 et `CloudStatus` après la bascule ;
    - 409 `needs_confirmation`, message « Les données de ce PC seront remplacées par celles du cloud » ;
    - 422 `cloud_unreachable` avec le message de `probe` ;
    - 409 `schema_too_new` ;
  - `DELETE /api/storage/cloud` : retour en local, 200 et `CloudStatus` ;
  - `POST /api/storage/cloud/wipe` : 200 ; 409 si le mode n'est pas cloud.
- Ordre d'activation (atomique côté réglages) :
  1. `probe` ;
  2. `enable_cloud` ;
  3. `save_settings` (mode + identifiants) ;
  4. remplacer `app.state.repo` et recréer `app.state.history` ;
  5. `delete_local_files`.

  Une exception à l'une des étapes 1 à 3 laisse les réglages et les fichiers intacts.
- Ordre de désactivation :
  1. `disable_cloud` ;
  2. `save_settings` (mode local, URL et jeton effacés) ;
  3. remplacer `app.state.repo`.
- Erreurs globales : `SchemaTooNew` → 409 `schema_too_new` « Mets à jour CoachCloclo sur ce PC ». Une `sqlalchemy.exc.OperationalError` ou `DBAPIError` d'origine réseau, levée par une requête en mode cloud → 503 `cloud_unreachable` « Base cloud injoignable : vérifie ta connexion ». Au démarrage, si la source cloud échoue, l'app démarre quand même avec un repo « indisponible » (toutes les routes sauf `/api/storage*` et `/api/status` répondent 503 ou 409), afin que l'utilisateur puisse corriger le jeton ou attendre le réseau.

- [ ] **Step 1 : tests** (la « base cloud » est une seconde base SQLite enveloppée dans une source de test).
  - `test_enable_on_empty_cloud_copies_and_deletes_local` : après l'appel, `coach.db` n'existe plus, `GET /api/storage` indique `mode == "turso"`, et `GET /api/plan` renvoie les données d'avant.
  - `test_enable_on_nonempty_cloud_needs_confirmation_then_adopts` : 409 `needs_confirmation`, puis avec `replace_local=true` → les données du cloud, et le local supprimé.
  - `test_enable_with_bad_token_changes_nothing` (Review Focus 3) : `probe` lève `CloudUnreachable` → 422, `settings.storage_mode == "local"`, `coach.db` toujours présent.
  - `test_enable_copy_failure_keeps_local` : `verify_copy` lève une erreur → 500 ou 422, mode local, fichiers intacts.
  - `test_disable_copies_back_and_keeps_cloud` : `coach.db` recréé avec les mêmes données, la base cloud est inchangée et le jeton est effacé.
  - `test_wipe_cloud`.
  - `test_schema_too_new_on_enable` (Review Focus 4).
  - `test_cloud_unreachable_returns_503` (Review Focus 5) : le moteur cloud lève `OperationalError` → `GET /api/plan` renvoie 503 `cloud_unreachable`.
  - `test_storage_routes_loopback_only` : depuis une IP du réseau local → 403.
  - `test_storage_view_never_returns_token`.
- [ ] **Step 2 :** lancer. Attendu : FAIL.
- [ ] **Step 3 :** implémenter.
- [ ] **Step 4 :** `uv run pytest`. Attendu : PASS.
- [ ] **Step 5 :** commit `feat(storage): activer, désactiver et effacer le stockage cloud`.

### Task 8 : interface des Réglages et bandeaux d'erreur

**Files :**
- Create : `web/src/components/StorageSettings.svelte`, `web/src/components/StorageSettings.test.ts`
- Modify : `web/src/lib/api.ts`, `web/src/routes/Setup.svelte` (sous `<LanSettings />`), `web/src/components/ErrorBanner.svelte` (ou l'équivalent qui affiche les erreurs d'API)

**Interfaces :**
- Consumes : routes de la tâche 7.
- Produces dans `api.ts` :
  - `type StorageView = { mode: "local" | "turso"; turso_url: string | null; has_turso_token: boolean }` ;
  - `storage()`, `enableCloud(url, token, replaceLocal)`, `disableCloud()` et `wipeCloud()`.

Contenu du bloc « Stockage des données » :
- **Mode local :** une phrase d'explication, le lien vers le guide (section README de la tâche 9), les champs URL et jeton, et le bouton « Stocker mes données dans le cloud ».
  - Sur 409 `needs_confirmation`, une boîte de confirmation affiche le message du serveur, puis renvoie la requête avec `replaceLocal=true`.
  - Pendant la copie, le bouton est désactivé et affiche « Transfert en cours… ».
- **Mode cloud :** l'URL (jeton masqué), « Revenir au stockage local » et « Effacer mes données du cloud » (avec confirmation : « Les données seront supprimées du cloud pour tous tes PC. Cette action est irréversible. »).

- [ ] **Step 1 : tests Vitest.**
  - Affichage selon le mode.
  - Activation réussie : appel avec les bons arguments, puis affichage du mode cloud.
  - `needs_confirmation` → confirmation → second appel avec `replaceLocal=true`.
  - Message d'erreur `cloud_unreachable` affiché.
  - Effacement : la confirmation est demandée avant l'appel.
  - Pour `ErrorBanner` : les codes `cloud_unreachable` et `schema_too_new` affichent le message du serveur ; pour `schema_too_new`, un lien vers les Réglages permet de mettre à jour.
- [ ] **Step 2 :** `cd web && npm test -- StorageSettings`. Attendu : FAIL.
- [ ] **Step 3 :** implémenter en suivant le style de `LanSettings.svelte`.
- [ ] **Step 4 :** `npm test` puis `npm run build`. Attendu : PASS, build OK.
- [ ] **Step 5 :** commit `feat(web): réglage du stockage cloud`.

### Task 9 : doctor, empaquetage Windows, guide

**Files :**
- Modify : `coach/doctor.py`, `packaging/windows/coachcloclo.spec` (`hiddenimports` : `sqlalchemy_libsql` et `libsql_experimental`), `README.md`
- Test : `tests/test_doctor.py` (ou le fichier existant de tests du doctor)

- [ ] **Step 1 : tests.**
  - `test_doctor_checks_cloud_when_enabled` : mode turso et `probe` en échec → le check « Base cloud » est en erreur avec le message.
  - En mode local, ce check n'apparaît pas. Avec `--offline`, il est sauté.
- [ ] **Step 2 :** lancer. Attendu : FAIL. Implémenter. Relancer. Attendu : PASS.
- [ ] **Step 3 :** README.
  - Mettre à jour la section « Données et tokens » : mode local par défaut ; ce qui part dans le cloud et ce qui reste sur le PC.
  - Ajouter une section « Stockage dans le cloud (Turso) » avec le guide pas à pas : créer un compte sur turso.tech, créer une base (région proche), créer un jeton d'accès à cette seule base, coller l'URL `libsql://…` et le jeton dans Réglages → Stockage des données, puis faire de même sur le 2ᵉ PC (qui adopte le cloud).
  - Ajuster la phrase d'introduction « tes données ne quittent pas ton ordinateur » pour mentionner l'option.
- [ ] **Step 4 :** construire l'installateur Windows en local (commande du workflow `release.yml`), installer, activer le cloud sur une base de test, vérifier dans le journal qu'aucune erreur d'import de `libsql` n'apparaît, puis revenir en local.
- [ ] **Step 5 :** commit `feat(storage): doctor, empaquetage et guide Turso`.

### Vérification finale

- [ ] `uv run pytest`, `uv run pytest -m live tests/storage` (avec une base Turso), `cd web && npm test && npm run build`.
- [ ] Scénario réel sur deux PC :
  1. activer sur le PC maison (cloud vide) ;
  2. activer sur le PC du travail (confirmation, adoption) ;
  3. créer un imprévu au travail, puis le voir à la maison après rechargement ;
  4. lancer la synchro sur les deux PC en même temps : un seul la fait, l'autre affiche le message de verrou ;
  5. revenir en local au travail : `coach.db` est recréé, et la maison voit toujours le cloud.
