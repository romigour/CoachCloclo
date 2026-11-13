# Plusieurs objectifs avec priorité — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre plusieurs objectifs de course à venir, chacun Principal / Secondaire / Plaisir, et un plan d'entraînement par cycles qui en tient compte.

**Architecture:** Une table `Cycle` reprend ce qui était « le plan » dans `Goal` (début, réglages, validation) ; séances et imprévus sont rattachés au cycle (`cycle_id`). Des règles pures (`coach/plan/goals.py`) calculent la fin du cycle, l'écart entre objectifs et l'effet d'un changement d'objectif ; les services orchestrent ajustement, régénération de la suite et clôture ; les prompts décrivent les objectifs du cycle et l'horizon.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLite, pytest (`uv run pytest`) ; Svelte 5 + TypeScript, vitest (`npm test` dans `web/`).

**Spec:** `docs/superpowers/specs/2026-11-13-multi-objectives-design.md`

## Global Constraints

- Priorités : `"principal" | "secondaire" | "plaisir"`, libellés **Principal**, **Secondaire**, **Plaisir** ; défaut `"principal"`.
- Écart minimal entre deux objectifs `active` non-Plaisir : **14 jours** (`MIN_GAP_DAYS = 14`).
- Message d'écart (exact) : `« {course} du {jj/mm/aaaa} ({Priorité}) est à {n} jours : passe l'un des deux en Plaisir ou déplace-le »` — sans les guillemets français.
- Premier objectif (aucun cycle actif) : course dans au moins 14 jours (`MIN_DAYS_BEFORE_RACE`, inchangé). Objectif ajouté à un cycle existant : date strictement après aujourd'hui.
- Un seul `Cycle` au statut `"active"` à la fois. `Goal.status` : `"active" | "done" | "archived"`.
- Rien n'est enregistré si Claude échoue lors d'un ajustement (même garantie que l'actuel `update_goal`).
- Séances `done`/`missed`/`exported`/`sync_error` jamais supprimées par un ajout ou une régénération ; seules les `todo` à venir sont remplacées.
- Textes visibles et prompts en français ; commentaires et docstrings en français comme le reste du code.
- Migrations additives et idempotentes dans `repo._migrate` (on ne supprime aucune colonne).

## Review Focus

1. **Base existante avec séances exportées et imprévus** : après migration, `/plan` montre les mêmes semaines, les mêmes séances (ids inchangés) et l'arrêt en cours. → test `test_migration_moves_goal_plan_to_cycle` (Task 1) et `test_status_after_migration` (Task 2).
2. **Changer la date d'un objectif vers un autre trop proche** : refusé comme à la création, rien n'est enregistré. → `test_update_goal_date_respects_gap` (Task 5).
3. **Retirer un objectif dont la stratégie Jour J est sur la montre** : le workout Garmin est supprimé avant l'archivage ; en cas d'erreur Garmin, l'objectif reste actif. → `test_remove_goal_withdraws_race_workout` et `test_remove_goal_garmin_error_keeps_goal` (Task 5).
4. **Course ajoutée le jour d'une séance déjà exportée** : la validation exige que Claude retire cette séance (op remove), pas qu'il la déplace. → `test_exported_session_on_race_day_must_be_removed` (Task 6).
5. **Une course Secondaire passe pendant le cycle** : l'objectif passe `done`, le cycle continue, la synchro propose toujours des ajustements. → `test_sync_marks_passed_secondary_done_keeps_cycle` (Task 8).

---

## Lot 1 — Modèle et migration (comportement inchangé pour un seul objectif)

### Task 1: Table `Cycle`, priorité, migration et dépôt

**Files:**
- Modify: `coach/plan/models.py`
- Modify: `coach/plan/repo.py`
- Modify: `tests/plan/factories.py`
- Test: `tests/plan/test_repo.py`

**Interfaces:**
- Produces (models) :
  - `PRIORITIES = ("principal", "secondaire", "plaisir")`, `PRIORITY_LABELS = {"principal": "Principal", "secondaire": "Secondaire", "plaisir": "Plaisir"}`.
  - `class Cycle(SQLModel, table=True)` : `id: int | None` (PK), `created_at: datetime`, `status: str = "active"`, `plan_start: date`, `end_date: date`, `sessions_per_week: int`, `available_days_json: str = ALL_DAYS_JSON`, `long_run_day: str | None = None`, `include_bike: bool = False`, `plan_accepted: bool = False`, `needs_generation: bool = False`, `recovery_from_goal_id: int | None = None` ; méthode `available_days() -> list[str]`.
  - `Goal.priority: str = "principal"`. Les champs plan de `Goal` (`plan_start`, `sessions_per_week`, `plan_accepted`, `available_days_json`, `long_run_day`, `include_bike`) **restent** dans le modèle (colonnes NOT NULL existantes) : ils sont écrits à la création (copie du cycle) mais plus jamais lus après la Task 2.
  - `Session.goal_id` → `Session.cycle_id: int = Field(index=True)` ; `Event.goal_id` → `Event.cycle_id: int = Field(index=True)` ; `Session.from_spec(spec, cycle_id: int)`.
- Produces (repo) : `active_cycle() -> Cycle | None` ; `upcoming_goals() -> list[Goal]` (status `active`, tri `race_date, id`) ; `goals_in(cycle: Cycle) -> list[Goal]` (actifs avec `plan_start <= race_date <= end_date`) ; `horizon_goals(cycle: Cycle) -> list[Goal]` (actifs, `race_date > end_date`) ; `sessions(cycle_id, week_index=None)`, `events(cycle_id)`, `open_injury(cycle_id)` (paramètre renommé). `active_goal()` est **supprimé**.
- Produces (factories) : `make_cycle(**overrides) -> Cycle` (défauts : `plan_start=date(2026,10,26)`, `end_date=date(2027,1,31)`, `sessions_per_week=3`, `status="active"`) ; `make_goal` ajoute `priority="principal"` ; `make_db_session(cycle_id: int, **overrides)`.

> Après cette tâche, seuls `tests/plan/test_repo.py` et `tests/plan/test_models*.py` doivent passer : la suite complète redevient verte à la fin de la Task 2 (renommage de `goal_id` dans tous les services).

- [ ] **Step 1: Écrire les tests de migration et du dépôt**

Dans `tests/plan/test_repo.py`, réutiliser `_old_schema_db` (schéma ancien) pour :

```python
def test_migration_moves_goal_plan_to_cycle(tmp_path):
    # ancienne base : objectif actif id=7 (plan_accepted=1, 4 séances/sem, long_run_day="dimanche"),
    # une séance goal_id=7 statut "exported", un imprévu injury goal_id=7 sans end_date
    engine = make_engine(path)
    repo = Repo(engine)
    cycle = repo.active_cycle()
    assert cycle.id == 7 and cycle.plan_accepted and cycle.sessions_per_week == 4
    assert cycle.end_date == date(2027, 1, 31) and cycle.long_run_day == "dimanche"
    assert [s.status for s in repo.sessions(7)] == ["exported"]
    assert repo.open_injury(7) is not None
    assert repo.upcoming_goals()[0].priority == "principal"

def test_migration_archived_goal_gets_done_cycle(tmp_path): ...  # goal archived id=3 -> Cycle(id=3, status="done")
def test_migration_cycle_is_idempotent(tmp_path): ...            # make_engine deux fois : un seul cycle par objectif
def test_goals_in_and_horizon(repo): ...                         # cycle 1/11→31/01 ; objectifs 15/12, 31/01, 30/05 -> goals_in = 2 premiers, horizon = dernier ; archivé exclu
def test_active_cycle_ignores_done(repo): ...
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/plan/test_repo.py -v`
Expected: FAIL (`Cycle` / `active_cycle` inexistants).

- [ ] **Step 3: Implémenter modèles, migration et dépôt**

Migration, à la fin de `_migrate` (après les étapes existantes, dans la même transaction) :
1. `_add_columns(conn, "goal", {"priority": "VARCHAR NOT NULL DEFAULT 'principal'"})`.
2. Pour `session` puis `event` : si la colonne `goal_id` existe, `ALTER TABLE {t} RENAME COLUMN goal_id TO cycle_id`.
3. Pour chaque ligne de `goal` sans ligne `cycle` de même id : `INSERT INTO cycle` avec **`id = goal.id`** (les `cycle_id` renommés restent donc valides), `status = 'active'` si `goal.status = 'active'` sinon `'done'`, `end_date = race_date`, et copie de `plan_start`, `sessions_per_week`, `available_days_json`, `long_run_day`, `include_bike`, `plan_accepted`.

`create_all` crée la table `cycle` avant `_migrate` ; une base neuve a directement `cycle_id`.

- [ ] **Step 4: Lancer les tests du dépôt**

Run: `uv run pytest tests/plan/test_repo.py -v`
Expected: PASS (adapter les tests existants qui utilisaient `active_goal`/`goal_id`).

- [ ] **Step 5: Commit**

```bash
git add coach/plan/models.py coach/plan/repo.py tests/plan
git commit -m "feat: table Cycle, priorité des objectifs et migration"
```

### Task 2: Brancher le backend sur le cycle actif

**Files:**
- Modify: `coach/plan/calendar.py`, `coach/plan/constraints.py`, `coach/analysis/compliance.py`
- Modify: `coach/llm/prompts.py`
- Modify: `coach/services/context.py`, `plans.py`, `adjust.py`, `events.py`, `sync.py`, `garmin_export.py`
- Modify: `coach/api/app.py`
- Test: tous les tests de `tests/` qui utilisaient `goal_id` / `make_goal` comme porteur du plan (`tests/plan`, `tests/analysis/test_compliance.py`, `tests/llm/test_prompts.py`, `tests/services/*`, `tests/api/test_app.py`)

**Interfaces:**
- Consumes : Task 1.
- Produces (fonctions pures, le premier paramètre devient un `Cycle`) : `calendar.week_monday(cycle, i)`, `suggested_date(cycle, i, day)`, `week_of(cycle, d)` ; `PlanConstraints.of(cycle, today, events)` ; `planned_from_plan(cycle, plan)`, `planned_after_adjustment(cycle, upcoming, adj)` ; `mark_missed(sessions, cycle, today)` ; `load_constraints(repo, cycle, today)`.
- Produces (prompts, signatures définitives, utilisées telles quelles en Task 6) :
  - `build_generation_prompt(cycle: Cycle, goals: list[Goal], horizon: list[Goal], zones, history, n_weeks: int, gpx_texts: list[str], today=None, race_texts: list[str] = (), constraints=None, *, first_week: int = 1, fixed: list[Session] = (), recovery_note: str | None = None) -> str`
  - `build_adjustment_prompt(cycle: Cycle, goals: list[Goal], horizon: list[Goal], zones, current_week, done, missed, upcoming, history, comparisons=None, race_texts: list[str] = (), change_note=None, constraints=None) -> str`
  - Avec un seul objectif Principal et un horizon vide, le texte produit est **identique** à l'actuel (les tests de prompts existants passent sans changer leurs assertions de texte). `first_week`, `fixed`, `recovery_note` ne sont pas encore utilisés dans le texte (Task 5 et 8).
- Produces (services) :
  - `create_goal(repo, garmin, data: GoalInput) -> Goal` : crée le cycle (réglages de `data`, `plan_start = calendar.plan_start(today)`, `end_date = race_date`) et l'objectif (`priority` de `data`) ; comme aujourd'hui, un cycle actif existant passe `done` (ses objectifs actifs `archived`, ses `todo` supprimées). Ce comportement est remplacé en Task 5.
  - `generate_plan(repo, garmin, llm) -> PlanResponse` ; `accept_plan(repo) -> None` (cycle actif ; `GoalError("Aucun plan en cours")` sinon).
  - `update_goal(repo, garmin, llm, goal_id, data: GoalUpdate) -> tuple[Goal, int]` : `GoalUpdate` ne garde que `race_date` et `target_time` ; si la date change, `cycle.end_date` suit (un seul objectif à ce stade).
  - `PlanSettingsUpdate(BaseModel)` : `available_days: list[Weekday] | None`, `long_run_day: Weekday | Literal[""] | None`, `include_bike: bool | None` ; `update_plan_settings(repo, garmin, llm, data) -> tuple[Cycle, int]` (logique et messages repris de l'actuel `update_goal`).
  - `ask_adjustment(repo, garmin, llm, cycle, zones, sessions, today, *, done=(), missed=(), change_note=None)` : `cycle` peut être une copie non enregistrée ; il lit `repo.goals_in(cycle)` / `horizon_goals(cycle)` lui-même.
  - `request_adjustment(repo, garmin, llm, note=None, missed=())`, `create_event(repo, garmin, llm, data)`, `build_event(repo, cycle, data, today)` : sur le cycle actif ; `GoalError`/`EventError` « Le plan doit être validé » si `plan_accepted` est faux.
- Produces (API) :
  - `GET /api/status` : retire `goal`, ajoute `cycle: CycleDict | null`, `goals: GoalDict[]` (à venir), `next_goal: GoalDict | null`.
  - `CycleDict` : `id, status, plan_start, end_date, sessions_per_week, available_days, long_run_day, include_bike, plan_accepted, needs_generation`.
  - `GoalDict` : `id, type, distance_km, d_plus_m, race_date, priority, status, target_time_s, target_source, gpx_summary`.
  - `POST /api/goals` (form) : champ `priority` en plus (défaut `principal`).
  - `PATCH /api/goals/{id}` → `{goal, proposal_id}` ; `PATCH /api/cycle` (corps `PlanSettingsUpdate`) → `{cycle, proposal_id}`.
  - `POST /api/cycle/generate`, `POST /api/cycle/accept`, `POST /api/cycle/adjust`, `POST /api/cycle/events`, `GET /api/cycle/events` remplacent les routes `/goals/{id}/…` correspondantes. `/goals/{id}/race-plan*` inchangées.
  - `GET /api/plan` → `{cycle, goals, horizon, open_injury, weeks}` (`goals` = `goals_in`, `horizon` = `horizon_goals`, en `GoalDict`).

- [ ] **Step 1: Adapter les tests au nouveau porteur du plan**

Remplacer dans les tests `make_goal(...)` utilisé comme plan par `make_cycle(...)` (+ un `make_goal` pour la course), `goal_id=` par `cycle_id=`, les routes `/goals/{id}/generate|accept|events|adjust` par `/cycle/...`, `status["goal"]` par `status["next_goal"]` / `status["cycle"]`. Ajouter :

```python
def test_status_after_migration(...):  # tests/api/test_app.py : base ancienne -> /status a cycle.plan_accepted et next_goal.priority == "principal"
def test_patch_cycle_settings_asks_adjustment(...):  # PATCH /api/cycle {"include_bike": true} -> proposal_id, cycle.include_bike
def test_generate_without_cycle_is_422(...)
```

- [ ] **Step 2: Lancer la suite, vérifier les échecs attendus**

Run: `uv run pytest -q`
Expected: FAIL sur les services / API pas encore adaptés.

- [ ] **Step 3: Adapter calendrier, contraintes, compliance, prompts, services et API selon les interfaces ci-dessus**

`_goal_dict` prend la forme `GoalDict` ci-dessus et `_cycle_dict` est ajouté. `n_weeks(cycle.plan_start, cycle.end_date)` partout où l'on utilisait `goal.race_date`. `garmin_export._goal` devient `_cycle(repo, session) -> Cycle`.

- [ ] **Step 4: Lancer toute la suite backend**

Run: `uv run pytest -q`
Expected: PASS (hors tests `live` déjà ignorés par défaut).

- [ ] **Step 5: Commit**

```bash
git add coach tests
git commit -m "refactor: le plan, les séances et les imprévus portent sur le cycle"
```

### Task 3: Brancher le front sur la nouvelle API

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/App.svelte`, `web/src/components/Sidebar.svelte`, `web/src/routes/{Goal,Plan,Race,Today,Proposal}.svelte`, `web/src/components/{GoalEditDialog,EventDialog,EventList,InjuryBanner}.svelte`
- Create: `web/src/components/PlanSettingsDialog.svelte`
- Test: tests `*.test.ts` correspondants ; `web/src/components/PlanSettingsDialog.test.ts`

**Interfaces:**
- Consumes : API de la Task 2.
- Produces (`api.ts`) : types `Priority = "principal" | "secondaire" | "plaisir"`, `Cycle`, `Goal` (forme `GoalDict`), `Status` avec `cycle`, `goals`, `next_goal` ; `Plan` avec `cycle`, `goals`, `horizon` ; méthodes `generate()`, `accept()`, `updatePlanSettings(body)`, `createEvent(body)`, `events()`, `requestAdjustment()` sans `goalId`. `PRIORITY_LABELS` exporté depuis `web/src/lib/labels.ts`.
- `GoalEditDialog` ne garde que date et temps visé ; disponibilités et vélo passent dans `PlanSettingsDialog` (props `cycle: Cycle`, `onsaved(proposalId: number)`), ouvert depuis la page Objectif par un bouton « Réglages du plan ».
- Le comportement visible reste celui d'aujourd'hui pour un seul objectif.

- [ ] **Step 1: Adapter les tests front (mocks d'API) à la nouvelle forme et écrire `PlanSettingsDialog.test.ts`**

`PlanSettingsDialog.test.ts` : « enregistre les jours et le vélo puis appelle onsaved avec l'id de proposition » ; « refuse moins de jours que de séances par semaine » (réutilise `availabilityValid`).

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd web && npm test`
Expected: FAIL.

- [ ] **Step 3: Implémenter les changements de types, d'appels et `PlanSettingsDialog`**

- [ ] **Step 4: Tests et build**

Run: `cd web && npm test && npm run build`
Expected: PASS, build sans erreur de type.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "refactor(web): statut et plan par cycle, réglages du plan séparés"
```

---

## Lot 2 — Plusieurs objectifs

### Task 4: Règles pures des objectifs

**Files:**
- Create: `coach/plan/goals.py`
- Test: `tests/plan/test_goals.py`

**Interfaces:**
- Consumes : `Goal`, `PRIORITY_LABELS` (Task 1).
- Produces :
  - `MIN_GAP_DAYS = 14`
  - `goal_label(goal: Goal) -> str` : `"Trail de 20 km"` / `"Course sur route de 21,1 km"` (distance au format français, `:g` puis `.` → `,`).
  - `gap_conflict(goal: Goal, others: list[Goal]) -> str | None` : premier `other` (`id` différent, `status == "active"`) tel que ni `goal` ni `other` n'est Plaisir et `abs((goal.race_date - other.race_date).days) < MIN_GAP_DAYS` ; message exact des Global Constraints avec `other`.
  - `cycle_end(goals: list[Goal]) -> date | None` : `goals` = objectifs actifs du cycle et suivants, triés ; premier Principal, sinon dernier objectif ; puis extension sur les jours **immédiatement consécutifs** portant un autre objectif (§5.1 du design) ; `None` si liste vide.
  - `ChangeKind = Literal["close", "draft", "regenerate", "shrink", "adjust", "horizon"]`
  - `classify_change(*, plan_accepted: bool, old_end: date, new_end: date | None, touched_in_cycle: bool) -> ChangeKind` :
    1. `new_end is None` → `"close"` ;
    2. `new_end != old_end` → `"draft"` si non validé, sinon `"regenerate"` si `new_end > old_end`, sinon `"shrink"` ;
    3. `touched_in_cycle` → `"draft"` si non validé, sinon `"adjust"` ;
    4. sinon `"horizon"`.

- [ ] **Step 1: Écrire les tests**

```python
def test_gap_conflict_message():
    semi = make_goal(id=1, type="route", distance_km=21.1, race_date=date(2027,3,22), priority="secondaire")
    trail = make_goal(id=2, type="trail", distance_km=20, race_date=date(2027,3,28), priority="secondaire")
    assert gap_conflict(trail, [semi]) == (
        "Course sur route de 21,1 km du 22/03/2027 (Secondaire) est à 6 jours : "
        "passe l'un des deux en Plaisir ou déplace-le")

def test_gap_ignores_plaisir_and_self_and_archived(): ...
def test_gap_exactly_14_days_ok(): ...
def test_cycle_end_first_principal(): ...                  # Secondaire 28/03, Principal 20/05, Principal 10/10 -> 20/05
def test_cycle_end_without_principal_is_last(): ...
def test_cycle_end_extends_over_consecutive_days(): ...    # Principal sam 20/05 + Plaisir dim 21/05 -> 21/05
def test_cycle_end_empty_is_none(): ...
@pytest.mark.parametrize(...)  # un cas par branche de classify_change
def test_classify_change(...): ...
```

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/plan/test_goals.py -v` → FAIL (module absent).
- [ ] **Step 3: Implémenter `coach/plan/goals.py`**
- [ ] **Step 4: Vérifier** — Run: `uv run pytest tests/plan/test_goals.py -v` → PASS.
- [ ] **Step 5: Commit**

```bash
git add coach/plan/goals.py tests/plan/test_goals.py
git commit -m "feat: règles d'écart et de fin de cycle des objectifs"
```

### Task 5: Ajouter, modifier, retirer un objectif ; régénérer la suite

**Files:**
- Create: `coach/services/goals.py` (création, ajout, modification, retrait d'objectif ; `create_goal`, `update_goal`, `GoalInput`, `GoalUpdate`, `GoalError`, `parse_target_time`, `check_target_time` y déménagent depuis `plans.py`, qui garde génération, validation et réglages du plan)
- Modify: `coach/services/plans.py`, `coach/services/race_strategy.py`, `coach/llm/schemas.py` (`validate_plan`), `coach/llm/prompts.py` (texte « séances fixes »), `coach/api/app.py`
- Test: `tests/services/test_goals.py` (nouveau), `tests/services/test_plans.py`, `tests/services/test_race_strategy.py`, `tests/llm/test_schemas.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes : Task 4 (`gap_conflict`, `cycle_end`, `classify_change`), Task 2 (`ask_adjustment`, `save_proposal`, `mark_for_cleanup`, `sync_marked`).
- Produces :
  - `GoalInput` : + `priority: Priority = "principal"` ; `sessions_per_week`, `available_days`, `long_run_day`, `include_bike` deviennent facultatifs (`sessions_per_week: int | None`), **obligatoires seulement sans cycle actif** (`GoalError("Indique le nombre de séances par semaine")`).
  - `GoalUpdate` : `race_date`, `target_time`, `priority: Priority | None`.
  - `class ChangeResult(BaseModel)`: `proposal_id: int | None`, `needs_generation: bool`.
  - `add_goal(repo, garmin, llm, data: GoalInput) -> tuple[Goal, ChangeResult]` : sans cycle actif → crée cycle + objectif (règle des 14 jours avant la course) et `ChangeResult(None, True)` ; sinon ajoute l'objectif au cycle actif. Ne ferme **plus** le cycle existant.
  - `update_goal(repo, garmin, llm, goal_id, data: GoalUpdate) -> tuple[Goal, ChangeResult]` (le plan n'a plus besoin d'être validé pour modifier un objectif).
  - `remove_goal(repo, garmin, llm, goal_id) -> ChangeResult`.
  - `race_strategy.withdraw_race(repo, garmin, goal_id) -> None` : déprogramme et supprime le workout Jour J exporté (`unschedule`, `delete_workout`), remet ses ids à `None` ; une erreur Garmin remonte.
  - `generate_plan(repo, garmin, llm)` régénère **la suite** quand le cycle a des séances non `todo` : `first_week = max(1, week_of(cycle, today))`, séances fixes = non `todo` des semaines ≥ `first_week` (+ `exported`), suppression des seules `todo` des semaines ≥ `first_week` ; remet `needs_generation = False` et `plan_accepted = False`.
  - `validate_plan(plan, *, n_weeks, sessions_per_week, pace_available, estimate_min_s=None, first_week: int = 1, fixed_counts: Mapping[int, int] | None = None)` : semaines attendues `range(first_week, n_weeks + 1)` ; plafond par semaine `sessions_per_week - fixed_counts.get(w, 0)`.
  - API : `POST /api/goals` → `{goal, proposal_id, needs_generation}` (appelle `add_goal`) ; `PATCH /api/goals/{id}` → `{goal, proposal_id, needs_generation}` ; `DELETE /api/goals/{id}` → `{proposal_id, needs_generation}`.

Orchestration commune (privée à `goals.py`), à suivre pour les trois opérations :
1. Construire la liste des objectifs actifs **après** le changement (copie non enregistrée de l'objectif modifié/ajouté, sans l'objectif retiré) ; refuser avec `GoalError(gap_conflict(...))` si conflit.
2. `new_end = cycle_end(objectifs ≥ cycle.plan_start)` ; `kind = classify_change(plan_accepted=cycle.plan_accepted, old_end=cycle.end_date, new_end=new_end, touched_in_cycle=<date avant ou après dans [plan_start, end avant/après]>)`.
3. Selon `kind` :
   - `adjust` / `shrink` : `ask_adjustment` sur une copie du cycle avec `end_date = new_end` ; pour `shrink`, retirer d'abord des séances transmises celles au-delà de `new_end` (logique `removed_ids` de l'actuel `update_goal`) ; **puis** une transaction enregistre objectif, `end_date`, retraits (`todo` supprimées, `exported` marquées `mark_for_cleanup(removal=True)`), proposition ; enfin `sync_marked`. `ChangeResult(proposal_id, False)`.
   - `regenerate` / `draft` : enregistrer objectif et `end_date`, `needs_generation = True`, `plan_accepted = False` ; `ChangeResult(None, True)`. Les séances existantes restent affichées jusqu'à « Générer ».
   - `horizon` : enregistrer l'objectif seul ; `ChangeResult(None, False)`.
   - `close` : cycle `done`, séances `todo` supprimées, `exported` marquées puis `sync_marked`, propositions `pending` → `stale` ; `ChangeResult(None, False)`.
4. Retrait : `withdraw_race` **avant** toute écriture si une stratégie a un `garmin_workout_id` ; puis `Goal.status = "archived"`.
Note de changement pour Claude (`change_note`) : « L'athlète a ajouté l'objectif {label} du {date} ({Priorité}) » / « a modifié … » / « a retiré … », suivie de « Adapte les séances à venir en conséquence. »

- [ ] **Step 1: Écrire les tests de service**

Dans `tests/services/test_goals.py` (Garmin et LLM factices existants de `tests/services`) :

```python
def test_first_goal_creates_cycle_and_needs_generation(...)
def test_first_goal_requires_sessions_per_week(...)
def test_add_secondary_in_accepted_cycle_asks_adjustment(...)       # ChangeResult.proposal_id non nul, cycle.end_date inchangée
def test_add_goal_gap_conflict_saves_nothing(...)                  # GoalError avec le message exact ; aucun Goal ajouté
def test_add_goal_after_principal_is_horizon(...)                  # pas d'appel LLM, proposal_id None, needs_generation False
def test_add_closer_principal_shrinks_cycle(...)                   # séance exportée au-delà -> pending_removal, proposition créée
def test_add_far_goal_without_principal_regenerates(...)           # needs_generation True, plan_accepted False, séances inchangées
def test_add_goal_in_draft_marks_needs_generation(...)
def test_adjust_failure_saves_nothing(...)                         # LLM en erreur -> objectif absent, end_date inchangée
def test_update_goal_date_respects_gap(...)
def test_update_priority_to_principal_moves_end(...)
def test_remove_last_goal_closes_cycle(...)                        # cycle done, todo supprimées, exported retirées de Garmin
def test_remove_goal_withdraws_race_workout(...)
def test_remove_goal_garmin_error_keeps_goal(...)
```

Dans `tests/services/test_plans.py` : `test_regenerate_keeps_fixed_sessions` (séances `done` semaine 1 et `exported` semaine 3, aujourd'hui semaine 3 → plan attendu semaines 3..n, la séance exportée conservée, les `todo` des semaines ≥ 3 remplacées) ; dans `tests/llm/test_schemas.py` : `test_validate_plan_first_week_and_fixed_counts`.

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/services/test_goals.py tests/services/test_plans.py tests/llm/test_schemas.py -q` → FAIL.
- [ ] **Step 3: Implémenter `goals.py`, `withdraw_race`, la régénération de la suite et les routes**

Le prompt de génération, si `fixed` est non vide, ajoute : « Semaines {first_week} à {n} seulement : les séances suivantes sont fixées et comptent dans leur semaine : » suivi d'une ligne `_session_line` par séance fixe.

- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add coach tests
git commit -m "feat: ajout, modification et retrait d'objectifs dans le cycle"
```

### Task 6: Prompts et contrôles selon la priorité

**Files:**
- Modify: `coach/llm/prompts.py`, `coach/llm/schemas.py`, `coach/plan/constraints.py`, `coach/services/plans.py`, `coach/services/adjust.py`, `coach/services/context.py`, `coach/services/garmin_export.py` (application d'une proposition portant des estimations)
- Test: `tests/llm/test_prompts.py`, `tests/llm/test_schemas.py`, `tests/plan/test_constraints.py`, `tests/services/test_plans.py`, `tests/services/test_adjust.py`

**Interfaces:**
- Consumes : signatures de prompts de la Task 2.
- Produces :
  - `class GoalEstimate(_Strict)`: `goal_id: int`, `seconds: int`.
  - `PlanResponse.estimated_time_s` **remplacé** par `estimated_times: list[GoalEstimate] = []` ; `AdjustmentResponse.estimated_times: list[GoalEstimate] = []`.
  - `validate_plan(..., estimate_min_s: Mapping[int, int] | None = None)` et `validate_adjustment(..., estimate_min_s: Mapping[int, int] | None = None)` : pour chaque `goal_id` attendu, une estimation présente et ≥ au plancher ; erreur sinon : `"estimated_times : estimation manquante pour l'objectif {id}"` / `"estimated_times : {s} s invraisemblable pour l'objectif {id} (au moins {min} s)"`. Plancher = `round(MIN_PACE_S_KM * distance_km)` pour chaque objectif du cycle de source `claude` (génération) ou de source `claude` sans `target_time_s` (ajustement).
  - Estimations appliquées : à la génération, directement sur les objectifs concernés ; pour un ajustement, à l'**acceptation** de la proposition, à partir d'une nouvelle colonne `Proposal.estimates_json: str = "[]"` (ajoutée par `_add_columns`, remplie par `save_proposal`).
  - `PlanConstraints` : + `race_dates: tuple[date, ...] = ()`, `sessions_per_week: int | None = None` ; `load_constraints` les remplit depuis `goals_in(cycle)`.
  - `constraint_errors` ajoute :
    - séance non exportée un jour de course : `"{label} : tombe le jour de la course du {jj/mm}"` ;
    - séance exportée un jour de course : `"{label} : séance exportée le jour de la course du {jj/mm}, à retirer (op remove)"` ;
    - par semaine contenant k courses : `fixed + prévues ≤ max(0, sessions_per_week − k)`, sinon `"semaine {w} : {n} séances pour {cap} possibles ({k} course(s) cette semaine)"`.
  - Texte des prompts (dans `_goals_text(goals, horizon, *, generation)`, qui remplace `_goal_text`) :
    - un seul objectif Principal et horizon vide → texte actuel inchangé ;
    - sinon : une ligne par objectif du cycle « - {date} : {type}, {km} km, {D+} m de D+, priorité {Priorité}[, temps visé h:mm] » ; deux objectifs à dates consécutives annoncés « (enchaînés, à traiter comme un bloc) » ;
    - constante `PRIORITY_RULES` (ajoutée si au moins un objectif non Principal ou plus d'un objectif) reprenant §5.3 du design : Principal = affûtage complet ; Secondaire = séance spécifique dans les 10 jours avant, mini-affûtage de quelques jours (volume réduit, intensité conservée), récupération après, sans casser la progression vers le Principal ; Plaisir = pas d'affûtage, la course remplace une séance de sa semaine (souvent la sortie longue), récupération légère après si elle est longue ; aucune séance le jour d'une course, et une course compte comme une séance de sa semaine ;
    - horizon non vide : « Objectifs suivants (préparés dans un cycle ultérieur, ne pas les anticiper) : » + une ligne par objectif ; si l'un est Principal : « Termine ce cycle par l'affûtage de {label} sans anticiper le suivant. »
    - estimation : « Pour chaque objectif sans temps visé (ids {…}), estime un temps réaliste dans estimated_times. »

- [ ] **Step 1: Écrire les tests**

```python
def test_single_principal_prompt_unchanged(...)                    # snapshot du texte actuel
def test_prompt_lists_goals_with_priority_and_rules(...)           # "priorité Secondaire", PRIORITY_RULES présent
def test_prompt_consecutive_goals_as_block(...)
def test_prompt_horizon_principal_line(...)
def test_validate_plan_estimates_per_goal(...)
def test_race_day_session_rejected(...)
def test_exported_session_on_race_day_must_be_removed(...)
def test_week_cap_counts_races(...)                                 # 4 séances/sem, 2 courses -> 3 prévues = erreur "pour 2 possibles (2 course(s) cette semaine)"
def test_accept_proposal_applies_estimates(...)
```

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/llm tests/plan/test_constraints.py tests/services -q` → FAIL.
- [ ] **Step 3: Implémenter**
- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add coach tests
git commit -m "feat: Claude prépare les objectifs du cycle selon leur priorité"
```

### Task 7: Interface — liste d'objectifs, priorité, courses dans le plan, Jour J

**Files:**
- Modify: `web/src/routes/Goal.svelte` (devient la page **Objectifs**), `web/src/routes/Plan.svelte`, `web/src/routes/Race.svelte`, `web/src/components/GoalEditDialog.svelte`, `web/src/components/Sidebar.svelte`, `web/src/lib/api.ts`
- Create: `web/src/components/GoalForm.svelte` (formulaire d'objectif, réglages du plan affichés seulement sans cycle), `web/src/components/PriorityBadge.svelte`, `web/src/components/RaceDayCard.svelte`
- Test: `web/src/routes/Goal.test.ts`, `Plan.test.ts`, `Race.test.ts`, `web/src/components/GoalForm.test.ts`, `GoalEditDialog.test.ts`

**Interfaces:**
- Consumes : API Task 5 (`createGoal` → `{goal, proposal_id, needs_generation}`, `updateGoal`, `removeGoal(id)`), `Plan.goals`/`horizon` (Task 2).
- Produces :
  - `api.removeGoal(goalId: number): Promise<{ proposal_id: number | null; needs_generation: boolean }>`.
  - Après une opération : `proposal_id` non nul → navigation `#/proposal` ; `needs_generation` → bandeau « Le plan doit être recalculé » avec bouton « Générer » ; erreur 422 → `ErrorBanner` avec le message du serveur (message d'écart tel quel).
  - Page Objectifs : objectifs à venir triés par date (badge, type/distance/D+, temps visé, actions Modifier, Jour J, Retirer — retrait confirmé par `confirm()` « Retirer {label} du {date} ? ») ; bouton « Ajouter un objectif » ; bouton « Réglages du plan » (Task 3) ; objectifs courus (`status === "done"`) dans un `<details>` « Objectifs courus ».
  - `GoalForm` : sélecteur de priorité (3 boutons radio, Principal par défaut pour le premier objectif, Secondaire sinon) ; les champs séances/jours/sortie longue/vélo n'apparaissent que si `cycle === null`.
  - Plan : `RaceDayCard` le jour de chaque objectif du cycle (titre `goal_label` côté front, `PriorityBadge`) ; liste « Ensuite » des objectifs de l'horizon sous le plan.
  - Jour J : `<select>` des objectifs à venir, `next_goal` par défaut ; `Race` reçoit `goalId`. Sans temps de référence pour un objectif de l'horizon : « Temps estimé à la préparation de son cycle, ou fixe un temps visé ».

- [ ] **Step 1: Écrire les tests**

```ts
it("affiche les objectifs triés avec leur priorité")
it("ajoute un objectif sans réglages du plan quand un cycle existe")
it("affiche le message d'écart renvoyé par le serveur")
it("ouvre la proposition après un ajout qui l'a créée")
it("affiche le bandeau Générer quand needs_generation")
it("retire un objectif après confirmation")
it("montre une carte Course le jour d'un objectif dans le plan")  // Plan.test.ts
it("liste les objectifs de l'horizon sous le plan")               // Plan.test.ts
it("change d'objectif dans le sélecteur Jour J")                  // Race.test.ts
```

- [ ] **Step 2: Vérifier l'échec** — Run: `cd web && npm test` → FAIL.
- [ ] **Step 3: Implémenter**
- [ ] **Step 4: Vérifier** — Run: `cd web && npm test && npm run build` → PASS.
- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(web): page Objectifs, priorités et courses dans le plan"
```

---

## Lot 3 — Cycle suivant

### Task 8: Clôture du cycle et « Préparer le cycle suivant »

**Files:**
- Create: `coach/services/cycles.py`
- Modify: `coach/services/sync.py`, `coach/services/plans.py` (note de récupération), `coach/llm/prompts.py`, `coach/api/app.py`, `web/src/lib/api.ts`, `web/src/routes/Goal.svelte`, `web/src/App.svelte`
- Test: `tests/services/test_cycles.py`, `tests/services/test_sync.py`, `tests/api/test_app.py`, `web/src/routes/Goal.test.ts`

**Interfaces:**
- Consumes : `cycle_end` (Task 4), `generate_plan` (Task 5), `PlanSettingsUpdate` (Task 2).
- Produces :
  - `close_passed(repo, today: date) -> None` : objectifs `active` avec `race_date < today` → `done` ; si le cycle actif a `end_date < today` → `done` et propositions `pending` → `stale`. Appelée par `sync` après le rattachement des activités (pour que la séance du jour de course reste rattachable) et avant la décision de proposer un ajustement (pas de proposition sur un cycle clos).
  - `prepare_next_cycle(repo, garmin, data: PlanSettingsUpdate | None = None) -> Cycle` : exige aucun cycle actif et au moins un objectif à venir (`GoalError("Aucun objectif à venir")`) ; `plan_start = max(lundi suivant la fin du dernier cycle, calendar.plan_start(today))` ; `end_date = cycle_end(upcoming_goals())` ; réglages copiés du dernier cycle `done` puis surchargés par `data` ; `needs_generation = True` ; `recovery_from_goal_id` = dernier objectif `done` du cycle précédent ; copie l'arrêt ouvert du cycle précédent (même `start_date`, `end_date` nulle, `note`) dans le nouveau cycle.
  - `generate_plan` passe `recovery_note = "Commence par une récupération adaptée à {label} couru le {jj/mm/aaaa}."` quand `cycle.recovery_from_goal_id` est renseigné ; le prompt l'ajoute après la ligne des objectifs.
  - API : `POST /api/cycle/next` (corps facultatif `PlanSettingsUpdate`) → `CycleDict`. `/status` inchangé : `cycle: null` + `goals` non vide = cycle à préparer.
  - Front : sur la page Objectifs, si `cycle === null` et `goals.length > 0`, carte « Préparer le cycle suivant » (réglages pré-remplis du dernier cycle, bouton « Préparer et générer » → `api.nextCycle()` puis `api.generate()`) ; si aucun objectif : formulaire de premier objectif (comportement Task 7).

- [ ] **Step 1: Écrire les tests**

```python
def test_sync_marks_passed_secondary_done_keeps_cycle(...)   # Secondaire passé -> done ; cycle actif ; proposition toujours possible
def test_sync_closes_cycle_after_principal(...)              # cycle done, proposition pending -> stale, aucune nouvelle proposition
def test_race_day_activity_still_matched_before_close(...)
def test_prepare_next_cycle_dates_and_settings(...)          # Principal dim 20/05 -> plan_start lun 21/05 ; réglages copiés
def test_prepare_next_cycle_late_starts_this_week(...)
def test_prepare_next_cycle_copies_open_injury(...)
def test_prepare_next_cycle_without_goal_is_error(...)
def test_generation_prompt_has_recovery_note(...)
```
Front : `it("propose de préparer le cycle suivant quand un objectif reste à venir")`.

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/services/test_cycles.py tests/services/test_sync.py -q` et `cd web && npm test` → FAIL.
- [ ] **Step 3: Implémenter**
- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` puis `cd web && npm test && npm run build` → PASS.
- [ ] **Step 5: Commit**

```bash
git add coach tests web
git commit -m "feat: clôture du cycle et préparation du cycle suivant"
```

### Task 9: Roadmap et vérification d'ensemble

**Files:**
- Modify: `ROADMAP.md` (ajout dans « Fait » : « Plusieurs objectifs avec priorité (Principal, Secondaire, Plaisir) et plan par cycles »)

- [ ] **Step 1: Suites complètes** — Run: `uv run pytest -q` et `cd web && npm test && npm run build` → PASS.
- [ ] **Step 2: Vérification manuelle avec le cas du design** (base de dev) : ultra Principal en mai, trail 20 km Secondaire le sam. 28/03, 30 km Plaisir le dim. 29/03, semi Secondaire le 22/03 refusé avec le message d'écart puis accepté en Plaisir ; générer : aucune séance les 22, 28 et 29/03 ; semaine du 23/03 ≤ séances/sem − 2.
- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: roadmap, plusieurs objectifs avec priorité"
```
