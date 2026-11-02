# Disponibilités, imprévus et vélo — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendre le plan adaptable : jours possibles et jour de sortie longue, imprévus déclarés qui déclenchent une proposition de Claude, séances vélo d'endurance douce.

**Architecture:** les contraintes sont des données (champs de `Goal`, table `Event`) ; un module de code pur `coach/plan/constraints.py` vérifie les réponses de Claude, et ses erreurs s'ajoutent à celles de `validate_plan` / `validate_adjustment` dans le `validate=` de `ask_structured` (relance unique existante). Les imprévus passent par le circuit de proposition existant (`ask_adjustment` → `save_proposal` → `apply_proposal`).

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLite, Pydantic v2, pytest ; Svelte 5 + Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-02-flexibility-design.md`

## Global Constraints

- Textes visibles et messages d'erreur en français ; erreurs métier levées en `CoachError` (sous-classes) → 422 `invalid` via `_register_errors`.
- Jours de la semaine : `Weekday` de `coach/llm/schemas.py` (`"lundi"` … `"dimanche"`), ordre de `coach/plan/calendar._WEEKDAYS`.
- Objectifs existants après migration : 7 jours possibles, `long_run_day = None`, `include_bike = False` ; séances existantes `sport = "run"`.
- `SessionSpec.sport` vaut `"run"` par défaut : anciennes réponses et `changes_json` des propositions restent valides.
- Rien ne change dans le plan sans proposition acceptée ; un imprévu reste enregistré même si Claude échoue.
- Vélo : type `EF` ou `récup`, `target_kind = "hr"`, zones Z1/Z2 ou aucune, au plus une séance vélo par semaine ; `sportType` Garmin `{"sportTypeId": 2, "sportTypeKey": "cycling"}`.
- `CYCLING_TYPES = {"cycling", "road_biking", "indoor_cycling", "virtual_ride", "gravel_cycling", "mountain_biking"}`.
- Commandes : `uv run pytest -q` (racine), `npm test -- --run` (dans `web/`).
- Messages de commit conventionnels en français, sans signature Claude.

## Review Focus

- **Semaine du plan entièrement bloquée** (vacances de 7 jours ou plus) : Claude doit pouvoir rendre une semaine vide ; aucune règle (ni `validate_plan`) ne doit exiger au moins une séance par semaine. Test ajouté en tâche 8.
- **Période bloquée chevauchant deux semaines ou débordant hors du plan** (début avant `plan_start`, fin après la course) : seules les dates réelles comptent, sans erreur d'index. Test en tâche 8.
- **Changer les jours possibles alors que des séances `todo` tombent sur un jour retiré** : la proposition doit les déplacer ; une séance `todo` non modifiée sur un jour retiré est une erreur. Test en tâche 2.
- **Arrêt ouvert déclaré un dimanche** : le blocage couvre seulement ce dimanche ; la semaine suivante reste libre. Test en tâche 8.
- **Supprimer l'arrêt ouvert lui-même** (au lieu de signaler la reprise) : le bandeau disparaît et la synchro propose de nouveau des ajustements. Test en tâche 10.

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `coach/plan/constraints.py` (nouveau) | `PlanConstraints`, `Planned`, `constraint_errors`, `planned_from_plan`, `planned_after_adjustment`, `blocked_periods` — code pur |
| `coach/plan/models.py` | champs `Goal`, `Session.sport`, table `Event` |
| `coach/plan/repo.py` | migration incrémentale, accès aux `Event` |
| `coach/services/context.py` | `load_constraints(repo, goal, today)` |
| `coach/services/plans.py` | `GoalInput`/`GoalUpdate`, validation des disponibilités, contraintes à la génération |
| `coach/services/adjust.py` | contraintes dans `ask_adjustment`, `request_adjustment` |
| `coach/services/events.py` (nouveau) | création, suppression, reprise d'un imprévu |
| `coach/services/sync.py` | suspension pendant un arrêt ouvert |
| `coach/services/garmin_export.py` | avertissements d'export, copie de `sport` |
| `coach/llm/schemas.py` | `SessionSpec.sport` |
| `coach/llm/prompts.py` | blocs Disponibilités, Imprévus, Vélo ; jour et sport des séances listées |
| `coach/export/garmin_workout.py` | `sportType` vélo |
| `coach/analysis/compliance.py` | `CYCLING_TYPES`, rattachement par sport |
| `coach/api/app.py` | champs des objectifs, routes des imprévus |
| `web/src/lib/api.ts` | types et appels |
| `web/src/components/AvailabilityFields.svelte` (nouveau) | jours + sortie longue (+ vélo), partagé par `Goal.svelte` et `GoalEditDialog` |
| `web/src/components/EventDialog.svelte` (nouveau) | déclaration d'un imprévu |
| `web/src/components/EventList.svelte` (nouveau) | liste et suppression des imprévus |
| `web/src/components/InjuryBanner.svelte` (nouveau) | bandeau d'arrêt et reprise |

---

# Lot 1 — Disponibilités

### Task 1: Champs de disponibilité sur l'objectif et migration incrémentale

**Files:**
- Modify: `coach/plan/models.py` (classe `Goal`)
- Modify: `coach/plan/repo.py:40-60` (`_migrate`)
- Test: `tests/plan/test_repo.py`

**Interfaces:**
- Produces: `Goal.available_days_json: str` (défaut `ALL_DAYS_JSON`), `Goal.long_run_day: str | None = None`, `Goal.available_days() -> list[str]` ; constante `ALL_DAYS_JSON` dans `models.py` (JSON des 7 jours dans l'ordre) ; `_add_columns(conn, table: str, columns: dict[str, str]) -> None` dans `repo.py` (ajoute chaque colonne absente, DDL donné en valeur).

- [ ] **Step 1: Write the failing tests**

```python
def test_goal_defaults_to_all_days(repo):
    goal = repo.add(make_goal())
    assert goal.available_days() == ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    assert goal.long_run_day is None

def test_migrate_adds_availability_to_old_goal(tmp_path):
    # base 0.5.0 : table goal sans available_days_json / long_run_day, une ligne existante
    ...  # créer la table goal avec les colonnes de la 0.5.0 via sqlite3, insérer une ligne
    repo = Repo(make_engine(path))
    goal = repo.active_goal()
    assert goal.available_days() == [...7 jours...]
    assert goal.long_run_day is None

def test_migrate_is_idempotent(tmp_path):
    make_engine(tmp_path / "t.db"); make_engine(tmp_path / "t.db")  # pas d'exception
```

- [ ] **Step 2: Run** `uv run pytest tests/plan/test_repo.py -q` — Expected: FAIL (`available_days` inconnu).
- [ ] **Step 3: Implement.** Réécrire `_migrate` en étapes indépendantes : l'étape existante du temps visé reste conditionnée à l'absence de `target_time_s` (avec sa reprise depuis `racestrategy`), puis `_add_columns(conn, "goal", {"available_days_json": f"VARCHAR NOT NULL DEFAULT '{ALL_DAYS_JSON}'", "long_run_day": "VARCHAR"})`. Supprimer le `return` anticipé.
- [ ] **Step 4: Run** `uv run pytest tests/plan -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(goal): jours possibles et jour de sortie longue en base`

### Task 2: Règles de disponibilité (code pur)

**Files:**
- Create: `coach/plan/constraints.py`
- Test: `tests/plan/test_constraints.py`

**Interfaces:**
- Consumes: `Goal.available_days()`, `Goal.long_run_day` (tâche 1) ; `calendar.suggested_date`, `SessionSpec`, `AdjustmentResponse`.
- Produces:

```python
@dataclass(frozen=True)
class PlanConstraints:
    available_days: tuple[str, ...]
    long_run_day: str | None
    today: date
    include_bike: bool = False
    events: tuple["Event", ...] = ()

    @classmethod
    def of(cls, goal: Goal, today: date, events: Sequence[Event] = ()) -> "PlanConstraints": ...

@dataclass(frozen=True)
class Planned:
    label: str              # « séance 12 », « ajout 2 », « semaine 3, séance 1 »
    spec: SessionSpec
    date: date              # scheduled_date si exportée, sinon calendar.suggested_date
    exported: bool

def planned_from_plan(goal: Goal, plan: PlanResponse) -> list[Planned]
def planned_after_adjustment(goal: Goal, upcoming: list[Session], adj: AdjustmentResponse) -> list[Planned]
def constraint_errors(planned: list[Planned], c: PlanConstraints, *, fixed_counts: Mapping[int, int] | None = None) -> list[str]
```

`planned_after_adjustment` : part des séances `upcoming`, retire les `remove`, remplace les `modify` (une séance exportée modifiée garde sa `scheduled_date`, `exported=True`), ajoute les `add`. `fixed_counts` (séances `done`/`missed`/`sync_error` par semaine) sert à la règle 4 (tâche 8).

Ce lot implémente les règles 1 (jours possibles, séances non exportées seulement ; jours de la semaine allégée en tâche 8) et 5 (sortie longue). Messages : `"{label} : {jour} n'est pas un jour possible"`, `"{label} : la sortie longue doit tomber le {long_run_day}"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_session_on_unavailable_day_is_rejected():
    c = PlanConstraints(available_days=("mardi", "jeudi", "dimanche"), long_run_day=None, today=TODAY)
    p = [Planned("séance 1", make_session(suggested_day="lundi"), date(2026, 11, 2), exported=False)]
    assert constraint_errors(p, c) == ["séance 1 : lundi n'est pas un jour possible"]

def test_exported_session_ignores_available_days(): ...  # exported=True, lundi → []

def test_long_run_must_be_on_long_run_day():
    c = PlanConstraints(available_days=ALL, long_run_day="dimanche", today=TODAY)
    p = [Planned("séance 1", make_session(type="sortie_longue", suggested_day="samedi"), ..., False)]
    assert constraint_errors(p, c) == ["séance 1 : la sortie longue doit tomber le dimanche"]

def test_unchanged_todo_on_removed_day_is_rejected():
    # Review Focus : goal avec available_days sans lundi, upcoming = [Session todo lundi], adj vide
    planned = planned_after_adjustment(goal, upcoming, AdjustmentResponse(analysis="", changes=[]))
    assert constraint_errors(planned, PlanConstraints.of(goal, TODAY)) == ["séance 7 : lundi n'est pas un jour possible"]

def test_planned_after_adjustment_applies_remove_modify_add(): ...  # labels, dates, exported conservé
```

- [ ] **Step 2: Run** `uv run pytest tests/plan/test_constraints.py -q` — Expected: FAIL (module absent).
- [ ] **Step 3: Implement** `coach/plan/constraints.py` (importer `Event` sous `TYPE_CHECKING` tant que la tâche 7 ne l'a pas créé).
- [ ] **Step 4: Run** `uv run pytest tests/plan/test_constraints.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plan): vérification des jours possibles et du jour de sortie longue`

### Task 3: Contraintes à la création, modification, génération et ajustement

**Files:**
- Modify: `coach/services/context.py`, `coach/services/plans.py`, `coach/services/adjust.py`, `coach/llm/prompts.py`
- Test: `tests/services/test_plans.py`, `tests/services/test_adjust.py`, `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes: tâche 2.
- Produces:
  - `load_constraints(repo: Repo, goal: Goal, today: date) -> PlanConstraints` (`context.py`) ; lot 1 : `events=()`, lot 2 : `repo.events(goal.id)`.
  - `GoalInput.available_days: list[Weekday]` (défaut les 7), `GoalInput.long_run_day: Weekday | None = None`.
  - `GoalUpdate.available_days: list[Weekday] | None = None`, `GoalUpdate.long_run_day: Weekday | Literal[""] | None = None` (`""` = aucun jour imposé).
  - `check_availability(available_days: list[str], long_run_day: str | None, sessions_per_week: int) -> None` (`plans.py`, lève `GoalError`).
  - `build_generation_prompt(..., constraints: PlanConstraints | None = None)` et `build_adjustment_prompt(..., constraints: PlanConstraints | None = None)`.
  - `ask_adjustment(...)` construit lui-même `load_constraints(repo, goal, today)` (avec le `goal` reçu, qui peut être la copie modifiée).

- [ ] **Step 1: Write the failing tests**

```python
def test_create_goal_rejects_fewer_days_than_sessions(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 3 jours possibles"):
        create_goal(repo, fake_garmin, goal_input(sessions_per_week=3, available_days=["mardi", "jeudi"]))

def test_create_goal_rejects_long_run_day_not_available(...):
    match="Le jour de la sortie longue doit faire partie des jours possibles"

def test_generate_plan_retries_on_unavailable_day(repo, fake_garmin):
    # 1re réponse : séance un lundi alors que lundi n'est pas possible ; 2e réponse valide
    llm = FakeLLMProvider([bad_plan_json, good_plan_json])
    generate_plan(repo, fake_garmin, llm, goal.id)
    assert "lundi n'est pas un jour possible" in llm.calls[1]

def test_update_goal_availability_creates_proposal_with_note(...):
    # GoalUpdate(available_days=[...sans lundi]) → proposition, note « jours possibles »
    assert "jours possibles" in llm.calls[0]

def test_update_goal_clears_long_run_day(...):  # long_run_day="" → None en base

def test_prompts_list_availability_and_session_day():
    prompt = build_adjustment_prompt(..., constraints=c)
    assert "Jours possibles : mardi, jeudi, dimanche" in prompt
    assert "Sortie longue : le dimanche" in prompt
    assert "| mardi |" in prompt  # _session_line affiche le jour conseillé
```

- [ ] **Step 2: Run** `uv run pytest tests/services/test_plans.py tests/services/test_adjust.py tests/llm/test_prompts.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `check_availability` : messages `"Il faut au moins {n} jours possibles pour {n} séances par semaine"` et `"Le jour de la sortie longue doit faire partie des jours possibles"` ; appelé dans `create_goal` et `update_goal` (sur les valeurs après modification). `update_goal` : n'exige plus une modification de date ou de temps ; notes ajoutées `"jours possibles : {liste}"`, `"sortie longue le {jour}"` ou `"plus de jour imposé pour la sortie longue"`.
  - `generate_plan` : `validate=lambda p: validate_plan(...) + constraint_errors(planned_from_plan(goal, p), c)`.
  - `ask_adjustment` : `validate=lambda a: validate_adjustment(...) + constraint_errors(planned_after_adjustment(goal, upcoming, a), c, fixed_counts=...)` avec `fixed_counts` = séances non `todo`/`exported` (hors `pending_removal`) par semaine.
  - Prompts : bloc `"Disponibilités : Jours possibles : {jours}. Sortie longue : le {jour}. Ne place aucune séance un autre jour."` (la phrase sur la sortie longue seulement si renseignée), inséré après le descriptif de l'objectif ; `_session_line` ajoute `| {suggested_day} |` après la semaine.
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: PASS (toute la suite : `_session_line` est partagé).
- [ ] **Step 5: Commit** `feat(plan): disponibilités respectées à la génération et à l'ajustement`

### Task 4: API des disponibilités et avertissement d'export

**Files:**
- Modify: `coach/api/app.py` (`post_goal`, `_goal_dict`), `coach/services/garmin_export.py` (`_warnings`)
- Test: `tests/api/test_app.py`, `tests/services/test_garmin_export.py`

**Interfaces:**
- Consumes: tâche 3.
- Produces: `POST /api/goals` accepte les champs de formulaire `available_days` (chaîne `"mardi,jeudi,dimanche"`, absente = 7 jours) et `long_run_day` ; `PATCH /api/goals/{id}` accepte `available_days` (liste) et `long_run_day` (`""` = aucun) en JSON ; `_goal_dict` expose `available_days: list[str]` et `long_run_day`. `_warnings` ajoute `"Jour hors de tes disponibilités"` si `d` n'est pas un jour possible.

- [ ] **Step 1: Write the failing tests** : création avec `available_days="mardi,jeudi,dimanche"` → `GET /api/plan` renvoie `goal.available_days == ["mardi", "jeudi", "dimanche"]` ; jour invalide (`"lunid"`) → 422 ; `export-check` un lundi non possible → `"Jour hors de tes disponibilités"` dans `warnings`.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_app.py tests/services/test_garmin_export.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** (découper la chaîne sur `,`, ignorer les vides, laisser `GoalInput` valider ; les erreurs Pydantic passent par `_invalid` comme aujourd'hui).
- [ ] **Step 4: Run** même commande — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): disponibilités de l'objectif et avertissement d'export`

### Task 5: Front des disponibilités

**Files:**
- Create: `web/src/components/AvailabilityFields.svelte`, `web/src/components/AvailabilityFields.test.ts`
- Modify: `web/src/lib/api.ts` (`Goal`, `GoalInput`, `createGoal`, `updateGoal`), `web/src/routes/Goal.svelte`, `web/src/components/GoalEditDialog.svelte`
- Test: `web/src/routes/Goal.test.ts`, `web/src/components/GoalEditDialog.test.ts`

**Interfaces:**
- Consumes: tâche 4.
- Produces: `AvailabilityFields` avec props liées `bind:days: string[]`, `bind:longRunDay: string` (`""` = Aucun), prop `perWeek: number` ; affiche sous les cases `"Coche au moins {perWeek} jours"` quand `days.length < perWeek` ; la liste « Jour de la sortie longue » ne propose que les jours cochés et repasse à `""` si son jour est décoché. Exporte `availabilityValid(days, perWeek): boolean`.

- [ ] **Step 1: Write the failing tests**
  - `AvailabilityFields` : décocher lundi retire « lundi » de la liste de sortie longue ; décocher le jour choisi remet « Aucun » ; message quand trop peu de jours.
  - `Goal.test.ts` : `createGoal` reçoit `available_days: ["mardi","jeudi","dimanche"]` et `long_run_day: "dimanche"` ; bouton de création désactivé avec 2 jours pour 3 séances.
  - `GoalEditDialog.test.ts` : ne changer que les jours envoie `{ available_days: [...] }` seulement ; remettre « Aucun » envoie `long_run_day: ""`.
- [ ] **Step 2: Run** `npm test -- --run` (dans `web/`) — Expected: FAIL.
- [ ] **Step 3: Implement** ; `createGoal` envoie `available_days` joint par `,` dans le `FormData`.
- [ ] **Step 4: Run** `npm test -- --run` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): choix des jours possibles et du jour de sortie longue`

# Lot 2 — Imprévus

### Task 6: Table `Event` et accès en base

**Files:**
- Modify: `coach/plan/models.py`, `coach/plan/repo.py`
- Test: `tests/plan/test_repo.py`

**Interfaces:**
- Produces: `Event` (SQLModel, champs de la spec 3.2 : `id`, `goal_id` indexé, `created_at`, `kind`, `start_date`, `end_date`, `max_sessions`, `days_json`, `session_id`, `note`) avec `Event.days() -> list[str] | None` ; `Repo.events(goal_id) -> list[Event]` (plus récent d'abord, par `start_date` puis `id`), `Repo.open_injury(goal_id) -> Event | None`. La table est créée par `create_all` (pas de migration de colonnes).

- [ ] **Step 1: Write the failing tests** : `events` trié ; `open_injury` renvoie l'arrêt sans `end_date` et `None` quand il est clos.
- [ ] **Step 2: Run** `uv run pytest tests/plan/test_repo.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plan): table des imprévus`

### Task 7: Validation d'un imprévu

**Files:**
- Create: `coach/services/events.py`
- Test: `tests/services/test_events.py`

**Interfaces:**
- Consumes: tâche 6.
- Produces:

```python
class EventError(CoachError): ...

class EventInput(BaseModel):
    kind: Literal["unavailable", "injury", "light_week", "fatigue"]
    start_date: date | None = None
    end_date: date | None = None
    max_sessions: int | None = Field(None, ge=0)
    days: list[Weekday] | None = None
    session_id: int | None = None
    note: str | None = Field(None, max_length=1000)

def build_event(repo: Repo, goal: Goal, data: EventInput, today: date) -> Event  # valide, n'écrit rien
```

Règles (spec 3.2) et messages :
- `unavailable` : début et fin obligatoires (`"Indique les dates de début et de fin"`), fin ≥ début (`"La fin doit être après le début"`).
- `injury` : début obligatoire, fin facultative ≥ début ; un seul arrêt ouvert (`"Un arrêt est déjà en cours : signale d'abord la reprise"`).
- `light_week` : `start_date` est un lundi d'une semaine du plan (`"Choisis une semaine du plan"`) ; `end_date` = dimanche (calculé) ; `max_sessions` obligatoire ; `days` ⊆ jours possibles de l'objectif.
- `fatigue` : `start_date = end_date = today` (imposés) ; `session_id` éventuel appartient à l'objectif (`"Séance introuvable"`).

- [ ] **Step 1: Write the failing tests** : un test par règle (valide et invalide), `fatigue` impose aujourd'hui.
- [ ] **Step 2: Run** `uv run pytest tests/services/test_events.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(events): validation des imprévus`

### Task 8: Règles des périodes bloquées, de l'arrêt ouvert et de la semaine allégée

**Files:**
- Modify: `coach/plan/constraints.py`
- Test: `tests/plan/test_constraints.py`

**Interfaces:**
- Consumes: `Event` (tâche 6), `PlanConstraints.events`.
- Produces: `blocked_periods(c: PlanConstraints) -> list[tuple[date, date, str]]` (début, fin, libellé « indisponibilité du 05/11 au 12/11 » / « arrêt depuis le 05/11 ») ; règles 1 (jours de la semaine allégée), 2, 3, 4 ajoutées à `constraint_errors`. Messages : `"{label} : tombe pendant {libellé}"`, `"{label} : séance exportée pendant {libellé}, à retirer (op remove)"`, `"semaine {w} : {n} séances pour {max} au plus (semaine allégée)"`.

Arrêt ouvert : fin = dimanche de la semaine de `c.today` (`calendar.plan_start(c.today) + 6 jours`), et au plus tôt `start_date`. Règle 5 : la sortie longue est libre si `long_run_day` est bloqué ou exclu par la semaine allégée cette semaine-là. Un `fatigue` ne bloque rien.

- [ ] **Step 1: Write the failing tests**

```python
def test_session_during_unavailability_is_rejected(): ...
def test_exported_session_during_unavailability_must_be_removed(): ...
def test_open_injury_blocks_until_end_of_current_week():
    # arrêt ouvert depuis mercredi 04/11, today = 05/11 : dimanche 08/11 bloqué, lundi 09/11 libre
def test_open_injury_declared_on_sunday_blocks_only_that_day(): ...   # Review Focus
def test_light_week_limits_sessions_with_fixed_counts():
    # max_sessions=1, une séance done dans la semaine (fixed_counts) + une prévue → erreur
def test_light_week_days_override_available_days(): ...
def test_long_run_free_when_long_run_day_blocked(): ...
def test_fully_blocked_week_may_be_empty():                           # Review Focus
    assert constraint_errors([], c) == []
def test_period_spanning_weeks_and_outside_plan():                    # Review Focus
    # indispo du 28/12 au 10/01 chevauchant 3 semaines, et une indispo commençant avant plan_start
def test_fatigue_does_not_block(): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/plan/test_constraints.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plan): périodes bloquées, arrêt en cours et semaine allégée`

### Task 9: Imprévus dans les prompts

**Files:**
- Modify: `coach/llm/prompts.py`, `coach/services/context.py` (`load_constraints` lit `repo.events`)
- Test: `tests/llm/test_prompts.py`, `tests/services/test_adjust.py`

**Interfaces:**
- Consumes: tâches 6, 8.
- Produces: bloc `"Imprévus :"` dans les deux prompts quand il y en a : une ligne par imprévu en cours ou à venir (`end_date` absente ou ≥ `today`) et par `fatigue` des 14 derniers jours, au format `"- indisponible du 05/11/2026 au 12/11/2026 : {note}"`, `"- blessure/maladie depuis le 05/11/2026 (reprise non connue) : {note}"`, `"- semaine allégée (semaine 3) : 2 séances au plus, jours possibles mardi, samedi"`, `"- fatigue signalée le 02/11/2026 : {note}"`.

- [ ] **Step 1: Write the failing tests** : chacun des quatre formats ; imprévu passé exclu ; `fatigue` de plus de 14 jours exclue ; `ask_adjustment` relance Claude quand la 1re réponse garde une séance pendant une indispo enregistrée en base.
- [ ] **Step 2: Run** `uv run pytest tests/llm/test_prompts.py tests/services/test_adjust.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(llm): imprévus transmis à Claude`

### Task 10: Déclarer, supprimer, reprendre ; synchro suspendue

**Files:**
- Modify: `coach/services/events.py`, `coach/services/adjust.py`, `coach/services/sync.py`, `coach/services/garmin_export.py` (`_warnings`)
- Test: `tests/services/test_events.py`, `tests/services/test_sync.py`, `tests/services/test_garmin_export.py`

**Interfaces:**
- Consumes: tâches 7–9.
- Produces:

```python
# adjust.py
def request_adjustment(repo, garmin, llm, goal_id: int, note: str | None = None) -> int
    # rafraîchit les zones, ask_adjustment(change_note=note), save_proposal, remet settings.proposal_due à False

# events.py
class EventResult(BaseModel):
    event_id: int
    proposal_id: int | None
    error: str | None
def create_event(repo, garmin, llm, goal_id: int, data: EventInput) -> EventResult
def delete_event(repo, event_id: int) -> None
def resume_injury(repo, garmin, llm, event_id: int, resume_date: date) -> EventResult
def event_note(event: Event) -> str   # description française de l'imprévu pour change_note
```

- `create_event` : exige un plan validé (`"Le plan de l'objectif doit être validé"`) ; enregistre l'`Event` et, pour un `fatigue` avec séance `todo`/`exported`, la passe en `missed` (même transaction) ; puis `request_adjustment(note=event_note(e))`. Une `LLMError` est attrapée : `proposal_id=None`, `error=str(e)` (ou le message par défaut de la classe), l'imprévu reste.
- `resume_injury` : l'événement est un arrêt ouvert ; `resume_date` ≥ `start_date` (`"La reprise doit être après le début de l'arrêt"`) ; `end_date = resume_date - 1 jour` (ou `start_date` si reprise le jour même) ; note : `"Reprise après {n} jours d'arrêt ({note}) : reprise progressive, volume et intensité réduits les premières semaines."`.
- `sync` : n'appelle pas `_propose` tant que `repo.open_injury(goal.id)` existe (`proposal_due` reste vrai).
- `_warnings` : `"Pendant ton imprévu : {libellé}"` si `d` tombe dans une période bloquée (`blocked_periods`).

- [ ] **Step 1: Write the failing tests**

```python
def test_create_event_produces_pending_proposal(...): result.proposal_id is not None; ancienne pending → stale
def test_create_event_keeps_event_when_claude_fails(...):  # FakeLLMProvider([]) lève LLMError dès le premier appel
    assert result.proposal_id is None and result.error and repo.events(goal.id)
def test_request_adjustment_after_failure_succeeds(...)
def test_fatigue_marks_session_missed(...)
def test_resume_injury_sets_end_and_asks_progressive_return(...):
    assert "reprise progressive" in llm.calls[-1]
def test_sync_skips_proposal_during_open_injury(...): result.proposal_id is None
def test_deleting_open_injury_resumes_sync_proposals(...)             # Review Focus
def test_export_check_warns_during_event(...)
```

- [ ] **Step 2: Run** `uv run pytest tests/services -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(events): déclarer un imprévu, reprise après un arrêt, synchro suspendue`

### Task 11: Routes des imprévus

**Files:**
- Modify: `coach/api/app.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: tâche 10.
- Produces:
  - `POST /api/goals/{goal_id}/events` (corps `EventInput`) → `EventResult` ;
  - `GET /api/goals/{goal_id}/events` → liste de `_event_dict` (`id, kind, start_date, end_date, max_sessions, days, session_id, note`) ;
  - `DELETE /api/events/{event_id}` → `{"status": "ok"}` (404 `not_found` si absent) ;
  - `POST /api/events/{event_id}/resume` (corps `{"date": "YYYY-MM-DD"}`, `DateBody` existant) → `EventResult` ;
  - `POST /api/goals/{goal_id}/adjust` → `{"proposal_id": int}` (erreurs Claude via les handlers existants) ;
  - `GET /api/plan` ajoute `open_injury: _event_dict | null`.

- [ ] **Step 1: Write the failing tests** : un test par route (succès + 422 de validation + 404).
- [ ] **Step 2: Run** `uv run pytest tests/api/test_app.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): routes des imprévus`

### Task 12: Front — déclarer un imprévu

**Files:**
- Create: `web/src/components/EventDialog.svelte`, `web/src/components/EventDialog.test.ts`
- Modify: `web/src/lib/api.ts`, `web/src/routes/Today.svelte`, `web/src/routes/Plan.svelte`

**Interfaces:**
- Consumes: tâche 11.
- Produces: `api.createEvent(goalId, body) -> Promise<EventResult>`, `api.requestAdjustment(goalId) -> Promise<{proposal_id}>`, `api.events(goalId)`, `api.deleteEvent(id)`, `api.resumeInjury(id, date)` ; type `CoachEvent`. `EventDialog` (props `goal`, `weeks`, `sessions`, `onclose`, `onproposal(id)`) : 1re étape quatre boutons « Indisponible », « Blessure / maladie », « Semaine allégée », « Fatigue / séance ratée » ; 2e étape les champs du type (spec 6.2) ; validation locale des dates ; après envoi, `onproposal(id)` si `proposal_id`, sinon l'erreur et un bouton « Réessayer » qui appelle `requestAdjustment`. Bouton « Signaler un imprévu » sur Aujourd'hui et Plan ; `onproposal` ouvre la page Proposition (même navigation qu'après une synchro).

- [ ] **Step 1: Write the failing tests** : champs affichés par type ; « fin avant début » bloque l'envoi ; semaine allégée envoie `start_date` = lundi choisi et `max_sessions` ; erreur Claude → « Réessayer » appelle `requestAdjustment`.
- [ ] **Step 2: Run** `npm test -- --run` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): déclarer un imprévu`

### Task 13: Front — liste des imprévus, bandeau d'arrêt, reprise

**Files:**
- Create: `web/src/components/EventList.svelte`, `web/src/components/EventList.test.ts`, `web/src/components/InjuryBanner.svelte`, `web/src/components/InjuryBanner.test.ts`
- Modify: `web/src/routes/Plan.svelte`, `web/src/routes/Today.svelte`

**Interfaces:**
- Consumes: tâche 12 (`api.*`).
- Produces: `EventList` (prop `goalId`) affiche les imprévus en cours et à venir avec « Supprimer » ; après suppression, la question « Recalculer le plan ? » (Oui → `requestAdjustment`, puis Proposition). `InjuryBanner` (prop `injury: CoachEvent | null`) : `"Arrêt depuis le {jj/mm} — Signaler la reprise"` ; le bouton ouvre un choix de date (aujourd'hui par défaut) puis `resumeInjury`.

- [ ] **Step 1: Write the failing tests** : imprévu passé non affiché ; suppression → « Recalculer le plan ? » ; bandeau absent sans arrêt ; reprise envoie la date du jour par défaut.
- [ ] **Step 2: Run** `npm test -- --run` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): liste des imprévus et reprise après un arrêt`

# Lot 3 — Vélo

### Task 14: Sport des séances et option vélo de l'objectif

**Files:**
- Modify: `coach/llm/schemas.py` (`SessionSpec`), `coach/plan/models.py` (`Session`, `Goal`, `to_spec`/`from_spec`), `coach/plan/repo.py` (`_migrate`), `coach/services/garmin_export.py` (copie de `"sport"` dans `apply_proposal` modify), `coach/services/plans.py` (`GoalInput`/`GoalUpdate.include_bike`), `coach/api/app.py` (`post_goal` champ `include_bike: bool = False`, `_goal_dict`, `_session_dict`)
- Test: `tests/llm/test_schemas.py`, `tests/plan/test_repo.py`, `tests/services/test_garmin_export.py`, `tests/api/test_app.py`

**Interfaces:**
- Produces: `SessionSpec.sport: Literal["run", "bike"] = "run"`, `Session.sport: str = "run"`, `Goal.include_bike: bool = False`, `PlanConstraints.of` renseigne `include_bike` ; migration `_add_columns(conn, "session", {"sport": "VARCHAR NOT NULL DEFAULT 'run'"})` et `_add_columns(conn, "goal", {"include_bike": "BOOLEAN NOT NULL DEFAULT 0"})` ; `_session_dict["sport"]`, `_goal_dict["include_bike"]` ; `update_goal` note `"vélo autorisé"` / `"plus de vélo"`.

- [ ] **Step 1: Write the failing tests** : `SessionSpec` sans `sport` vaut `"run"` ; ancienne proposition (`changes_json` sans `sport`) acceptée sans erreur ; `modify` vers une séance vélo copie `sport` ; migration d'une base 0.5.0 → `sport == "run"`, `include_bike is False`.
- [ ] **Step 2: Run** `uv run pytest -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plan): sport des séances et option vélo de l'objectif`

### Task 15: Règle et consigne vélo

**Files:**
- Modify: `coach/plan/constraints.py`, `coach/llm/prompts.py`
- Test: `tests/plan/test_constraints.py`, `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes: tâche 14.
- Produces: règle 6 dans `constraint_errors` — messages `"{label} : séance vélo non autorisée pour cet objectif"`, `"{label} : une séance vélo doit être de l'EF ou de la récup ciblée en FC"`, `"{label} : séance vélo limitée aux zones Z1 et Z2"`, `"semaine {w} : au plus une séance vélo"`. Prompts : si `include_bike`, consigne `"Vélo autorisé : tu peux remplacer au plus une séance EF ou récup par semaine par du vélo d'endurance douce (sport \"bike\", target_kind \"hr\", zones Z1 ou Z2), sur route ou home-trainer, jamais à la place d'une séance clé ; compte une durée d'environ 1,3 à 1,5 fois celle de la séance de course remplacée."` ; sans vélo : `"Toutes les séances sont en course à pied (sport \"run\")."` ; `_session_line` et `_done_line` indiquent `vélo` pour `sport == "bike"`.

- [ ] **Step 1: Write the failing tests** : un cas par message ; séance vélo `EF` Z2 en FC valide ; consigne présente ou absente selon `include_bike`.
- [ ] **Step 2: Run** `uv run pytest tests/plan/test_constraints.py tests/llm/test_prompts.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plan): séances vélo d'endurance douce`

### Task 16: Export Garmin et rattachement du vélo

**Files:**
- Modify: `coach/export/garmin_workout.py` (`session_to_workout_json`), `coach/analysis/compliance.py` (`match_activities`), `coach/api/app.py` (`get_free_activities`)
- Test: `tests/export/test_garmin_workout.py`, `tests/analysis/test_compliance.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes: tâche 14.
- Produces: `_SPORT_CYCLING = {"sportTypeId": 2, "sportTypeKey": "cycling"}` utilisé au niveau workout et segment quand `session.sport == "bike"` ; `CYCLING_TYPES` et `activity_types_for(sport: str) -> set[str]` dans `compliance.py` ; `match_activities` ne rattache une séance qu'aux activités de son sport ; `GET /api/activities/free` prend un paramètre facultatif `sport: Literal["run", "bike"] = "run"`.

- [ ] **Step 1: Write the failing tests** : JSON d'un workout vélo (`sportType` cycling aux deux niveaux, cible FC) ; activité `road_biking` rattachée à la séance vélo exportée du jour ; activité `running` non rattachée à une séance vélo, et l'inverse ; `/activities/free?sport=bike` ne renvoie que du vélo.
- [ ] **Step 2: Run** `uv run pytest tests/export tests/analysis tests/api -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(garmin): export et rattachement des séances vélo`

### Task 17: Front vélo

**Files:**
- Modify: `web/src/lib/api.ts` (`Session.sport`, `Goal.include_bike`, `activities/free?sport=`), `web/src/components/AvailabilityFields.svelte` (case vélo, `bind:includeBike`), `web/src/routes/Goal.svelte`, `web/src/components/GoalEditDialog.svelte`, `web/src/components/SessionCard.svelte`, `web/src/components/Icon.svelte` (icône `bike`)
- Test: `web/src/components/AvailabilityFields.test.ts`, `web/src/components/SessionCard.test.ts`, `web/src/components/GoalEditDialog.test.ts`

**Interfaces:**
- Consumes: tâches 14, 16.
- Produces: case « Inclure du vélo (endurance douce, en remplacement de séances faciles) » ; `createGoal` envoie `include_bike` ; `updateGoal` envoie `include_bike` s'il change ; `SessionCard` affiche l'icône vélo et le libellé « Vélo » pour `sport === "bike"` ; le rattachement manuel d'une séance vélo liste les activités vélo.

- [ ] **Step 1: Write the failing tests** : icône vélo présente seulement pour `sport: "bike"` ; `createGoal` reçoit `include_bike: true` ; la boîte de rattachement d'une séance vélo appelle `activities/free?sport=bike`.
- [ ] **Step 2: Run** `npm test -- --run` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test -- --run` puis `uv run pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): séances vélo`

### Task 18: Documentation

**Files:**
- Modify: `README.md`, `ROADMAP.md`

- [ ] **Step 1:** README : un paragraphe « Disponibilités, imprévus et vélo » (jours possibles, sortie longue, « Signaler un imprévu », reprise, vélo d'endurance douce). ROADMAP : ligne cochée dans « Fait ».
- [ ] **Step 2: Run** `uv run pytest -q` et `npm test -- --run` — Expected: PASS.
- [ ] **Step 3: Commit** `docs: disponibilités, imprévus et vélo`
