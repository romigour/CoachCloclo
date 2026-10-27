# Coach — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Application locale (backend Python + front Svelte PWA) qui génère avec Claude un plan route/trail à partir des données Garmin, propose des ajustements après chaque synchro et exporte à la demande les séances dans le calendrier Garmin.

**Architecture:** Paquet Python `coach` (FastAPI + SQLModel/SQLite) servant aussi le front compilé. Python calcule (zones, GPX, rattachement), Claude décide (JSON strict validé par Pydantic), Python exécute (conversion et appels Garmin). Seuls `coach/garmin/` et `coach/llm/` font du réseau, derrière des interfaces remplaçables par des fakes.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLModel, Pydantic v2, garminconnect ≥ 0.3 (sans garth), gpxpy, platformdirs, Typer, anthropic (mode API), pytest ; Svelte 5 + Vite + Vitest ; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-27-coach-running-design.md`

## Global Constraints

- Python ≥ 3.12 ; `garminconnect>=0.3,<0.4` avec l'extra `workout` ; aucun import de `garth`.
- Tokens Garmin : `garmin.login(tokenstore)` avec `tokenstore = <data_dir>/garmin` (fichier `garmin_tokens.json`). Jamais de mot de passe persisté, ni en argument de ligne de commande, ni dans un log.
- Dates passées à garminconnect au format `'YYYY-MM-DD'` ; « aujourd'hui » = `garmin.today()` quand un client est disponible.
- Dossier de données : `platformdirs.user_data_dir("coach")`, surchargé par la variable d'environnement `COACH_HOME` (utilisée par tous les tests).
- Écoute sur `127.0.0.1:8765` par défaut ; `--lan` écoute sur `0.0.0.0` et exige le PIN.
- Claude : `claude -p` en sous-processus, prompt sur stdin, sortie JSON, outils désactivés, délai 180 s ; une seule nouvelle tentative sur réponse invalide.
- Types de séance : `EF`, `seuil`, `VMA`, `côtes`, `sortie_longue`, `récup`. Séances dures : `seuil`, `VMA`, `côtes`, `sortie_longue`.
- Statuts Session : `todo`, `exported`, `done`, `missed`, `sync_error`. Statuts Proposal : `pending`, `accepted`, `rejected`, `stale`.
- Interface et messages utilisateur en français.
- Nom de distribution `coach-running`, module `coach`, commande `coach`.
- Aucune écriture Garmin (upload/schedule/unschedule/delete) en dehors d'une action explicite de l'utilisateur (export, déplacement, retrait, acceptation d'une proposition).

## Review Focus

1. **Métriques Garmin absentes** (montre récente, pas de seuil lactique ni de zones FC) → zones de repli (Karvonen depuis FC max/repos, allure seuil depuis la prédiction 10 km) ; sans aucune donnée d'allure, les séances `pace` basculent en `hr`. Test dans la tâche 2.
2. **GPX invalide, vide ou sans altitude** → erreur claire (HTTP 422) pour un fichier illisible ; sans altitude, résumé avec `d_plus_m=None` et un avertissement, sans plantage. Test dans la tâche 3.
3. **Date de course passée ou trop proche** (moins de 14 jours) → objectif refusé avec un message clair. Test dans la tâche 11.
4. **Activités hors course ou plusieurs dans la même journée** (vélo, deux sorties) → le vélo est ignoré, chaque séance reçoit au plus une activité, celle dont la durée est la plus proche. Test dans la tâche 7.
5. **Réponse de Claude incohérente** (`session_id` inconnu, séance déjà `done` modifiée, plus de séances par semaine que demandé, zone d'allure sur une séance `hr`) → rejetée par la validation, puis une nouvelle tentative avec l'erreur. Test dans la tâche 4.

---

## File Structure

```
pyproject.toml                 uv/hatchling, deps, entry point coach = coach.cli:app
coach/config.py                chemins (data_dir, tokenstore, db, settings.json), Settings
coach/analysis/zones.py        Zones, compute_zones()
coach/analysis/gpx.py          GpxSummary, analyze_gpx()
coach/analysis/compliance.py   match_activities(), mark_missed(), hard_session_warnings()
coach/llm/schemas.py           StepSpec, RepeatSpec, SessionSpec, PlanResponse, AdjustmentResponse, validators
coach/llm/provider.py          LLMProvider, ClaudeCliProvider, AnthropicApiProvider, FakeLLMProvider, erreurs
coach/llm/client.py            ask_structured()
coach/llm/prompts.py           build_generation_prompt(), build_adjustment_prompt(), SYSTEM_PROMPT
coach/export/garmin_workout.py session_to_workout_json()
coach/plan/models.py           tables SQLModel
coach/plan/calendar.py         plan_start(), n_weeks(), week_monday()
coach/plan/repo.py             accès base
coach/garmin/port.py           GarminPort (Protocol), FakeGarminClient, ActivitySummary, Metrics
coach/garmin/client.py         GarminClient (implémentation réelle : auth, lecture, workouts)
coach/services/plans.py        create_goal(), generate_plan(), accept_plan()
coach/services/sync.py         sync()
coach/services/garmin_export.py export_session(), move_session(), unschedule_session(), apply_proposal()
coach/api/app.py               create_app(), routes, PIN
coach/doctor.py                Check, run_checks()
coach/cli.py                   start, doctor, login-garmin, update
web/                           Svelte + Vite, build → coach/web_dist/
install.ps1, install.sh        installeurs
.github/workflows/ci.yml       CI 3 OS
tests/…                        un fichier de test par module
```

---

### Task 1: Squelette du projet et configuration

**Files:**
- Create: `pyproject.toml`, `coach/__init__.py`, `coach/config.py`, `.gitignore`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `data_dir() -> Path`, `tokenstore_dir() -> Path`, `db_path() -> Path`, `class Settings(BaseModel)` (champs `llm_mode: Literal["cli","api"] = "cli"`, `anthropic_api_key: str | None = None`, `anthropic_model: str = "claude-sonnet-5-5"`, `pin_hash: str | None = None`, `last_sync_at: datetime | None = None`), `load_settings() -> Settings`, `save_settings(s: Settings) -> None` (fichier en `0600` sur POSIX). Fixture pytest `coach_home` qui pointe `COACH_HOME` vers `tmp_path`.

- [ ] **Step 1: Write the failing tests**

```python
def test_data_dir_uses_coach_home(coach_home):
    assert data_dir() == coach_home
    assert tokenstore_dir() == coach_home / "garmin"
    assert db_path() == coach_home / "coach.db"

def test_settings_roundtrip(coach_home):
    s = load_settings()
    assert s.llm_mode == "cli"
    s.llm_mode = "api"; save_settings(s)
    assert load_settings().llm_mode == "api"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -v` → FAIL (module absent)
- [ ] **Step 3: Implement** `pyproject.toml` (deps de la Tech Stack, groupe dev : pytest, httpx ; marker `live` déclaré et exclu par défaut via `addopts = "-m 'not live'"`), `coach/config.py`, `.gitignore` (inclut `garmin_tokens.json`, `coach/web_dist/`, `node_modules/`). Les dossiers sont créés à la demande.
- [ ] **Step 4: Run** `uv run pytest -v` → PASS
- [ ] **Step 5: Commit** `git commit -m "chore: squelette du projet et configuration"`

---

### Task 2: Zones d'entraînement

**Files:**
- Create: `coach/analysis/__init__.py`, `coach/analysis/zones.py`
- Test: `tests/analysis/test_zones.py`

**Interfaces:**
- Produces:
  - `PaceZoneName = Literal["récup","EF","marathon","seuil","VMA"]`, `HrZoneName = Literal["Z1","Z2","Z3","Z4","Z5"]`
  - `class Zones(BaseModel)`: `pace: dict[PaceZoneName, tuple[int,int]] | None` (secondes/km, borne rapide puis lente), `hr: dict[HrZoneName, tuple[int,int]]` (bpm), `source: list[str]`
  - `compute_zones(*, threshold_pace_s_km: int | None, pred_10k_s: int | None, garmin_hr_zones: list[int] | None, hr_max: int | None, hr_rest: int | None) -> Zones`

Règles (valeurs fixées ici, à utiliser telles quelles) :
- Allure seuil T = `threshold_pace_s_km`, sinon `round(pred_10k_s / 10 * 1.04)`, sinon `pace=None`.
- Zones d'allure en multiples de T (borne rapide, borne lente) : récup (1.30, 1.45), EF (1.20, 1.32), marathon (1.06, 1.12), seuil (0.98, 1.03), VMA (0.88, 0.93), arrondies à la seconde.
- FC : `garmin_hr_zones` = 5 bornes basses Z1..Z5 + borne haute = `hr_max` ; sinon Karvonen avec réserve R = max − repos : Z1 50–60 %, Z2 60–70 %, Z3 70–80 %, Z4 80–90 %, Z5 90–100 % de R, plus le repos. Sans `hr_max` ni zones Garmin → `ValueError("FC max inconnue")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_pace_zones_from_threshold():
    z = compute_zones(threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=[100,120,140,160,175], hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (235, 247)
    assert z.pace["EF"] == (288, 317)
    assert z.hr["Z2"] == (120, 140) and z.hr["Z5"] == (175, 190)

def test_fallback_threshold_from_10k_prediction():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=2400, garmin_hr_zones=None, hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (245, 258)          # T = 250, round(257.5) = 258
    assert z.hr["Z2"] == (134, 148)               # Karvonen

def test_no_pace_data_gives_none():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50)
    assert z.pace is None

def test_missing_hr_max_raises():
    with pytest.raises(ValueError):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=None, hr_max=None, hr_rest=50)
```

- [ ] **Step 2: Run** `uv run pytest tests/analysis/test_zones.py -v` → FAIL
- [ ] **Step 3: Implement** `compute_zones` selon les règles ci-dessus ; `source` liste l'origine retenue (`"lactate_threshold"`, `"race_prediction_10k"`, `"garmin_hr_zones"`, `"karvonen"`).
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(analysis): zones d'allure et de FC avec replis"`

---

### Task 3: Analyse GPX

**Files:**
- Create: `coach/analysis/gpx.py`, `tests/fixtures/gpx/climb.gpx` (trace synthétique : 10 km, 2 montées de 300 m sur 3 km), `tests/fixtures/gpx/flat_no_ele.gpx`, `tests/fixtures/gpx/broken.gpx`
- Test: `tests/analysis/test_gpx.py`

**Interfaces:**
- Produces:
  - `class Climb(BaseModel)`: `start_km: float`, `length_km: float`, `gain_m: int`, `avg_grade_pct: float`
  - `class GpxSummary(BaseModel)`: `distance_km: float`, `d_plus_m: int | None`, `d_minus_m: int | None`, `max_ele_m: int | None`, `climbs: list[Climb]`, `warnings: list[str]`
  - `class GpxError(ValueError)`
  - `analyze_gpx(data: bytes) -> GpxSummary`
  - `summary_to_text(s: GpxSummary) -> str` (texte français compact envoyé à Claude)

Règles : altitude lissée par moyenne glissante sur 5 points ; D+ = somme des hausses du profil lissé ; une montée = segment continu dont le gain dépasse 50 m, et elle se termine après une descente de plus de 20 m. Moins de 2 points ou XML invalide → `GpxError("Fichier GPX illisible ou vide")`. Sans altitude → `d_plus_m=None`, `climbs=[]`, avertissement « Trace sans altitude : D+ à saisir manuellement ».

- [ ] **Step 1: Write the failing tests**

```python
def test_climb_fixture():
    s = analyze_gpx(FIX("climb.gpx"))
    assert s.distance_km == pytest.approx(10.0, abs=0.2)
    assert s.d_plus_m == pytest.approx(600, abs=30)
    assert len(s.climbs) == 2 and s.climbs[0].avg_grade_pct == pytest.approx(10, abs=1.5)

def test_no_elevation_warns():
    s = analyze_gpx(FIX("flat_no_ele.gpx"))
    assert s.d_plus_m is None and s.warnings

def test_broken_raises():
    with pytest.raises(GpxError):
        analyze_gpx(FIX("broken.gpx"))
    with pytest.raises(GpxError):
        analyze_gpx(b"")

def test_summary_text_mentions_climbs():
    assert "montée" in summary_to_text(analyze_gpx(FIX("climb.gpx")))
```

- [ ] **Step 2: Run** `uv run pytest tests/analysis/test_gpx.py -v` → FAIL
- [ ] **Step 3: Implement** avec `gpxpy` (distance par `gpxpy.geo.distance` entre points consécutifs). Les fixtures sont générées par un petit script lancé une fois, puis committées.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(analysis): analyse de trace GPX"`

---

### Task 4: Schémas des réponses de Claude et validation métier

**Files:**
- Create: `coach/llm/__init__.py`, `coach/llm/schemas.py`
- Test: `tests/llm/test_schemas.py`

**Interfaces:**
- Consumes: `PaceZoneName`, `HrZoneName` (tâche 2).
- Produces:
  - `SessionType = Literal["EF","seuil","VMA","côtes","sortie_longue","récup"]`, `HARD_TYPES: frozenset[str]`
  - `Weekday = Literal["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]`
  - `StepSpec`: `kind: Literal["warmup","active","recovery","cooldown"]`, `duration_s: int | None`, `distance_m: int | None`, `zone: PaceZoneName | HrZoneName | None` ; validator : exactement un des deux champs `duration_s`/`distance_m`.
  - `RepeatSpec`: `repeat: int` (2..30), `steps: list[StepSpec]` (min 1)
  - `SessionSpec`: `week_index: int` (≥ 1), `order: int` (≥ 1), `suggested_day: Weekday`, `type: SessionType`, `target_kind: Literal["pace","hr"]`, `title: str`, `description: str`, `chaining_note: str | None`, `steps: list[StepSpec | RepeatSpec]` (min 1) ; validator : les zones utilisées correspondent à `target_kind` (zones d'allure ↔ `pace`, Z1–Z5 ↔ `hr`).
  - `WeekSpec`: `week_index: int`, `focus: str`, `sessions: list[SessionSpec]`
  - `PlanResponse`: `summary: str`, `weeks: list[WeekSpec]`
  - `Change`: `op: Literal["modify","add","remove"]`, `session_id: int | None`, `session: SessionSpec | None`, `reason: str` ; validator : `modify` → les deux renseignés, `add` → `session` seul, `remove` → `session_id` seul.
  - `AdjustmentResponse`: `analysis: str`, `changes: list[Change]`
  - `validate_plan(plan: PlanResponse, *, n_weeks: int, sessions_per_week: int, pace_available: bool) -> list[str]` : erreurs en français. Règles : semaines numérotées 1..n_weeks sans trou ; au plus `sessions_per_week` séances par semaine ; `order` unique par semaine ; si `pace_available` est faux, aucune séance `pace`.
  - `validate_adjustment(adj: AdjustmentResponse, *, editable_ids: set[int], current_week: int, sessions_per_week: int, counts_by_week: dict[int,int], pace_available: bool) -> list[str]` : `session_id` ∈ `editable_ids` (séances `todo` ou `exported`) ; un `add` n'est pas placé avant `current_week` ; après application, aucune semaine ne dépasse `sessions_per_week` ; règle `pace_available` identique.

- [ ] **Step 1: Write the failing tests**

```python
def test_step_requires_exactly_one_length():
    with pytest.raises(ValidationError): StepSpec(kind="active", duration_s=60, distance_m=200, zone="VMA")
    with pytest.raises(ValidationError): StepSpec(kind="active", zone="VMA")

def test_zone_must_match_target_kind():
    with pytest.raises(ValidationError):
        make_session(target_kind="hr", steps=[StepSpec(kind="active", duration_s=600, zone="seuil")])

def test_validate_plan_too_many_sessions():
    plan = make_plan(n_weeks=2, per_week=[3, 4])
    assert any("semaine 2" in e for e in validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True))

def test_validate_plan_pace_without_data():
    assert validate_plan(make_plan(n_weeks=1, per_week=[1], target_kind="pace"), n_weeks=1, sessions_per_week=3, pace_available=False)

def test_validate_adjustment_rejects_unknown_or_done_session():
    adj = AdjustmentResponse(analysis="x", changes=[Change(op="remove", session_id=99, reason="r")])
    assert validate_adjustment(adj, editable_ids={1, 2}, current_week=3, sessions_per_week=4, counts_by_week={3: 4}, pace_available=True)

def test_validate_adjustment_rejects_add_in_past_week():
    adj = AdjustmentResponse(analysis="x", changes=[Change(op="add", session=make_session(week_index=2), reason="r")])
    assert validate_adjustment(adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={}, pace_available=True)
```

`make_session` et `make_plan` sont des helpers de test placés dans `tests/llm/factories.py`, réutilisés par les tâches suivantes.

- [ ] **Step 2: Run** `uv run pytest tests/llm/test_schemas.py -v` → FAIL
- [ ] **Step 3: Implement** `coach/llm/schemas.py`
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(llm): schémas de réponse et validation métier"`

---

### Task 5: Conversion d'une séance en workout Garmin

**Files:**
- Create: `coach/export/__init__.py`, `coach/export/garmin_workout.py`, `tests/fixtures/garmin/workout_intervals.json`
- Test: `tests/export/test_garmin_workout.py`

**Interfaces:**
- Consumes: `SessionSpec`, `StepSpec`, `RepeatSpec` (tâche 4), `Zones` (tâche 2).
- Produces: `session_to_workout_json(session: SessionSpec, zones: Zones, *, name: str) -> dict` (dict prêt pour `Garmin.upload_workout`).

Correspondances (JSON workout Garmin) :
- Racine : `workoutName=name`, `sportType={"sportTypeId":1,"sportTypeKey":"running"}`, un seul `workoutSegments[0]` avec `segmentOrder=1`.
- Étape → `{"type":"ExecutableStepDTO","stepOrder":n,"stepType":{...}}`. stepType : warmup 1, cooldown 2, active→interval 3, recovery 4. Un `RepeatSpec` devient `{"type":"RepeatGroupDTO","stepType":{"stepTypeId":6,"stepTypeKey":"repeat"},"numberOfIterations":r,"workoutSteps":[...]}`. `stepOrder` est numéroté globalement, en ordre de parcours.
- Fin : `duration_s` → `endCondition={"conditionTypeId":2,"conditionTypeKey":"time"}`, `endConditionValue=s` ; `distance_m` → `{"conditionTypeId":3,"conditionTypeKey":"distance"}`, valeur en mètres.
- Cible : allure → `targetType={"workoutTargetTypeId":6,"workoutTargetTypeKey":"pace.zone"}`, `targetValueOne`/`targetValueTwo` en **m/s** (`1000 / s_km`, borne lente en premier) ; FC → `{"workoutTargetTypeId":4,"workoutTargetTypeKey":"heart.rate.zone"}` avec les bpm ; sans zone → `{"workoutTargetTypeId":1,"workoutTargetTypeKey":"no.target"}`.

- [ ] **Step 1: Capture the reference fixture (live, once)** : crée manuellement dans Garmin Connect un workout « 15 min échauffement / 6×400 m allure / 200 m récup / 10 min retour au calme », puis `g.get_workout_by_id(id)`. Sauvegarde le JSON anonymisé dans `tests/fixtures/garmin/workout_intervals.json`, et vérifie les identifiants ci-dessus avec `g.get_workout_types()`. **Si un identifiant diffère, la fixture fait foi** : corrige le tableau de correspondances de cette tâche.
- [ ] **Step 2: Write the failing tests**

```python
def test_intervals_match_reference_structure():
    out = session_to_workout_json(INTERVALS_SESSION, ZONES, name="S3 – VMA")
    ref = load_fixture("workout_intervals.json")
    assert shape(out["workoutSegments"][0]["workoutSteps"]) == shape(ref["workoutSegments"][0]["workoutSteps"])
    # shape() garde type, stepType.stepTypeKey, endCondition.conditionTypeKey, targetType.workoutTargetTypeKey, numberOfIterations

def test_pace_target_in_m_per_s_slow_first():
    step = first_active(session_to_workout_json(INTERVALS_SESSION, ZONES, name="x"))
    assert step["targetValueOne"] == pytest.approx(1000 / 223, rel=1e-3)   # borne lente de VMA si T=240
    assert step["targetValueOne"] < step["targetValueTwo"]

def test_hr_target_uses_bpm():
    step = first_active(session_to_workout_json(EF_HR_SESSION, ZONES, name="x"))
    assert (step["targetValueOne"], step["targetValueTwo"]) == ZONES.hr["Z2"]
```

- [ ] **Step 3: Run** `uv run pytest tests/export -v` → FAIL
- [ ] **Step 4: Implement** `session_to_workout_json`
- [ ] **Step 5: Run** → PASS
- [ ] **Step 6: Commit** `git commit -m "feat(export): conversion séance → workout Garmin"`

---

### Task 6: Modèle de données, calendrier du plan et dépôt

**Files:**
- Create: `coach/plan/__init__.py`, `coach/plan/models.py`, `coach/plan/calendar.py`, `coach/plan/repo.py`
- Test: `tests/plan/test_calendar.py`, `tests/plan/test_repo.py`

**Interfaces:**
- Produces:
  - Tables SQLModel conformes à la section 4 de la spec, plus :
    - `Goal.plan_start: date` (lundi de la semaine de création) et `Goal.plan_accepted: bool` ;
    - `Session.title`, `Session.description`, `Session.steps_json` (les `steps` du `SessionSpec`), `Session.garmin_workout_id: int | None`, `Session.garmin_schedule_id: int | None`, `Session.sync_error: str | None` ;
    - `Activity.duration_s`, `Activity.distance_m`, `Activity.d_plus_m`, `Activity.avg_hr`, `Activity.raw_json`.
  - `Session.to_spec() -> SessionSpec`, `Session.from_spec(spec: SessionSpec, goal_id: int) -> Session`.
  - `plan_start(today: date) -> date` (lundi de la semaine), `n_weeks(start: date, race_date: date) -> int` (la dernière semaine contient la course), `week_monday(goal: Goal, week_index: int) -> date`, `week_of(goal: Goal, d: date) -> int`.
  - `class Repo` (constructeur `Repo(engine)`, `make_engine(path: Path) -> Engine`) : `active_goal() -> Goal | None`, `add(obj) -> obj`, `sessions(goal_id, week_index: int | None = None) -> list[Session]`, `session(id) -> Session`, `activities_since(d: date) -> list[Activity]`, `activity_by_garmin_id(gid: int) -> Activity | None`, `pending_proposal() -> Proposal | None`, `latest_snapshot() -> AthleteSnapshot | None`, `transaction()` (context manager).

- [ ] **Step 1: Write the failing tests**

```python
def test_n_weeks_race_on_sunday():
    assert n_weeks(date(2026,10,26), date(2027,1,31)) == 14

def test_week_monday_and_week_of():
    g = Goal(plan_start=date(2026,10,26), race_date=date(2027,1,31), ...)
    assert week_monday(g, 3) == date(2026,11,9)
    assert week_of(g, date(2026,11,12)) == 3

def test_session_spec_roundtrip(repo):
    spec = make_session(week_index=2)
    s = repo.add(Session.from_spec(spec, goal_id=1))
    assert repo.session(s.id).to_spec() == spec

def test_single_pending_proposal(repo):
    repo.add(Proposal(status="pending", analysis="a", changes_json="[]"))
    assert repo.pending_proposal().analysis == "a"
```

- [ ] **Step 2: Run** `uv run pytest tests/plan -v` → FAIL
- [ ] **Step 3: Implement** les modèles, le calendrier et le dépôt (fixture `repo` dans `tests/conftest.py`, sur une base SQLite temporaire).
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(plan): modèle de données, calendrier et dépôt"`

---

### Task 7: Rattachement des activités, séances manquées et avertissement 48 h

**Files:**
- Create: `coach/analysis/compliance.py`
- Test: `tests/analysis/test_compliance.py`

**Interfaces:**
- Consumes: `Session`, `Activity`, `Goal`, `week_of` (tâche 6), `HARD_TYPES` (tâche 4).
- Produces:
  - `RUNNING_TYPES = {"running","trail_running","treadmill_running","track_running"}`
  - `match_activities(sessions: list[Session], activities: list[Activity], goal: Goal) -> list[tuple[int, int]]` : paires `(session_id, activity_id)`. Ne fait aucune écriture.
  - `mark_missed(sessions: list[Session], goal: Goal, today: date) -> list[int]` : ids des séances `todo` ou `exported` d'une semaine entièrement passée (le dimanche avant `today`) et sans activité.
  - `hard_session_warnings(session: Session, target: date, others: list[Session]) -> list[str]`

Règles :
- Seules les activités dont le type est dans `RUNNING_TYPES` et qui ne sont pas encore rattachées sont prises en compte.
- Les séances `exported` sont traitées en premier : candidates à `scheduled_date` ±1 jour ; on prend l'écart de date minimal, puis l'écart de durée minimal.
- Les séances `todo` viennent ensuite : candidates dans la même semaine (`week_of`) ; on prend l'écart minimal `|duration_s/60 − est_duration_min|`.
- Une activité ne sert qu'une fois.
- Avertissement : `session.type` dans `HARD_TYPES` et une autre séance `exported` de type dur avec `|Δjours| < 2` → « Séance dure à moins de 48 h de « <titre> » (<date>) ».

- [ ] **Step 1: Write the failing tests**

```python
def test_exported_session_matches_adjacent_day(): ...
    # séance exportée le mardi, activité le mercredi → rattachée

def test_cycling_ignored(): ...
    # seule activité = cycling le jour prévu → aucune paire

def test_two_runs_same_day_pick_closest_duration():
    # séance 45 min ; activités de 20 et 50 min le même jour → celle de 50 min

def test_todo_session_matches_within_week_only(): ...

def test_activity_used_once(): ...

def test_mark_missed_only_finished_weeks():
    # today = mercredi semaine 3 → les todo de semaine 2 sans activité sont missed, pas celles de semaine 3

def test_warning_consecutive_hard_days():
    assert hard_session_warnings(vma, date(2026,11,11), [seuil_exported_on(date(2026,11,10))])
    assert not hard_session_warnings(vma, date(2026,11,12), [seuil_exported_on(date(2026,11,10))])
    assert not hard_session_warnings(ef, date(2026,11,11), [seuil_exported_on(date(2026,11,10))])
```

Chaque test est écrit complètement, avec ses objets construits via `tests/plan/factories.py`.

- [ ] **Step 2: Run** `uv run pytest tests/analysis/test_compliance.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(analysis): rattachement des activités et avertissement 48 h"`

---

### Task 8: Fournisseurs LLM et appel structuré avec nouvelle tentative

**Files:**
- Create: `coach/llm/provider.py`, `coach/llm/client.py`
- Test: `tests/llm/test_provider.py`, `tests/llm/test_client.py`

**Interfaces:**
- Produces:
  - Erreurs : `LLMError` → `LLMUnavailable` (CLI absent ou non connecté), `LLMUsageLimit`, `LLMTimeout`, `LLMInvalidResponse`.
  - `class LLMProvider(Protocol)`: `def complete(self, system: str, prompt: str) -> str`
  - `ClaudeCliProvider(executable: str = "claude", timeout_s: int = 180, runner=subprocess.run)` : exécute `[executable, "-p", "--output-format", "json", "--system-prompt", system, "--tools", ""]` avec `input=prompt`. Lit l'enveloppe JSON : `is_error` vrai et texte contenant « limit » → `LLMUsageLimit` ; sinon `is_error` → `LLMError`. Renvoie `result`. `TimeoutExpired` → `LLMTimeout` ; `FileNotFoundError` → `LLMUnavailable`.
  - `AnthropicApiProvider(api_key: str, model: str)` : `client.messages.create(model=…, max_tokens=16000, system=system, messages=[{"role":"user","content":prompt}])`, puis concaténation des blocs texte.
  - `FakeLLMProvider(responses: list[str])` : renvoie les réponses dans l'ordre et enregistre les prompts dans `.calls`.
  - `provider_from_settings(s: Settings) -> LLMProvider`
  - `ask_structured(provider: LLMProvider, system: str, prompt: str, model: type[T], validate: Callable[[T], list[str]] = lambda _: []) -> T` : extrait le premier objet JSON du texte (blocs de code ```json acceptés), applique `model.model_validate`, puis `validate`. Si ça échoue, un seul second appel avec le prompt suivi de « Ta réponse précédente est invalide : <erreurs>. Renvoie uniquement le JSON corrigé. ». Second échec → `LLMInvalidResponse(errors)`.

- [ ] **Step 1: Verify CLI flags** : `claude --help`. Vérifie que `-p`, `--output-format json`, `--system-prompt` et `--tools` existent. Si `--tools ""` n'existe pas, remplace-le par `--disallowedTools` suivi de la liste des outils intégrés donnée par l'aide. Note le choix retenu dans la docstring de la classe.
- [ ] **Step 2: Write the failing tests**

```python
def test_cli_provider_parses_envelope():
    run = fake_run(stdout=json.dumps({"type":"result","is_error":False,"result":"{\"a\":1}"}))
    assert ClaudeCliProvider(runner=run).complete("sys", "p") == '{"a":1}'
    assert run.kwargs["input"] == "p" and "--output-format" in run.args

def test_cli_usage_limit():
    run = fake_run(stdout=json.dumps({"is_error":True,"result":"Claude usage limit reached"}))
    with pytest.raises(LLMUsageLimit): ClaudeCliProvider(runner=run).complete("s","p")

def test_cli_missing_and_timeout(): ...   # FileNotFoundError → LLMUnavailable ; TimeoutExpired → LLMTimeout

def test_ask_structured_retries_once_with_errors():
    fake = FakeLLMProvider(["pas du json", '```json\n{"analysis":"ok","changes":[]}\n```'])
    out = ask_structured(fake, "s", "p", AdjustmentResponse)
    assert out.analysis == "ok" and "invalide" in fake.calls[1]

def test_ask_structured_gives_up_after_second_failure():
    with pytest.raises(LLMInvalidResponse):
        ask_structured(FakeLLMProvider(["x", "y"]), "s", "p", AdjustmentResponse)

def test_business_validation_triggers_retry():
    fake = FakeLLMProvider(['{"analysis":"a","changes":[]}', '{"analysis":"b","changes":[]}'])
    calls = iter([["erreur"], []])
    assert ask_structured(fake, "s", "p", AdjustmentResponse, validate=lambda _: next(calls)).analysis == "b"
```

- [ ] **Step 3: Run** `uv run pytest tests/llm -v` → FAIL
- [ ] **Step 4: Implement**
- [ ] **Step 5: Run** → PASS
- [ ] **Step 6: Add live test** `tests/llm/test_live.py::test_cli_roundtrip` (`@pytest.mark.live`) : `ask_structured(ClaudeCliProvider(), …, AdjustmentResponse)` sur un petit prompt, puis `uv run pytest -m live tests/llm/test_live.py -v` → PASS sur la machine du développeur.
- [ ] **Step 7: Commit** `git commit -m "feat(llm): fournisseurs CLI/API et appel structuré"`

---

### Task 9: Prompts de génération et d'ajustement

**Files:**
- Create: `coach/llm/prompts.py`
- Test: `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes: `Goal`, `Session`, `Activity`, `AthleteSnapshot` (tâche 6), `Zones` (tâche 2), `summary_to_text` (tâche 3).
- Produces:
  - `SYSTEM_PROMPT: str` : rôle d'entraîneur running/trail. Il impose de répondre uniquement en JSON conforme, de n'utiliser que les noms de zones fournis et jamais de valeurs chiffrées d'allure ou de FC, de choisir `pace` pour la route et le fractionné sur plat et `hr` pour le trail, les côtes et l'EF, et d'écrire les textes en français.
  - `build_generation_prompt(goal: Goal, zones: Zones, history: list[Activity], n_weeks: int, gpx_text: str | None) -> str`
  - `build_adjustment_prompt(goal: Goal, zones: Zones, current_week: int, done: list[tuple[Session, Activity]], missed: list[Session], upcoming: list[Session], history: list[Activity]) -> str`

Chaque prompt se termine par le schéma JSON attendu (`PlanResponse.model_json_schema()` ou `AdjustmentResponse.model_json_schema()`). Les séances à venir sont listées avec leur `id`, leur statut et leur `scheduled_date`. L'historique est résumé à une ligne par activité (date, type, durée, distance, D+, FC moyenne) sur 8 semaines.

- [ ] **Step 1: Write the failing tests**

```python
def test_generation_prompt_contains_constraints():
    p = build_generation_prompt(goal_trail, zones, history, n_weeks=14, gpx_text="2 montées…")
    for needle in ["14 semaines", "3 séances", "trail", "2 montées", '"weeks"', "Z2"]:
        assert needle in p

def test_generation_prompt_without_pace_zones_forbids_pace():
    assert "Aucune zone d'allure" in build_generation_prompt(goal_route, zones_no_pace, [], n_weeks=8, gpx_text=None)

def test_adjustment_prompt_lists_ids_and_status():
    p = build_adjustment_prompt(goal, zones, 4, done=[(s1, a1)], missed=[s2], upcoming=[s3, s4], history=[])
    assert f"id={s3.id}" in p and "exported" in p and '"changes"' in p

def test_system_prompt_forbids_raw_values():
    assert "jamais de valeur" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run** `uv run pytest tests/llm/test_prompts.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(llm): prompts de génération et d'ajustement"`

---

### Task 10: Client Garmin (port, fake et implémentation réelle)

**Files:**
- Create: `coach/garmin/__init__.py`, `coach/garmin/port.py`, `coach/garmin/client.py`
- Test: `tests/garmin/test_client.py` (tests unitaires sur une fausse instance de `Garmin`), `tests/garmin/test_live.py` (marqué `live`)

**Interfaces:**
- Produces:
  - `class GarminAuthRequired(Exception)`, `class GarminRateLimited(Exception)`, `class GarminUnavailable(Exception)`
  - `class Metrics(BaseModel)`: `vo2max`, `hr_max`, `hr_rest`, `threshold_hr`, `threshold_pace_s_km`, `pred_10k_s`, `hr_zones: list[int] | None` (tous optionnels)
  - `class ActivitySummary(BaseModel)`: `garmin_id: int`, `date: date`, `type_key: str`, `duration_s: int`, `distance_m: int`, `d_plus_m: int | None`, `avg_hr: int | None`, `raw: dict`
  - `class GarminPort(Protocol)` : `today() -> date`, `metrics() -> Metrics`, `activities(start: date, end: date) -> list[ActivitySummary]`, `upload_workout(workout: dict) -> int`, `schedule(workout_id: int, d: date) -> int` (renvoie l'id planifié), `reschedule(schedule_id: int, d: date) -> None`, `unschedule(schedule_id: int) -> None`, `delete_workout(workout_id: int) -> None`
  - `FakeGarminClient` : état en mémoire (`.workouts`, `.calendar`) et option `fail_on: set[str]` pour injecter des erreurs. Utilisé dans les tests des services.
  - `class GarminClient(GarminPort)` : `GarminClient.from_tokens(tokenstore: Path) -> GarminClient` (lève `GarminAuthRequired`), `start_login(email: str, password: str, tokenstore: Path) -> tuple[Literal["ok","needs_mfa"], GarminClient | dict]`, `finish_login(state: dict, code: str, tokenstore: Path) -> GarminClient`

Appels garminconnect à utiliser :
- Authentification : `Garmin().login(str(tokenstore))` ; `Garmin(email, pwd, return_on_mfa=True).login(str(tokenstore))` → `("needs_mfa", state)` ; `Garmin().resume_login(state, code)`.
- Lecture : `get_max_metrics_latest()`, `get_lactate_threshold(latest=True)`, `get_heart_rates(day)` (`restingHeartRate`), `get_heart_rate_zones_v2()`, `get_race_predictions()`, `get_activities_by_date(start, end)`.
- Workouts : `upload_workout(dict)`, `schedule_workout(id, "YYYY-MM-DD")`, `reschedule_workout(sid, d)`, `unschedule_workout(sid)`, `delete_workout(id)`.
- Erreurs : `GarminConnectAuthenticationError` → `GarminAuthRequired` ; `GarminConnectTooManyRequestsError` → une seule nouvelle tentative après 5 s, puis `GarminRateLimited` ; `GarminConnectConnectionError` → `GarminUnavailable`.

- [ ] **Step 1: Inspect real payloads (live, once)** : appelle chaque méthode de lecture et note dans `tests/fixtures/garmin/` une réponse anonymisée par méthode, en tronquant les champs inutiles. Le parsing s'écrira contre ces fixtures, en utilisant `.get()` sur tous les champs.
- [ ] **Step 2: Write the failing tests**

```python
def test_metrics_parsing_from_fixtures(fake_garmin_lib):
    m = GarminClient(fake_garmin_lib).metrics()
    assert m.threshold_pace_s_km == FIXTURE_EXPECTED_THRESHOLD and m.hr_rest == FIXTURE_EXPECTED_REST

def test_metrics_tolerates_missing_data(fake_garmin_lib_empty):
    assert GarminClient(fake_garmin_lib_empty).metrics().threshold_pace_s_km is None

def test_activities_parsing(fake_garmin_lib):
    a = GarminClient(fake_garmin_lib).activities(date(2026,10,1), date(2026,10,27))[0]
    assert a.type_key == "running" and a.duration_s > 0

def test_rate_limit_retries_once_then_raises(fake_garmin_lib_429):
    with pytest.raises(GarminRateLimited): GarminClient(fake_garmin_lib_429, sleep=lambda s: None).activities(...)
    assert fake_garmin_lib_429.calls == 2

def test_auth_error_mapped(fake_garmin_lib_401): ...

def test_start_login_needs_mfa(monkeypatch): ...   # Garmin(...).login renvoie ("needs_mfa", {...})
```

- [ ] **Step 3: Run** `uv run pytest tests/garmin -v` → FAIL
- [ ] **Step 4: Implement** `port.py` (Protocol + Fake), puis `client.py`. Le constructeur prend une instance de `Garmin` et un `sleep` injectable.
- [ ] **Step 5: Run** → PASS
- [ ] **Step 6: Live test** : `test_live.py::test_read_only` lit les métriques et les activités des 30 derniers jours, sans aucune écriture. `test_live.py::test_workout_roundtrip` exige `COACH_LIVE_WRITE=1` : il envoie un workout de test, le planifie à J+30, le déplace, le retire, puis le supprime. Lancer `uv run pytest -m live tests/garmin -v` → PASS.
- [ ] **Step 7: Commit** `git commit -m "feat(garmin): client Garmin, port et fake"`

---

### Task 11: Service objectif et génération du plan

**Files:**
- Create: `coach/services/__init__.py`, `coach/services/context.py`, `coach/services/plans.py`
- Test: `tests/services/test_plans.py`

**Interfaces:**
- Consumes: tâches 2, 3, 4, 6, 8, 9, 10.
- Produces:
  - `class GoalInput(BaseModel)`: `type: Literal["route","trail"]`, `distance_km: float` (> 0), `d_plus_m: int` (≥ 0), `race_date: date`, `sessions_per_week: int` (2..7), `gpx: bytes | None`
  - `class GoalError(ValueError)`
  - `refresh_snapshot(repo: Repo, garmin: GarminPort) -> tuple[AthleteSnapshot, Zones]` (dans `context.py`, réutilisé par la tâche 12)
  - `create_goal(repo, garmin, data: GoalInput) -> Goal` : `race_date` à moins de 14 jours de `garmin.today()` → `GoalError("La course doit être dans au moins 14 jours")`. Archive l'objectif actif précédent et ses séances non exportées. Stocke le GPX dans `<data_dir>/gpx/<goal_id>.gpx` avec son résumé ; si le D+ du GPX existe et que `d_plus_m == 0`, il le remplace.
  - `generate_plan(repo, garmin, llm: LLMProvider, goal_id: int) -> PlanResponse` : supprime les séances `todo` d'un brouillon précédent, appelle `ask_structured(..., validate=validate_plan(...))` et enregistre les séances en `todo` avec `Goal.plan_accepted=False`.
  - `accept_plan(repo, goal_id: int) -> None` : passe `plan_accepted` à vrai. L'export reste ensuite possible.

- [ ] **Step 1: Write the failing tests**

```python
def test_race_too_close_rejected(repo, fake_garmin):
    with pytest.raises(GoalError): create_goal(repo, fake_garmin, goal_input(race_date=fake_garmin.today() + timedelta(days=10)))

def test_race_in_past_rejected(repo, fake_garmin): ...

def test_gpx_dplus_used_when_not_given(repo, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(d_plus_m=0, gpx=FIX("climb.gpx")))
    assert g.d_plus_m == pytest.approx(600, abs=30)

def test_generate_plan_persists_sessions(repo, fake_garmin):
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    generate_plan(repo, fake_garmin, llm, goal.id)
    assert len(repo.sessions(goal.id)) == 42 and all(s.status == "todo" for s in repo.sessions(goal.id))

def test_generate_plan_invalid_twice_raises_and_persists_nothing(repo, fake_garmin):
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, FakeLLMProvider(["{}", "{}"]), goal.id)
    assert repo.sessions(goal.id) == []

def test_new_goal_archives_previous(repo, fake_garmin): ...
```

`valid_plan_json` est ajouté à `tests/llm/factories.py`.

- [ ] **Step 2: Run** `uv run pytest tests/services/test_plans.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(services): objectif et génération du plan"`

---

### Task 12: Service de synchro et propositions

**Files:**
- Create: `coach/services/sync.py`
- Test: `tests/services/test_sync.py`

**Interfaces:**
- Consumes: tâches 6, 7, 8, 9, 10, `refresh_snapshot` (tâche 11).
- Produces:
  - `class SyncResult(BaseModel)`: `new_activities: int`, `matched: int`, `missed: int`, `proposal_id: int | None`
  - `sync(repo, garmin, llm, *, now: datetime) -> SyncResult`

Déroulé :
1. `refresh_snapshot`.
2. Activités de `last_sync_at − 2 jours` (ou 56 jours au premier passage) jusqu'à aujourd'hui, dédupliquées par `garmin_id`.
3. `match_activities` → séances `done` avec `match_source="auto"`.
4. `mark_missed` → séances `missed`.
5. S'il y a eu au moins un rattachement ou une séance manquée depuis la dernière proposition, et que le plan est accepté : la Proposal `pending` passe en `stale`, puis `ask_structured(..., AdjustmentResponse, validate=validate_adjustment(...))` produit une nouvelle Proposal `pending`.
6. `last_sync_at = now`.

Une erreur LLM ne doit pas annuler les étapes 2 à 4 : elle est propagée après leur commit.

- [ ] **Step 1: Write the failing tests**

```python
def test_sync_matches_and_creates_proposal(repo, fake_garmin, accepted_plan): ...
def test_sync_without_news_creates_no_proposal(repo, fake_garmin, accepted_plan):
    sync(...); r = sync(...)
    assert r.proposal_id is None and len(fake_llm.calls) == 1
def test_new_proposal_makes_previous_stale(repo, fake_garmin, accepted_plan): ...
def test_llm_failure_keeps_matching(repo, fake_garmin, accepted_plan):
    with pytest.raises(LLMUsageLimit): sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=...)
    assert any(s.status == "done" for s in repo.sessions(goal.id))
def test_no_proposal_before_plan_accepted(repo, fake_garmin, draft_plan): ...
def test_duplicate_activities_not_reimported(repo, fake_garmin, accepted_plan): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/services/test_sync.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(services): synchro Garmin et propositions d'ajustement"`

---

### Task 13: Export, déplacement, retrait et application d'une proposition

**Files:**
- Create: `coach/services/garmin_export.py`
- Test: `tests/services/test_garmin_export.py`

**Interfaces:**
- Consumes: tâches 5, 6, 7, 10.
- Produces:
  - `class ExportError(ValueError)`
  - `export_session(repo, garmin, session_id: int, d: date) -> list[str]` : `d` doit appartenir à la semaine de la séance (sinon `ExportError`). Enchaîne `upload_workout`, puis `schedule`, puis `status="exported"`, et renvoie les avertissements de `hard_session_warnings`. Nom du workout : `f"S{week_index} – {title}"`.
  - `check_export(repo, session_id: int, d: date) -> list[str]` : avertissements seuls, sans aucune écriture.
  - `move_session(repo, garmin, session_id: int, d: date) -> list[str]` : `reschedule`.
  - `unschedule_session(repo, garmin, session_id: int) -> None` : `unschedule`, puis `delete_workout`, puis `status="todo"`.
  - `apply_proposal(repo, garmin, proposal_id: int) -> list[int]` : applique les changements en base dans une transaction, puis s'occupe de Garmin pour chaque séance `exported` modifiée ou supprimée. Renvoie les ids passés en `sync_error`.
  - `reject_proposal(repo, proposal_id: int) -> None`
  - `retry_sync_error(repo, garmin, session_id: int) -> None`

Ordre sûr pour remplacer une séance exportée : `upload_workout(nouveau)`, puis `schedule(nouveau, même date)`, puis `unschedule(ancien)`, puis `delete_workout(ancien)`. Un échec avant le nouveau `schedule` laisse l'ancien en place : la séance passe en `sync_error`, avec le message enregistré et les nouvelles étapes déjà en base. Un échec pendant le nettoyage de l'ancien : la séance passe en `sync_error` avec l'id de l'ancien conservé pour `retry_sync_error`. Une séance `exported` supprimée par la proposition : `unschedule`, puis `delete`.

- [ ] **Step 1: Write the failing tests**

```python
def test_export_schedules_on_chosen_day(repo, fake_garmin, session_w3):
    export_session(repo, fake_garmin, session_w3.id, date(2026,11,10))
    assert fake_garmin.calendar == {date(2026,11,10): [ANY]} and repo.session(session_w3.id).status == "exported"

def test_export_outside_week_rejected(repo, fake_garmin, session_w3): ...
def test_export_returns_48h_warning(repo, fake_garmin, ...): ...
def test_move_and_unschedule(repo, fake_garmin, exported_session): ...
def test_apply_proposal_replaces_exported_at_same_date(repo, fake_garmin, exported_session, proposal_modify): ...
def test_replace_failure_keeps_old_workout(repo, fake_garmin_fail_on_schedule, exported_session, proposal_modify):
    ids = apply_proposal(...)
    assert ids == [exported_session.id] and OLD_WORKOUT_ID in fake_garmin.workouts
def test_reject_changes_nothing(repo, fake_garmin, proposal_modify): ...
def test_todo_change_makes_no_garmin_call(repo, fake_garmin, proposal_on_todo):
    apply_proposal(...); assert fake_garmin.calls == []
```

- [ ] **Step 2: Run** `uv run pytest tests/services/test_garmin_export.py -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(services): export Garmin et application des propositions"`

---

### Task 14: API FastAPI et protection par PIN

**Files:**
- Create: `coach/api/__init__.py`, `coach/api/app.py`, `coach/api/deps.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: services des tâches 11 à 13, `GarminClient` (tâche 10), `provider_from_settings` (tâche 8).
- Produces: `create_app(*, lan: bool, garmin_factory: Callable[[], GarminPort], llm_factory: Callable[[], LLMProvider]) -> FastAPI`. Les factories sont remplacées par les fakes dans les tests.

Routes (préfixe `/api`, JSON) :

| Méthode et chemin | Effet |
|---|---|
| `GET /status` | `{garmin: "ok"\|"auth_required", llm_mode, pending_proposal_id, goal}` |
| `POST /garmin/login` `{email,password}` | `{status:"ok"}` ou `{status:"needs_mfa", login_id}` (l'état MFA reste en mémoire serveur, avec un TTL de 10 min) |
| `POST /garmin/mfa` `{login_id, code}` | `{status:"ok"}` |
| `POST /goals` (multipart, GPX facultatif) | crée l'objectif ; `GoalError`/`GpxError` → 422 avec `{detail}` |
| `POST /goals/{id}/generate` | génère le brouillon de plan |
| `POST /goals/{id}/accept` | accepte le plan |
| `GET /plan` | objectif actif, puis semaines, puis séances avec `week_monday` |
| `GET /sessions/{id}/export-check?date=` | `{warnings}` |
| `POST /sessions/{id}/export` `{date}` | `{warnings}` |
| `POST /sessions/{id}/move` `{date}` · `POST /sessions/{id}/unschedule` · `POST /sessions/{id}/retry` | |
| `POST /activities/{id}/match` `{session_id \| null}` | correction manuelle (`match_source="manual"`) |
| `POST /sync` | `SyncResult` |
| `GET /proposals/pending` · `POST /proposals/{id}/accept` · `POST /proposals/{id}/reject` | |
| `POST /auth/pin` `{pin}` | pose un cookie de session (mode LAN) |
| `GET /settings` · `PUT /settings` `{llm_mode, anthropic_api_key?, anthropic_model?}` | choix CLI / clé API (la clé n'est jamais renvoyée par `GET`, seulement `has_api_key`) |

Correspondance des erreurs : `GarminAuthRequired` → 401 `{code:"garmin_auth"}` ; `GarminRateLimited` → 429 ; `LLMUsageLimit` → 429 `{code:"llm_limit"}` ; `LLMUnavailable` → 503 ; `LLMTimeout` et `LLMInvalidResponse` → 502 ; `ExportError` → 422.

PIN : en mode `lan`, toute route `/api/*` sauf `/auth/pin` exige le cookie, sinon 401 `{code:"pin_required"}`. Le hash est en PBKDF2-SHA256 (`hashlib.pbkdf2_hmac`, 200 000 itérations, sel aléatoire) et stocké dans `Settings.pin_hash`. Si `lan` est demandé sans PIN défini, `create_app` lève `ValueError`. Le mot de passe Garmin n'apparaît dans aucun log, et on vérifie qu'aucun logger ne reçoit le corps de `/garmin/login`.

Fichiers statiques : `coach/web_dist` est monté sur `/` avec `html=True` s'il existe.

- [ ] **Step 1: Write the failing tests** (avec `TestClient`, un fake Garmin et un fake LLM) :
  `test_status_reports_auth_required`, `test_login_mfa_flow`, `test_goal_too_close_returns_422`, `test_broken_gpx_returns_422`, `test_generate_accept_and_plan`, `test_export_check_returns_warnings`, `test_sync_returns_result`, `test_llm_limit_maps_to_429_with_code`, `test_lan_requires_pin`, `test_lan_without_pin_refuses_to_start`, `test_settings_never_returns_api_key`, `test_password_not_logged` (avec `caplog`, le mot de passe n'apparaît pas).
- [ ] **Step 2: Run** `uv run pytest tests/api -v` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -m "feat(api): routes FastAPI et protection PIN"`

---

### Task 15: Doctor et CLI

**Files:**
- Create: `coach/doctor.py`, `coach/cli.py`
- Test: `tests/test_doctor.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `class Check(BaseModel)`: `name: str`, `ok: bool`, `detail: str`, `fix_hint: str | None`, `fixable: bool`
  - `run_checks(*, live: bool = True, which=shutil.which, runner=subprocess.run, garmin_factory=..., llm_factory=...) -> list[Check]`. Vérifications dans l'ordre, avec ces noms exacts : `python`, `garminconnect`, `claude_cli`, `claude_auth`, `garmin_tokens`, `data_dir`, `port`. `claude_auth` et `garmin_tokens` ne font un appel réel que si `live` est vrai : un `complete` minimal renvoyant `{"ok":true}`, et `garmin.today()` suivi de `metrics()`.
  - `fix(check: Check) -> bool` : `claude_cli` lance l'installeur natif (`irm https://claude.ai/install.ps1 | iex` via `powershell -NoProfile -Command` sur Windows, `curl -fsSL https://claude.ai/install.sh | bash` ailleurs) ; `claude_auth` lance `claude` en interactif pour que l'utilisateur se connecte ; `garmin_tokens` lance `coach login-garmin` ; `data_dir` crée le dossier.
  - Commandes Typer :
    - `coach start [--lan] [--port 8765] [--no-browser]` : en `--lan` sans PIN, demande d'abord un PIN avec `typer.prompt(hide_input=True)`.
    - `coach doctor [--fix] [--offline]` : affiche ✓ ou ✗ avec le nom, le détail et l'indice de correction ; code retour 1 si une vérification échoue. `--offline` ne lance ni `claude_cli`, ni `claude_auth`, ni `garmin_tokens` : elles sont marquées `ok=True` avec le détail « non vérifié (hors ligne) ».
    - `coach login-garmin` : demande l'email, le mot de passe (`getpass`) puis le code MFA si besoin.
    - `coach update` : `uv tool upgrade coach-running`.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_claude_cli_reported():
    checks = run_checks(live=False, which=lambda n: None if n == "claude" else "/x")
    c = by_name(checks, "claude_cli"); assert not c.ok and c.fixable

def test_usage_limit_reported_on_auth_check():
    c = by_name(run_checks(llm_factory=lambda: FailingLLM(LLMUsageLimit())), "claude_auth")
    assert not c.ok and "limite" in c.detail

def test_garmin_auth_required_reported(): ...
def test_doctor_exit_code(cli_runner, monkeypatch): ...   # une vérification en échec → exit 1
def test_start_lan_prompts_pin(cli_runner, monkeypatch): ...
def test_offline_skips_network_checks(): ...   # aucun appel à which('claude'), runner ni factories
```

- [ ] **Step 2: Run** `uv run pytest tests/test_doctor.py tests/test_cli.py -v` → FAIL
- [ ] **Step 3: Implement** (`start` lance `uvicorn.run(create_app(...), host, port)`, puis `webbrowser.open`)
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Manual check** : `uv run coach doctor` sur la machine du développeur → toutes les lignes en ✓.
- [ ] **Step 6: Commit** `git commit -m "feat(cli): commandes start, doctor, login-garmin, update"`

---

### Task 16: Front Svelte (PWA)

**Files:**
- Create: `web/package.json`, `web/vite.config.ts` (`build.outDir = "../coach/web_dist"`, proxy `/api` vers `127.0.0.1:8765` en dev), `web/src/lib/api.ts`, `web/src/lib/dates.ts`, `web/src/App.svelte`, `web/src/routes/{Setup,Goal,Plan,Proposal}.svelte`, `web/src/components/{WeekView,SessionCard,ExportDialog,SyncButton,ErrorBanner}.svelte`, `web/public/manifest.webmanifest`, `web/public/icon-192.png`, `web/public/icon-512.png`, `web/src/sw.ts` (cache de la coquille uniquement : jamais `/api`)
- Test: `web/src/lib/dates.test.ts`, `web/src/components/ExportDialog.test.ts`

**Interfaces:**
- Consumes: routes de la tâche 14.
- Produces:
  - `weekDays(weekMonday: string): string[]` (7 dates ISO)
  - `defaultExportDate(weekMonday: string, suggestedDay: Weekday): string`
  - Composants :
    - `ExportDialog` : sélecteur limité aux 7 jours de la semaine de la séance, jour conseillé présélectionné. Il appelle `export-check` à chaque changement de date, affiche les avertissements sans bloquer, puis appelle `export`.
    - `SyncButton` : déclenché au montage de l'app et au clic, il affiche « Analyse de ta séance par Claude… » pendant l'appel.
    - `ErrorBanner` : `garmin_auth` ouvre `Setup`, `llm_limit` affiche « Limite Claude atteinte : réessaie plus tard ou passe en mode clé API », `pin_required` ouvre la saisie du PIN.

Écrans :
- **Setup** : résultats de `/status`, connexion Garmin avec étape MFA, choix du mode Claude (CLI ou clé API) via `/settings`.
- **Goal** : formulaire avec le GPX facultatif, puis génération et relecture du brouillon (semaines, séances, résumé), puis les boutons « Valider le plan » et « Régénérer ».
- **Plan** : vue par semaine, avec pour chaque séance son statut, Exporter, Déplacer, Retirer, Réessayer (si `sync_error`) et la correction du rattachement d'activité.
- **Proposal** : analyse, liste des changements avec leurs raisons, Accepter et Refuser.

- [ ] **Step 1: Write the failing tests**

```ts
test("weekDays returns monday..sunday", () => {
  expect(weekDays("2026-11-09")).toEqual(["2026-11-09","2026-11-10","2026-11-11","2026-11-12","2026-11-13","2026-11-14","2026-11-15"]);
});
test("defaultExportDate uses suggested day", () => {
  expect(defaultExportDate("2026-11-09", "jeudi")).toBe("2026-11-12");
});
test("ExportDialog shows warning but keeps button enabled", async () => {
  mockApi({ "export-check": { warnings: ["Séance dure à moins de 48 h"] } });
  render(ExportDialog, { session, weekMonday: "2026-11-09" });
  expect(await screen.findByText(/48 h/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Exporter" })).toBeEnabled();
});
test("ExportDialog offers only the 7 days of the week", ...);
```

- [ ] **Step 2: Run** `cd web && npm test` → FAIL
- [ ] **Step 3: Implement** `dates.ts`, `api.ts` (fetch typé ; un code d'erreur produit une `ApiError(code, detail)`), puis les composants et les écrans.
- [ ] **Step 4: Run** `npm test` → PASS ; `npm run build` produit `coach/web_dist/index.html`.
- [ ] **Step 5: Manual check** : `uv run coach start` avec un vrai compte → connexion, création d'un objectif trail avec GPX, génération, validation, export d'une séance au jour choisi (vérifier qu'elle apparaît dans le calendrier Garmin Connect), synchro, puis acceptation d'une proposition. Vérifier aussi que la PWA s'installe depuis le téléphone en `--lan`.
- [ ] **Step 6: Commit** `git commit -m "feat(web): interface Svelte PWA"`

---

### Task 17: Installeurs, empaquetage et CI

**Files:**
- Create: `install.ps1`, `install.sh`, `.github/workflows/ci.yml`, `README.md`
- Modify: `pyproject.toml` (hatch : `artifacts = ["coach/web_dist/**"]`)

**Interfaces:**
- Consumes: `coach doctor --fix`, `coach start` (tâche 15).

Comportement des installeurs (identique sur les deux scripts) :
1. Installe `uv` s'il est absent (`irm https://astral.sh/uv/install.ps1 | iex` ou `curl -LsSf https://astral.sh/uv/install.sh | sh`).
2. Lance `uv tool install --python 3.12 "${COACH_SOURCE:-coach-running}"` (en remplaçant par `--force` si l'outil est déjà installé).
3. Lance `coach doctor --fix`.
4. Si toutes les vérifications passent, lance `coach start` ; sinon affiche les lignes en échec et s'arrête avec le code 1.

Le script ne demande jamais d'identifiant lui-même : c'est `doctor --fix` qui délègue à `claude` et à `coach login-garmin`.

CI, avec une matrice `windows-latest`, `macos-latest`, `ubuntu-latest` :
1. `npm ci && npm test && npm run build` dans `web/` ;
2. `uv run pytest` (marker `live` exclu) ;
3. `uv build` ;
4. exécution de l'installeur de l'OS avec `COACH_SOURCE=<chemin de la wheel construite>` et la variable `COACH_INSTALL_NO_START=1`, puis `coach doctor --offline`, → exit 0.

- [ ] **Step 1: Write** `install.ps1`, `install.sh` et `ci.yml`.
- [ ] **Step 2: Run locally** `uv build`, puis `COACH_SOURCE=dist/coach_running-*.whl COACH_INSTALL_NO_START=1 ./install.sh` (ou l'équivalent PowerShell), puis `coach doctor --offline` → exit 0.
- [ ] **Step 3: Write** `README.md` : la commande d'installation en une ligne pour chaque OS, ce que vérifie `doctor`, l'option `--lan` et son PIN, l'emplacement des données et des tokens, et une note sur l'usage du CLI Claude avec son propre abonnement ou du mode clé API.
- [ ] **Step 4: Push and verify** que la CI est verte sur les 3 OS.
- [ ] **Step 5: Commit** `git commit -m "build: installeurs, empaquetage du front et CI"`
