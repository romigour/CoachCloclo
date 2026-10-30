# Page d'accueil Stats — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une page d'accueil `#/stats` interactive (filtres période / sport, 6 blocs de graphiques) alimentée par tout l'historique Garmin, les records personnels Garmin et les compétitions saisies.

**Architecture:** Le back importe l'historique complet en arrière-plan (thread, état dans `history.json`), stocke records et compétitions dans deux nouvelles tables, et expose une liste compacte d'activités normalisées. Le front calcule tous les agrégats dans des modules TS purs (`web/src/lib/stats/`) et les affiche avec ECharts via une enveloppe `EChart.svelte`.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, garminconnect, pytest ; Svelte 5, TypeScript, Vite, Vitest, ECharts 5.6.0.

**Spec:** `docs/superpowers/specs/2026-10-30-stats-homepage-design.md` (à lire en entier avant toute tâche).

## Global Constraints

- Interface, messages d'erreur, commentaires et docstrings en français, comme le reste du code.
- Aucune nouvelle dépendance Python. Une seule nouvelle dépendance front : `echarts`, version exacte `5.6.0` (pas de `^`), importée de façon modulaire (`echarts/core`), renderer SVG.
- Pas de migration des colonnes existantes : seules deux tables sont ajoutées (`Race`, `PersonalRecord`), créées par `SQLModel.metadata.create_all`.
- L'état de l'import vit dans `data_dir() / "history.json"`, jamais dans `settings.json`.
- Les composants Svelte ne calculent rien : tout agrégat vient d'une fonction de `web/src/lib/stats/`.
- Dates côté front manipulées comme chaînes ISO `YYYY-MM-DD` (date locale de l'activité) ; jamais via `new Date(iso)` qui décale selon le fuseau. Semaines du lundi au dimanche.
- Seuils nommés (dans `web/src/lib/stats/running.ts`) : `MIN_DURATION_S = 1200`, `MAX_DPLUS_PER_KM = 10`, `MIN_TREND_POINTS = 8`, `MIN_ZONE_COVERAGE = 0.5`. Agrégation par semaine si la période fait ≤ 183 jours, par mois sinon. Catégories de distance de compétition à ±3 % de 5000, 10000, 21097.5, 42195 m.
- Commits sans signature ni trailer Claude.
- Vérification complète : `uv run pytest` et `cd web && npm test && npm run build` verts.

## Review Focus

1. Activités sans distance ou sans durée (renfo, natation en piscine, saisie manuelle) : aucune division par zéro, aucun `NaN`/`Infinity` dans allure, efficacité, km ou variations — ces activités comptent en heures et en séances seulement.
2. JSON Garmin incomplet (anciennes activités sans `eventType`, sans `hrTimeInZone_*`, sans `vO2MaxValue`, `startTimeLocal` absent ou mal formé) : la ligne normalisée met `null`, l'activité n'est jamais perdue à cause d'un champ facultatif.
3. Synchro et import en parallèle qui insèrent la même activité : la contrainte d'unicité sur `garmin_activity_id` ne doit ni faire échouer l'import ni la synchro (on ignore la ligne en conflit).
4. Période sans activité ou période précédente vide : chiffres à 0 et variation « — » (`null`), jamais `+Infinity %` ; blocs en état vide explicite.
5. Changement de fuseau / heure d'été : une activité du dimanche 23 h reste dans sa semaine et son jour locaux (dates ISO de `startTimeLocal`, pas de conversion `Date`).

Chaque point a son test dans la tâche qui possède le code : 1 → Tâches 3, 6, 7 ; 2 → Tâche 3 ; 3 → Tâche 2 ; 4 → Tâche 6 ; 5 → Tâche 7.

---

## Fichiers

Back :
- `coach/garmin/port.py` (mod.) — `PersonalRecordSummary`, `activities_page`, `personal_records`, fake.
- `coach/garmin/client.py` (mod.) — parsing factorisé `_summary`, `activities_page`, `personal_records`.
- `coach/plan/models.py` (mod.) — tables `Race`, `PersonalRecord`.
- `coach/plan/repo.py` (mod.) — accès activités / compétitions / records.
- `coach/services/activities.py` (nouveau) — `store_summaries`, déplacé de `sync.py`.
- `coach/services/sync.py` (mod.) — utilise `store_summaries`, rafraîchit les records.
- `coach/stats/__init__.py`, `coach/stats/normalize.py` (nouveaux) — familles de sport, lignes normalisées.
- `coach/services/history.py` (nouveau) — état, import paginé, records, `HistoryRunner`.
- `coach/api/app.py` (mod.) — endpoints stats / races / history, `/api/status`, déclenchement auto.

Front :
- `web/src/lib/api.ts` (mod.) — types et appels.
- `web/src/lib/stats/{filter,kpis,consistency,volume,running,races}.ts` + tests.
- `web/src/components/stats/EChart.svelte`, `web/src/test/EChartStub.svelte`.
- `web/src/components/stats/{Filters,KpiRow,ConsistencyCalendar,VolumeChart,SportDonut,RunningProgress,Records,Races,RaceEditDialog}.svelte`.
- `web/src/routes/Stats.svelte` + `Stats.test.ts`.
- `web/src/App.svelte`, `web/src/App.test.ts`, `web/src/routes/Setup.svelte` (mod.).

---

### Task 1: Port Garmin — pagination de l'historique et records personnels

**Files:**
- Modify: `coach/garmin/port.py`, `coach/garmin/client.py`
- Create: `tests/fixtures/garmin/personal_records.json`
- Test: `tests/garmin/test_client.py`

**Interfaces:**
- Produces:
  - `PersonalRecordSummary(BaseModel)` : `kind: Literal["1k", "1mile", "5k", "10k", "half", "marathon", "longest_run"]`, `value: float` (secondes, ou mètres pour `longest_run`), `garmin_activity_id: int | None`, `date: date | None`.
  - `GarminPort.activities_page(self, offset: int, limit: int) -> list[ActivitySummary]` (du plus récent au plus ancien, `[]` en fin d'historique).
  - `GarminPort.personal_records(self) -> list[PersonalRecordSummary]`.
  - `FakeGarminClient(..., personal_records: list[PersonalRecordSummary] | None = None)` ; `activities_page` renvoie `sorted(activities, key=(date, garmin_id), reverse=True)[offset:offset+limit]` ; les deux méthodes passent par `self._check("activities_page")` / `self._check("personal_records")` (donc `fail_on` fonctionne).
  - Constante `PR_KINDS: dict[int, str] = {1: "1k", 2: "1mile", 3: "5k", 4: "10k", 5: "half", 6: "marathon", 7: "longest_run"}` dans `client.py`.

- [ ] **Step 1: Écrire la fixture `personal_records.json`** (synthétique, avec le même `_comment` que les autres fixtures) : une liste avec `typeId` 1, 3, 4, 7 et 12 (inconnu), champs `typeId`, `value`, `activityId`, `prStartTimeGmtFormatted` (`"2025-05-04T08:12:00.0"`) ; une entrée `typeId` 3 sans `activityId`.

- [ ] **Step 2: Écrire les tests qui échouent** dans `tests/garmin/test_client.py`, sur le modèle des tests existants (API garminconnect simulée) :
  - `test_activities_page_parses_like_activities` : `get_activities(0, 100)` renvoie la fixture `activities.json["data"]` ; `client.activities_page(0, 100)` renvoie 2 `ActivitySummary` identiques à ceux de `client.activities(...)` sur la même donnée ; l'API simulée a reçu `(0, 100)`.
  - `test_activities_page_empty_end` : `get_activities` renvoie `[]` → `[]`.
  - `test_personal_records_maps_known_types` : 4 records (`1k`, `5k`, `10k`, `longest_run`), le `typeId` 12 est ignoré, `date == date(2025, 5, 4)`, `garmin_activity_id is None` pour l'entrée sans `activityId`.
  - `test_fake_activities_page_paginates_newest_first` : fake avec 3 activités de dates différentes ; `activities_page(0, 2)` → les 2 plus récentes, `activities_page(2, 2)` → la plus ancienne, `activities_page(4, 2)` → `[]`.

- [ ] **Step 3: Lancer** `uv run pytest tests/garmin/test_client.py -v` — attendu : FAIL (`AttributeError: activities_page`).

- [ ] **Step 4: Implémenter.** Dans `client.py`, extraire le corps de la boucle de `activities` en `_summary(a: Any) -> ActivitySummary | None` et l'utiliser dans `activities` et `activities_page` (`self._call(self._api.get_activities, offset, limit)`). `personal_records` passe par `self._call(self._api.get_personal_record)`, parsing défensif (`_int`, `_num`), date = 10 premiers caractères de `prStartTimeGmtFormatted` ou, à défaut, `actStartDateTimeInGMTFormatted`, `None` si illisible. Ajouter les deux méthodes au `Protocol` et au fake.

- [ ] **Step 5: Lancer** `uv run pytest tests/garmin -v` — attendu : PASS (les tests live restent désélectionnés).

- [ ] **Step 6: Commit** `feat(garmin): pagination de l'historique et records personnels`

---

### Task 2: Tables `Race` / `PersonalRecord`, dépôt et enregistrement commun des activités

**Files:**
- Modify: `coach/plan/models.py`, `coach/plan/repo.py`, `coach/services/sync.py`
- Create: `coach/services/activities.py`
- Test: `tests/plan/test_repo.py`, `tests/services/test_activities.py` (nouveau), `tests/services/test_sync.py` (doit rester vert)

**Interfaces:**
- Consumes: `ActivitySummary` (Task 1).
- Produces:
  - `Race(SQLModel, table=True)` : `id: int | None` (PK), `activity_id: int = Field(unique=True, index=True)`, `name: str | None`, `official_time_s: int | None`, `overall_rank: int | None`, `overall_total: int | None`, `category: str | None`, `category_rank: int | None`, `category_total: int | None`, `excluded: bool = False`.
  - `PersonalRecord(SQLModel, table=True)` : `id`, `kind: str`, `value: float`, `garmin_activity_id: int | None`, `date: dt.date | None`.
  - `Repo.all_activities() -> list[Activity]` (tri `date, id`), `Repo.has_activities() -> bool`, `Repo.activity(id: int) -> Activity` (`KeyError` si absente), `Repo.races() -> list[Race]`, `Repo.upsert_race(activity_id: int, fields: dict) -> Race` (crée ou met à jour, force `excluded=False`), `Repo.exclude_race(activity_id: int) -> None` (crée ou met à jour avec `excluded=True`, garde les autres champs), `Repo.records() -> list[PersonalRecord]`, `Repo.replace_records(records: list[PersonalRecord]) -> None` (supprime tout puis insère, dans une transaction).
  - `coach/services/activities.py` : `store_summaries(repo: Repo, summaries: Iterable[ActivitySummary]) -> int` — conversion identique à l'actuel `_import_activities` (allure, `raw_json`), ignore les ids déjà présents, **ignore aussi une `IntegrityError`** sur une ligne (insertion concurrente), retourne le nombre ajouté.

- [ ] **Step 1: Tests qui échouent.**
  - `tests/plan/test_repo.py` : `test_upsert_race_creates_then_updates` (2e appel modifie `official_time_s`, une seule ligne) ; `test_exclude_race_keeps_fields` (après `upsert_race(5, {"name": "10 km de Rennes"})` puis `exclude_race(5)` : `excluded is True`, `name` conservé ; `upsert_race` ensuite remet `excluded=False`) ; `test_replace_records_replaces_all` ; `test_has_activities`.
  - `tests/services/test_activities.py` : `test_store_summaries_skips_existing` (2 appels avec les mêmes résumés → 2 puis 0) ; `test_store_summaries_survives_concurrent_insert` (Review Focus 3 : un `Repo` dont `activity_by_garmin_id` renvoie toujours `None` via monkeypatch, alors que la ligne existe déjà → pas d'exception, retourne 0, une seule ligne en base).

- [ ] **Step 2: Lancer** `uv run pytest tests/plan/test_repo.py tests/services/test_activities.py -v` — attendu : FAIL (`ImportError`).

- [ ] **Step 3: Implémenter** les modèles, les méthodes du dépôt et `store_summaries` (chaque insertion dans sa propre transaction pour isoler l'`IntegrityError`). Dans `sync.py`, `_import_activities` devient `store_summaries(repo, garmin.activities(since, today))` (tri conservé dans `store_summaries`).

- [ ] **Step 4: Lancer** `uv run pytest tests/plan tests/services -v` — attendu : PASS, y compris `test_sync.py` inchangé.

- [ ] **Step 5: Commit** `feat(stats): tables Race et PersonalRecord, enregistrement commun des activités`

---

### Task 3: Normalisation des activités

**Files:**
- Create: `coach/stats/__init__.py` (vide), `coach/stats/normalize.py`, `tests/stats/__init__.py`, `tests/fixtures/garmin/activity_full.json`
- Test: `tests/stats/test_normalize.py`

**Interfaces:**
- Consumes: `Activity`, `Race` (Task 2).
- Produces:
  - `Family = Literal["run", "trail", "bike", "swim", "strength", "walk", "other"]`.
  - `FAMILIES: dict[str, Family]` — `running`, `treadmill_running`, `track_running`, `street_running`, `indoor_running`, `virtual_run` → `run` ; `trail_running`, `ultra_run` → `trail` ; `cycling`, `road_biking`, `mountain_biking`, `gravel_cycling`, `indoor_cycling`, `virtual_ride`, `e_bike_fitness` → `bike` ; `lap_swimming`, `open_water_swimming`, `swimming` → `swim` ; `strength_training`, `indoor_cardio`, `hiit`, `yoga`, `pilates` → `strength` ; `walking`, `hiking`, `casual_walking` → `walk`.
  - `sport_family(type_key: str) -> Family` (inconnu → `other`).
  - `race_view(race: Race) -> dict` : les 7 champs de saisie de `Race`.
  - `stat_row(activity: Activity, race: Race | None) -> dict` avec exactement les clés : `id`, `garmin_id`, `date` (ISO), `start` (`startTimeLocal` tel quel ou `None`), `name`, `family`, `type_key`, `duration_s`, `distance_m`, `d_plus_m`, `avg_hr`, `max_hr`, `vo2max`, `hr_zones_s`, `race`.
  - Règles : `name` = `activityName` ou `None` ; `max_hr` = `maxHR` ; `vo2max` = `vO2MaxValue` ; `hr_zones_s` = `[hrTimeInZone_1..5]` si les 5 sont des nombres, sinon `None` ; `race` = `race_view(race)` si `race` non exclue ; sinon `race_view(Race(activity_id=activity.id))` (tous les champs à `None`) si `raw["eventType"]["typeKey"] == "race"` et `race` est `None` ; sinon `None`. Valeurs numériques `0` ou négatives pour `distance_m` / `duration_s` → `None`.

- [ ] **Step 1: Écrire `activity_full.json`** (synthétique, `_comment` habituel) : course avec `activityName`, `startTimeLocal`, `maxHR`, `vO2MaxValue`, `hrTimeInZone_1..5`, `eventType: {"typeKey": "race"}`.

- [ ] **Step 2: Tests qui échouent** dans `tests/stats/test_normalize.py` :
  - `test_sport_family` : `trail_running` → `trail`, `treadmill_running` → `run`, `indoor_cycling` → `bike`, `paddleboarding` → `other`.
  - `test_stat_row_full` : à partir de la fixture, toutes les clés présentes, `hr_zones_s` de longueur 5, `race` est un dict dont `name is None`.
  - `test_stat_row_minimal_raw` (Review Focus 2) : `raw_json="{}"`, `startTimeLocal` absent → `start is None`, `name/max_hr/vo2max/hr_zones_s/race` à `None`, `date` = la date de l'`Activity`.
  - `test_stat_row_partial_zones` : 4 zones sur 5 → `hr_zones_s is None`.
  - `test_stat_row_zero_distance` (Review Focus 1) : `distance_m=0`, `duration_s=0` → `None` tous les deux.
  - `test_race_priority` : `Race(excluded=True)` + `eventType race` → `race is None` ; `Race(name="Semi de Nantes")` sans `eventType` → `race["name"] == "Semi de Nantes"`.

- [ ] **Step 3: Lancer** `uv run pytest tests/stats -v` — attendu : FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implémenter** `coach/stats/normalize.py` (`json.loads` du `raw_json` protégé : JSON illisible → `{}`).

- [ ] **Step 5: Lancer** `uv run pytest tests/stats -v` — attendu : PASS.

- [ ] **Step 6: Commit** `feat(stats): normalisation des activités Garmin`

---

### Task 4: Service d'import de l'historique

**Files:**
- Create: `coach/services/history.py`
- Modify: `coach/services/sync.py`
- Test: `tests/services/test_history.py` (nouveau), `tests/services/test_sync.py`

**Interfaces:**
- Consumes: `GarminPort.activities_page`, `personal_records` (Task 1) ; `store_summaries`, `Repo.replace_records` (Task 2).
- Produces:
  - `HistoryState(BaseModel)` : `status: Literal["idle", "running", "done", "error"] = "idle"`, `imported: int = 0`, `error: str | None = None`, `finished_at: datetime | None = None`.
  - `load_state() -> HistoryState` / `save_state(s: HistoryState) -> None` sur `data_dir() / "history.json"` (fichier absent ou illisible → `HistoryState()`).
  - `PAGE_SIZE = 100`, `PAGE_PAUSE_S = 1.0`.
  - `refresh_records(repo: Repo, garmin: GarminPort) -> bool` : `replace_records` si l'appel réussit ; sur `GarminUnavailable` / `GarminRateLimited` / `GarminAuthRequired`, ne touche à rien et renvoie `False`.
  - `import_history(repo: Repo, garmin: GarminPort, *, sleep: Callable[[float], None] = time.sleep) -> int` : état `running` + `imported=0` au départ ; boucle `offset` par `PAGE_SIZE` ; après chaque page, `store_summaries` puis `save_state` avec `imported` cumulé ; s'arrête dès qu'une page contient moins de `PAGE_SIZE` activités (page vide comprise), sinon `sleep(PAGE_PAUSE_S)` avant la page suivante ; puis `refresh_records` ; état `done` + `finished_at`. Sur exception Garmin : état `error` avec `str(exc)` (pour `GarminAuthRequired` : `"Connexion Garmin expirée : reconnecte-toi dans les Réglages"`), puis relève l'exception.
  - `class HistoryRunner` : `__init__(self, repo: Repo, garmin_factory: Callable[[], GarminPort])` ; `start(self) -> bool` (`False` si un import tourne déjà — verrou `threading.Lock` non bloquant ; sinon lance un thread démon qui crée le client via la factory, appelle `import_history` et avale l'exception déjà enregistrée dans l'état ; une erreur de la factory passe aussi l'état à `error`) ; `running` (propriété) ; `join(self, timeout: float | None = None) -> None` pour les tests.
  - `recover_orphan() -> None` : un état `running` sur disque passe à `error` avec `"Import interrompu"`.
- Dans `sync()` : après `store_summaries`, appeler `refresh_records(repo, garmin)` (résultat ignoré).

- [ ] **Step 1: Tests qui échouent** (`coach_home` fixture, `FakeGarminClient`, `sleep` enregistreur) :
  - `test_import_paginates_until_empty_page` : 250 activités, `import_history(..., sleep=calls.append)` → 250 en base, retourne 250, `calls == [1.0, 1.0]` (pages de 100, 100 puis 50 : la page incomplète termine l'import, aucune page vide demandée), état `done`, `imported == 250`, `finished_at` renseigné.
  - `test_import_resumes_without_duplicates` : 2e appel → retourne 0, toujours 250 lignes.
  - `test_import_error_keeps_activities` : fake dont `activities_page` lève `GarminUnavailable` à `offset >= 100` (sous-classe du fake) → `pytest.raises(GarminUnavailable)`, 100 lignes en base, état `error` avec message, `imported == 100`.
  - `test_import_refreshes_records` : fake avec 2 records → `repo.records()` en a 2.
  - `test_refresh_records_failure_keeps_table` : records existants, `fail_on={"personal_records"}` → `False`, table inchangée.
  - `test_runner_refuses_second_start` : factory qui bloque sur un `threading.Event` ; `start()` → `True`, second `start()` → `False` ; libérer, `join()`.
  - `test_runner_factory_auth_error_sets_error_state` : factory qui lève `GarminAuthRequired` → après `join()`, état `error`.
  - `test_recover_orphan` : état `running` écrit → `recover_orphan()` → `error`, `"Import interrompu"`.
  - Dans `tests/services/test_sync.py` : `test_sync_refreshes_personal_records`.

- [ ] **Step 2: Lancer** `uv run pytest tests/services -v` — attendu : FAIL.

- [ ] **Step 3: Implémenter** `coach/services/history.py` et l'appel dans `sync.py`.

- [ ] **Step 4: Lancer** `uv run pytest tests/services -v` — attendu : PASS.

- [ ] **Step 5: Commit** `feat(stats): import complet de l'historique Garmin en arrière-plan`

---

### Task 5: API — stats, compétitions, import, statut

**Files:**
- Modify: `coach/api/app.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: `stat_row` (Task 3) ; `HistoryRunner`, `load_state`, `recover_orphan` (Task 4) ; méthodes du dépôt (Task 2).
- Produces (JSON) :
  - `GET /api/stats/activities` → `{"activities": [stat_row...]}` triées par `date` puis `id` (une seule requête `races()`, indexée par `activity_id`).
  - `GET /api/stats/records` → `{"records": [{"kind", "value", "garmin_activity_id", "date"}...]}`.
  - `PUT /api/races/{activity_id}` corps `RaceBody` → `stat_row` mis à jour ; `404 not_found` si l'activité n'existe pas.
  - `DELETE /api/races/{activity_id}` → `{"status": "ok"}` ; `404` si l'activité n'existe pas.
  - `POST /api/history/import` → `{"status": "started"}` ; `409 history_running` si déjà en cours.
  - `GET /api/status` gagne `has_activities: bool` et `history: {"status", "imported", "error"}`.
- `RaceBody(BaseModel)` : `name: str | None = Field(None, max_length=120)`, `official_time_s: int | None = Field(None, gt=0)`, `overall_rank`, `overall_total`, `category_rank`, `category_total: int | None = Field(None, ge=1)`, `category: str | None = Field(None, max_length=40)` ; `model_validator` : rang ≤ effectif quand les deux sont fournis (message `"Le classement dépasse le nombre de participants"`). Erreurs au format 422 existant.
- `create_app` : `recover_orphan()` puis `app.state.history = HistoryRunner(app.state.repo, garmin_factory)`. `post_sync` : après `sync(...)`, si `load_state().status == "idle"`, `app.state.history.start()`. Les `DELETE` passent par le `csrf_guard` existant (méthode non sûre).

- [ ] **Step 1: Tests qui échouent** dans `tests/api/test_app.py` (client et factories existants) :
  - `test_stats_activities_merges_races` : 2 activités dont une avec `Race(name=...)` → 2 lignes, `race["name"]` correct sur la bonne.
  - `test_put_race_validates_rank` : `overall_rank=50, overall_total=10` → 422 ; `official_time_s=0` → 422 ; corps valide → 200 et `race["official_time_s"]` renvoyé.
  - `test_put_race_unknown_activity_404`.
  - `test_delete_race_excludes_detected_race` : activité `eventType race` → `DELETE` → la ligne revient avec `race is None`.
  - `test_history_import_conflict` : runner remplacé par un faux dont `start()` renvoie `False` → 409 `history_running`.
  - `test_status_has_activities_and_history`.
  - `test_sync_starts_history_import_once` : faux runner comptant les `start()` ; 1er `POST /api/sync` → 1 appel ; après `save_state(HistoryState(status="done"))`, 2e sync → toujours 1.
  - `test_records_endpoint`.

- [ ] **Step 2: Lancer** `uv run pytest tests/api -v` — attendu : FAIL (404 sur les nouvelles routes).

- [ ] **Step 3: Implémenter** les routes dans `create_app` (section `# --- statistiques ---`), à la suite des routes existantes.

- [ ] **Step 4: Lancer** `uv run pytest -v` — attendu : tout PASS.

- [ ] **Step 5: Commit** `feat(api): endpoints de statistiques, compétitions et import de l'historique`

---

### Task 6: Front — types d'API, filtres et chiffres clés

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/lib/api.test.ts`
- Create: `web/src/lib/stats/filter.ts`, `filter.test.ts`, `kpis.ts`, `kpis.test.ts`

**Interfaces:**
- Consumes: les réponses JSON de la Task 5.
- Produces (`api.ts`) :
  - `type Family = "run" | "trail" | "bike" | "swim" | "strength" | "walk" | "other"`.
  - `type RaceInfo = { name: string | null; official_time_s: number | null; overall_rank: number | null; overall_total: number | null; category: string | null; category_rank: number | null; category_total: number | null }`.
  - `type StatActivity` : les 15 clés de `stat_row`, `race: RaceInfo | null`, `hr_zones_s: number[] | null`.
  - `type PersonalRecord = { kind: "1k" | "1mile" | "5k" | "10k" | "half" | "marathon" | "longest_run"; value: number; garmin_activity_id: number | null; date: string | null }`.
  - `type HistoryState = { status: "idle" | "running" | "done" | "error"; imported: number; error: string | null }` ; `Status` gagne `has_activities: boolean; history: HistoryState`.
  - `api.statsActivities()`, `api.statsRecords()`, `api.saveRace(activityId: number, race: Partial<RaceInfo>) -> StatActivity` (PUT), `api.removeRace(activityId: number)` (DELETE, avec `X-Coach`), `api.importHistory()`.
- Produces (`filter.ts`) :
  - `type Period = { from: string; to: string }` (ISO inclus ; `all` → première activité .. aujourd'hui).
  - `type PeriodChoice = { kind: "12m" } | { kind: "year"; year: number } | { kind: "all" } | { kind: "custom"; from: string; to: string }`.
  - `type SportFilter = "all" | "running" | Family` (`running` = `run` + `trail`).
  - `resolvePeriod(choice: PeriodChoice, today: string, acts: StatActivity[]): Period` (`12m` = du lendemain du même jour un an plus tôt à `today`).
  - `previousPeriod(p: Period): Period` (même nombre de jours, juste avant).
  - `filterActivities(acts: StatActivity[], p: Period, sport: SportFilter): StatActivity[]`.
  - `sportOptions(acts: StatActivity[]): SportFilter[]` (`all`, `running` si run ou trail présents, puis chaque famille présente dans l'ordre de `Family`).
  - Utilitaires ISO partagés : `addDays(iso: string, n: number): string`, `daysBetween(a: string, b: string): number`, `mondayOf(iso: string): string` — calculés en UTC (`Date.UTC`) pour ne jamais dépendre du fuseau.
- Produces (`kpis.ts`) : `type Kpi = { key: "hours" | "run_km" | "sessions" | "d_plus"; value: number; delta: number | null }` ; `computeKpis(current: StatActivity[], previous: StatActivity[] | null): Kpi[]` — `delta` = variation relative (0.12 pour +12 %), `null` si `previous` est `null` ou si la valeur précédente vaut 0.

- [ ] **Step 1: Tests qui échouent** :
  - `filter.test.ts` : `resolvePeriod({kind:"12m"}, "2026-10-30", [])` → `{from:"2025-10-31", to:"2026-10-30"}` ; `previousPeriod` de ce résultat → `{from:"2024-10-31", to:"2025-10-30"}` ; `filterActivities` avec `"running"` garde run et trail, exclut bike ; `mondayOf("2026-11-01")` → `"2026-10-26"` (dimanche) ; `sportOptions` ordonné.
  - `kpis.test.ts` : une activité sans distance compte 1 séance et ses heures, 0 km, pas de `NaN` (Review Focus 1) ; période précédente vide → tous les `delta` à `null` (Review Focus 4) ; `previous` `null` → `delta` `null` ; `run_km` ignore le vélo.
  - `api.test.ts` : `removeRace(3)` envoie `DELETE /api/races/3` avec l'en-tête `X-Coach`.

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/lib` — attendu : FAIL.

- [ ] **Step 3: Implémenter.** Ajouter `const del = <T>(p: string) => request<T>("DELETE", p);` à côté de `get` / `post`.

- [ ] **Step 4: Lancer** `cd web && npx vitest run src/lib` — attendu : PASS.

- [ ] **Step 5: Commit** `feat(web): types de stats, filtres et chiffres clés`

---

### Task 7: Front — régularité et volume

**Files:**
- Create: `web/src/lib/stats/consistency.ts`, `consistency.test.ts`, `volume.ts`, `volume.test.ts`

**Interfaces:**
- Consumes: `Period`, `addDays`, `mondayOf`, `daysBetween` (Task 6).
- Produces :
  - `dailyMinutes(acts: StatActivity[]): [string, number][]` (une entrée par jour avec activité, minutes arrondies).
  - `weekStats(acts: StatActivity[], p: Period, today: string): { activeWeeks: number; totalWeeks: number; currentStreak: number; bestStreak: number }` — semaines du lundi au dimanche couvrant `p` ; la semaine en cours (contenant `today`) compte si active et ne casse pas la série si elle est encore vide.
  - `type Bucket = "week" | "month"` ; `bucketFor(p: Period): Bucket` (≤ 183 jours → `week`).
  - `volumeSeries(acts: StatActivity[], p: Period, metric: "hours" | "km"): { labels: string[]; series: { family: Family; values: number[] }[]; movingAvg: (number | null)[] }` — toutes les semaines / mois de la période (y compris vides, à 0), une série par famille présente, `movingAvg` sur 4 buckets du total (`null` pour les 3 premiers) ; en `km`, les activités sans distance comptent 0.
  - `sportShare(acts: StatActivity[]): { family: Family; hours: number }[]` trié par heures décroissantes, familles à 0 h exclues.

- [ ] **Step 1: Tests qui échouent** :
  - `consistency.test.ts` : série courante de 3 avec la semaine en cours vide ; série cassée par une semaine vide au milieu ; `bestStreak` ≥ `currentStreak` ; activité `date "2026-10-25"` (dimanche) avec `start "2026-10-25T23:30:00"` comptée dans la semaine du `2026-10-19` (Review Focus 5).
  - `volume.test.ts` : période de 90 jours → `week`, 400 jours → `month` ; mois vides présents à 0 ; `movingAvg[3]` = moyenne des 4 premiers totaux ; activité sans distance en `km` → 0, pas de `NaN`.

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/lib/stats` — attendu : FAIL.

- [ ] **Step 3: Implémenter** (dates en chaînes ISO via les utilitaires de `filter.ts` ; mois = `iso.slice(0, 7)`).

- [ ] **Step 4: Lancer** `cd web && npx vitest run src/lib/stats` — attendu : PASS.

- [ ] **Step 5: Commit** `feat(web): calculs de régularité et de volume`

---

### Task 8: Front — progression en course à pied et compétitions

**Files:**
- Create: `web/src/lib/stats/running.ts`, `running.test.ts`, `races.ts`, `races.test.ts`

**Interfaces:**
- Consumes: `StatActivity` (Task 6).
- Produces (`running.ts`, avec les 4 constantes des Global Constraints exportées) :
  - `aerobicEfficiency(acts: StatActivity[]): { points: { date: string; value: number }[]; trend: { slope: number; intercept: number } | null }` — retient `family === "run"`, `duration_s >= MIN_DURATION_S`, `avg_hr` et `distance_m` non nuls, `(d_plus_m ?? 0) / (distance_m / 1000) <= MAX_DPLUS_PER_KM` ; `value = (distance_m / (duration_s / 60)) / avg_hr` ; tendance par moindres carrés sur `x = daysBetween(premier point, date)` si `points.length >= MIN_TREND_POINTS`.
  - `vo2maxSeries(acts): { date: string; value: number }[]` (activités run/trail avec `vo2max`).
  - `longestRunByMonth(acts): { month: string; km: number }[]` (run + trail).
  - `zoneDistribution(acts): number[] | null` — cumul des 5 zones des run/trail ; `null` si aucune course ou si la part des courses ayant `hr_zones_s` est `< MIN_ZONE_COVERAGE`.
  - `trailSummary(acts): { dPlusM: number; dPlusPerKm: number } | null` (`null` sans sortie trail ; trail sans distance exclu du ratio).
- Produces (`races.ts`) :
  - `type DistanceCategory = "5k" | "10k" | "half" | "marathon"` ; `CATEGORY_M: Record<DistanceCategory, number>` ; `distanceCategory(distanceM: number | null, family: Family): DistanceCategory | null` (±3 %, `trail` → `null`).
  - `topPercent(rank: number | null, total: number | null): number | null` → `Math.max(1, Math.round(rank / total * 100))`, `null` si l'un manque.
  - `type RaceRow = { activity: StatActivity; timeS: number | null; official: boolean; paceSKm: number | null; overallTop: number | null; categoryTop: number | null }` ; `raceRows(acts): RaceRow[]` (activités avec `race`, plus récentes d'abord ; `timeS = race.official_time_s ?? duration_s`, `official` = temps officiel présent).
  - `raceProgression(acts): { category: DistanceCategory; points: { date: string; timeS: number }[] }[]` — seulement les catégories avec ≥ 2 courses.

- [ ] **Step 1: Tests qui échouent** :
  - `running.test.ts` : exclusion de chacune des conditions (trail, 19 min, sans FC, sans distance, 12 m/km) ; `trend` `null` à 7 points, non nul à 8 avec une pente positive sur des valeurs croissantes ; `zoneDistribution` `null` quand 1 course sur 3 a des zones ; `trailSummary` sans trail → `null`.
  - `races.test.ts` : 10 300 m → `10k`, 10 400 m → `null` (> 3 %), trail 21 km → `null` ; `topPercent(12, 80)` → 15, `topPercent(1, 5000)` → 1 ; `raceRows` prend le temps officiel en priorité et marque `official` ; `raceProgression` ignore une catégorie courue une seule fois.

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/lib/stats` — attendu : FAIL.

- [ ] **Step 3: Implémenter.**

- [ ] **Step 4: Lancer** `cd web && npx vitest run src/lib/stats` — attendu : PASS.

- [ ] **Step 5: Commit** `feat(web): calculs de progression en course et de compétitions`

---

### Task 9: ECharts et enveloppe `EChart.svelte`

**Files:**
- Modify: `web/package.json`, `web/package-lock.json`
- Create: `web/src/components/stats/EChart.svelte`, `web/src/lib/stats/echarts.ts`, `web/src/test/EChartStub.svelte`

**Interfaces:**
- Produces:
  - `web/src/lib/stats/echarts.ts` : enregistre (`echarts.use`) `BarChart`, `LineChart`, `PieChart`, `ScatterChart`, `HeatmapChart`, `CalendarComponent`, `GridComponent`, `TooltipComponent`, `LegendComponent`, `DataZoomComponent`, `VisualMapComponent`, `MarkLineComponent`, `SVGRenderer` ; exporte `echarts` et `themeColors(): { text: string; muted: string; border: string; accent: string; families: Record<Family, string> }` lus depuis les variables CSS de `app.css` (`getComputedStyle(document.documentElement)`), avec une palette de 7 couleurs de familles définie comme nouvelles variables `--fam-run`, `--fam-trail`, … dans `app.css` (clair et sombre).
  - `EChart.svelte` props : `option: EChartsCoreOption`, `height?: string = "280px"`, `onclick?: (params: { name: string; dataIndex: number; seriesName?: string; data: unknown }) => void`, `label: string` (posé en `aria-label` sur le conteneur, `role="img"`). Init au montage (renderer SVG), `setOption(option, true)` à chaque changement, `ResizeObserver` pour `resize()`, ré-init sur changement de `prefers-color-scheme`, `dispose()` au démontage.
  - `EChartStub.svelte` : mêmes props, rend `<div role="img" aria-label={label} data-option={JSON.stringify(option)}>` ; utilisé par les tests via `vi.mock("../components/stats/EChart.svelte", () => import("../test/EChartStub.svelte"))` (chemin relatif au fichier de test).

- [ ] **Step 1: Installer** `cd web && npm install --save-dev --save-exact echarts@5.6.0` — attendu : `package.json` contient `"echarts": "5.6.0"`.

- [ ] **Step 2: Implémenter** `echarts.ts`, `EChart.svelte`, `EChartStub.svelte` et les variables `--fam-*` dans `app.css`.

- [ ] **Step 3: Vérifier** `cd web && npm run build && npm test` — attendu : build OK, tests existants verts. Noter dans le message de commit la taille du chunk produit.

- [ ] **Step 4: Commit** `feat(web): ECharts et composant EChart`

---

### Task 10: Page Stats — filtres, chiffres clés, régularité, volume

**Files:**
- Create: `web/src/routes/Stats.svelte`, `web/src/routes/Stats.test.ts`, `web/src/components/stats/{Filters,KpiRow,ConsistencyCalendar,VolumeChart,SportDonut}.svelte`
- Modify: `web/src/App.svelte` (route `stats` seulement ; la redirection par défaut est en Task 12)

**Interfaces:**
- Consumes: Tasks 6, 7, 9.
- Produces:
  - `Stats.svelte` props : `history: HistoryState | null`, `onimport: () => void`. Charge `api.statsActivities()` et `api.statsRecords()` au montage ; détient `choice: PeriodChoice`, `sport: SportFilter`, `metric: "hours" | "km"`, mémorisés dans `localStorage` sous la clé `coach.stats.filters` (lecture et écriture dans `try/catch`, défauts `{kind:"12m"}` / `"all"` / `"hours"`) ; `today` = date locale du jour en ISO. Grille 2 colonnes à partir de 900 px. Bandeau si `history.status` vaut `running` (« Import de l'historique : {imported} activités… ») ou `error` (message + bouton « Reprendre » → `onimport`). Expose à ses enfants des valeurs dérivées (`$derived`) : `period`, `current`, `previous`.
  - `Filters.svelte` props : `choice`, `sport`, `options: SportFilter[]`, `years: number[]`, `onchange: (choice: PeriodChoice, sport: SportFilter) => void`, `onreset: () => void`. Libellés : « 12 derniers mois », « Année », « Tout », « Personnalisée » ; sports : « Tous », « Course à pied », « Course sur route », « Trail », « Vélo », « Natation », « Renfo / cardio », « Marche / rando », « Autres ». Collant en haut (`position: sticky`).
  - `KpiRow.svelte` props : `kpis: Kpi[]` ; libellés « Heures », « Km de course », « Séances », « D+ » ; variation « ▲ +12 % » / « ▼ −8 % » / « — ».
  - `ConsistencyCalendar.svelte` props : `days: [string, number][]`, `period: Period`, `stats` (retour de `weekStats`), `onpick: (period: Period) => void` (clic sur un jour → période d'un jour). Calendrier ECharts `calendar` + `heatmap`, une rangée par année de la période.
  - `VolumeChart.svelte` props : retour de `volumeSeries`, `metric`, `bucket: Bucket`, `onmetric`, `onpick: (period: Period) => void` (clic sur une barre → la semaine ou le mois). Barres empilées + ligne `movingAvg` (« Moyenne 4 semaines » / « Moyenne 4 mois »).
  - `SportDonut.svelte` props : `share` (retour de `sportShare`).
  - Clic `onpick` → `choice = {kind: "custom", from, to}`. Bloc sans activité : `<p class="empty">Pas assez de données sur cette période</p>`.

- [ ] **Step 1: Tests qui échouent** dans `Stats.test.ts` (fetch simulé comme dans `App.test.ts`, `EChart` simulé, `vi.setSystemTime(new Date(2026, 9, 30))`) :
  - `shows KPIs for the default 12-month period` : 3 activités dont une hors période → « Séances » vaut 2.
  - `changing sport filter recomputes` : choisir « Vélo » → « Km de course » vaut 0.
  - `empty period shows explicit empty state` : aucune activité → au moins un « Pas assez de données sur cette période », aucun `role="img"`.
  - `history running banner` et `history error banner calls onimport` (clic sur « Reprendre »).
  - `filters survive a throwing localStorage` : `localStorage.getItem` qui lève → la page s'affiche avec les défauts.

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/routes/Stats.test.ts` — attendu : FAIL.

- [ ] **Step 3: Implémenter** les composants et ajouter `"stats"` à `ROUTES` dans `App.svelte` avec le lien « Stats » en premier dans la `nav`.

- [ ] **Step 4: Lancer** `cd web && npm test` — attendu : PASS.

- [ ] **Step 5: Vérifier dans l'app** : `uv run coach start` sur une base contenant des activités, ouvrir `#/stats`, essayer filtres, clic sur une barre et sur un jour, PC et largeur 375 px, thème sombre.

- [ ] **Step 6: Commit** `feat(web): page Stats avec filtres, chiffres clés, régularité et volume`

---

### Task 11: Page Stats — course à pied, records, compétitions

**Files:**
- Create: `web/src/components/stats/{RunningProgress,Records,Races,RaceEditDialog}.svelte`
- Modify: `web/src/routes/Stats.svelte`, `web/src/routes/Stats.test.ts`

**Interfaces:**
- Consumes: Tasks 6, 8, 9, 10 ; `api.saveRace`, `api.removeRace`.
- Produces:
  - `RunningProgress.svelte` props : `acts: StatActivity[]` (déjà filtrées). Quatre graphiques : « Efficacité aérobie » (nuage + `markLine` de tendance ; sous-titre « Vitesse / FC sur sorties route ≥ 20 min, peu de dénivelé » ; état vide si aucun point, mention « Tendance à partir de 8 sorties » si `trend` est `null`), « VO2max », « Sortie la plus longue par mois », « Zones FC » (barres 1 à 5, part zones 1-2 affichée « Facile : 78 % » ; bloc absent si `null`), et un encart « Trail » (D+ cumulé, D+ moyen / km) si non `null`. Le bloc entier n'est pas rendu si le filtre sport ne contient ni `run` ni `trail`.
  - `Records.svelte` props : `records: PersonalRecord[]`. Tableau : « 1 km », « 1 mile », « 5 km », « 10 km », « Semi », « Marathon », « Plus longue sortie » ; temps `h:mm:ss`, allure `m:ss /km` (calculée sur la distance nominale), date, lien `https://connect.garmin.com/modern/activity/{id}` (`target="_blank" rel="noopener"`). Mention « Records absolus, non filtrés par période ». Liste vide → « Records indisponibles ».
  - `Races.svelte` props : `acts: StatActivity[]` (toutes les activités pour la liste d'ajout), `rows: RaceRow[]`, `progression`, `onchanged: (row: StatActivity) => void`. Liste avec temps (« montre » en libellé discret si non officiel), allure, « Top 15 % » général et catégorie ; graphique de progression par catégorie ; bouton « Ajouter une compétition » ouvrant une liste des activités run / trail (plus récentes d'abord, champ de recherche filtrant sur nom ou date) ; « Modifier » ouvre `RaceEditDialog`.
  - `RaceEditDialog.svelte` props : `activity: StatActivity`, `onsaved: (a: StatActivity) => void`, `onclose: () => void`. Champs : épreuve, temps officiel (saisi `h:mm:ss`, envoyé en secondes), classement général / participants, catégorie, classement catégorie / effectif. « Enregistrer » → `api.saveRace` ; « Ce n'est pas une compétition » → `api.removeRace`. Erreurs de l'API affichées avec le composant `ErrorBanner` existant.
  - `Stats.svelte` remplace la ligne modifiée dans sa liste d'activités après `onchanged` (pas de rechargement complet).

- [ ] **Step 1: Tests qui échouent** dans `Stats.test.ts` :
  - `running block hidden when sport is bike`.
  - `records table formats times and links to Garmin` : record `5k` de 1234 s → « 20:34 » et lien contenant l'id.
  - `race edit saves official time` : ouvrir la compétition, saisir « 0:41:30 », enregistrer → `PUT /api/races/{id}` avec `official_time_s: 2490` et la ligne affiche « 41:30 ».
  - `unmarking a race removes it from the list` (`DELETE`).
  - `rank above total shows the API error` (réponse 422 simulée → message visible).

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/routes/Stats.test.ts` — attendu : FAIL.

- [ ] **Step 3: Implémenter.**

- [ ] **Step 4: Lancer** `cd web && npm test` — attendu : PASS.

- [ ] **Step 5: Vérifier dans l'app** (comme en Task 10) : marquer, modifier et dé-marquer une compétition ; records affichés.

- [ ] **Step 6: Commit** `feat(web): progression course, records et compétitions sur la page Stats`

---

### Task 12: Navigation, synchro sans objectif, relance de l'import, documentation

**Files:**
- Modify: `web/src/App.svelte`, `web/src/App.test.ts`, `web/src/routes/Setup.svelte`, `README.md`, `ROADMAP.md`

**Interfaces:**
- Consumes: `Status.has_activities`, `Status.history`, `api.importHistory` (Task 6) ; `Stats.svelte` (Task 10).
- Produces:
  - Route par défaut : `auth_required` → `#/setup` ; sinon `has_activities` → `#/stats` ; sinon `goal` → `#/plan` ; sinon `#/goal`.
  - Synchro automatique dès que `garmin === "ok"` (plus besoin d'objectif) ; message pendant la synchro : « Analyse de ta séance par Claude… » si un objectif existe, « Synchronisation Garmin… » sinon.
  - Pendant `history.status === "running"`, `App` rappelle `api.status()` toutes les 5 s (intervalle arrêté dès que l'état change ou au démontage) et passe `history` à `Stats`. `onimport` → `api.importHistory()` puis `refresh()` ; un `409` est ignoré.
  - `Setup.svelte` : section « Historique Garmin » avec l'état (« {imported} activités importées », « Import en cours… », message d'erreur) et un bouton « Réimporter l'historique ».
  - `README.md` : une ligne dans la présentation sur la page Stats et l'import de l'historique ; `ROADMAP.md` : cocher la page de statistiques globales et la déplacer dans « Fait ».

- [ ] **Step 1: Tests qui échouent** dans `App.test.ts` :
  - `default route is stats when activities exist` (`has_activities: true`, hash vide → `#/stats`).
  - `default route stays plan without activities`.
  - `auto-sync runs without a goal and says Garmin` (`goal: null`, `garmin: "ok"` → un `POST /api/sync`, texte « Synchronisation Garmin… »).
  - Le test existant reste vert (adapter son `/api/status` simulé avec `has_activities: false` et `history` à `idle`).

- [ ] **Step 2: Lancer** `cd web && npx vitest run src/App.test.ts` — attendu : FAIL.

- [ ] **Step 3: Implémenter.**

- [ ] **Step 4: Vérification complète** `uv run pytest` puis `cd web && npm test && npm run build` — attendu : tout vert.

- [ ] **Step 5: Vérifier dans l'app** : base vide → synchro → import qui progresse dans le bandeau → arrivée sur `#/stats` au rechargement ; « Réimporter l'historique » depuis les Réglages ; arrêt du serveur pendant l'import puis relance → bandeau « Import interrompu » avec « Reprendre ».

- [ ] **Step 6: Commit** `feat: page Stats par défaut, synchro sans objectif, relance de l'import`
