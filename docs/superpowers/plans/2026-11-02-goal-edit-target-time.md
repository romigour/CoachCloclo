# Temps visé de l'objectif et modification d'un objectif en cours — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** L'objectif porte un temps visé (fixé par l'athlète ou estimé par Claude) qui oriente le
plan et la stratégie du jour J, et un objectif en cours peut changer de date et de temps visé avec
une proposition d'ajustement de Claude.

**Architecture :** Deux colonnes sur `Goal` (ajoutées à chaud par une migration idempotente).
L'estimation arrive dans la réponse de génération (`PlanResponse.estimated_time_s`). La demande
d'ajustement de `sync._propose` est extraite dans `coach/services/adjust.py` pour servir aussi à
`update_goal`, qui enregistre objectif, retraits et proposition dans une seule transaction après
la réponse de Claude. La stratégie Jour J lit le temps sur l'objectif.

**Tech Stack :** Python 3 / FastAPI / SQLModel (SQLite) / pytest ; Svelte 5 / Vitest.

**Spec :** `docs/superpowers/specs/2026-11-02-goal-edit-target-time-design.md`

## Global Constraints

- Textes de l'interface, messages d'erreur, docstrings et commentaires en français, style du code existant.
- Format du temps saisi : `h:mm` (« 3:45 » = 3 h 45), `h:mm:ss` accepté ; c'est la règle de `parseTargetTime` dans `web/src/lib/race.ts`.
- Vraisemblance : allure moyenne pas plus rapide que 150 s/km (2:30/km) sur `goal.distance_km`.
- `target_source` vaut `"user"`, `"claude"` ou `None` ; toute modification du temps le passe à `"user"`.
- Seuls `race_date` et `target_time` sont modifiables sur un objectif en cours (actif et `plan_accepted`).
- Une modification ne laisse aucune trace en base si l'appel à Claude échoue.
- Erreurs métier : `GoalError` (sous-classe de `CoachError`) → 422 par le gestionnaire existant.
- Commandes : `uv run pytest` (racine) ; `cd web && npm test` (Vitest).
- Pas de signature ni de trailer Claude dans les messages de commit.

## Review Focus

1. **Date avancée dans la semaine courante** : nouvelle date ce dimanche alors qu'on est mardi → `n_weeks` = semaine courante, toutes les séances des semaines suivantes retirées, Claude ne peut ajouter qu'en semaine courante. Test : `test_update_goal_date_in_current_week` (tâche 6).
2. **Séance exportée programmée après la nouvelle date mais dans la dernière semaine** : elle doit être retirée et marquée pour nettoyage Garmin, pas laissée sur la montre. Test : `test_update_goal_removes_exported_after_race_day` (tâche 6).
3. **Proposition de synchro en attente au moment de la modification** : elle référence peut-être des séances retirées ; elle doit passer `stale`. Test : `test_update_goal_makes_pending_stale` (tâche 6).
4. **Base ouverte deux fois après migration** : la recopie du temps de la stratégie ne doit se faire qu'à l'ajout des colonnes, jamais écraser un temps modifié ensuite. Test : `test_migration_is_idempotent` (tâche 1).
5. **Estimation absurde de Claude** (ex. 600 s pour un marathon) : rejetée par `validate_plan` comme une erreur métier, donc relancée. Test : `test_validate_plan_rejects_implausible_estimate` (tâche 2).

---

### Task 1 : Colonnes du temps visé et migration

**Files :**
- Modify : `coach/plan/models.py` (classe `Goal`)
- Modify : `coach/plan/repo.py` (`make_engine`)
- Test : `tests/plan/test_repo.py`

**Interfaces :**
- Produces : `Goal.target_time_s: int | None = None`, `Goal.target_source: str | None = None` (commentaire `# "user" | "claude"`) ; `_migrate(engine: Engine) -> None` dans `repo.py`, appelée par `make_engine` après `create_all`.

- [ ] **Step 1 : Tests qui échouent**

```python
def _old_schema_db(path):
    """Base à l'ancien schéma : table goal sans les colonnes du temps visé, stratégie avec temps."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE goal (id INTEGER PRIMARY KEY, created_at DATETIME, type VARCHAR, distance_km FLOAT,
            d_plus_m INTEGER, race_date DATE, sessions_per_week INTEGER, gpx_path VARCHAR,
            gpx_summary_json VARCHAR, status VARCHAR, plan_start DATE, plan_accepted BOOLEAN);
        INSERT INTO goal VALUES (1, '2026-11-01', 'route', 21.1, 0, '2027-02-07', 4, NULL, NULL, 'active', '2026-11-02', 1);
        INSERT INTO goal VALUES (2, '2026-10-01', 'route', 10, 0, '2026-12-07', 3, NULL, NULL, 'archived', '2026-10-05', 1);
    """)
    con.commit(); con.close()
    # la table racestrategy est créée par create_all ; on y insère après le premier make_engine

def test_migration_adds_columns_and_copies_strategy_target(tmp_path): ...
    # crée l'ancien schéma + une racestrategy (goal_id=1, settings_json='{"target_time_s": 6600}')
    # via sqlite3 avec CREATE TABLE racestrategy minimal, puis Repo(make_engine(path))
    # assert repo.active_goal().target_time_s == 6600 and .target_source == "user"
    # assert le goal 2 (sans stratégie) a target_time_s None et target_source None

def test_migration_is_idempotent(tmp_path): ...
    # après la 1re ouverture, mettre goal 1 à target_time_s=7000 ; rouvrir make_engine(path)
    # assert target_time_s == 7000 (pas d'écrasement par la stratégie)

def test_new_goal_has_no_target(repo):
    g = repo.add(make_goal())
    assert g.target_time_s is None and g.target_source is None
```

Le premier test crée la table `racestrategy` à la main (colonnes de `RaceStrategy` dans `models.py`) avant d'appeler `make_engine`.

- [ ] **Step 2 : Lancer** `uv run pytest tests/plan/test_repo.py -k "migration or no_target" -v` → FAIL (colonnes absentes).

- [ ] **Step 3 : Implémenter** les deux champs sur `Goal` et `_migrate` : lire `PRAGMA table_info(goal)` ; si `target_time_s` manque, `ALTER TABLE goal ADD COLUMN target_time_s INTEGER`, `ALTER TABLE goal ADD COLUMN target_source VARCHAR`, puis pour chaque ligne de `racestrategy`, `json.loads(settings_json).get("target_time_s")` non nul → `UPDATE goal SET target_time_s=?, target_source='user' WHERE id=?`. Tout dans `engine.begin()`.

- [ ] **Step 4 : Lancer** `uv run pytest tests/plan -v` → PASS.

- [ ] **Step 5 : Commit** `feat(goal): colonnes du temps visé et migration de la base`

---

### Task 2 : Temps visé dans les schémas et les prompts

**Files :**
- Modify : `coach/llm/schemas.py` (`PlanResponse`, `validate_plan`, `validate_adjustment`)
- Modify : `coach/llm/prompts.py` (`_goal_text`, `build_generation_prompt`, `build_adjustment_prompt`)
- Modify : `coach/services/sync.py` (passer `n_weeks` à `validate_adjustment`)
- Test : `tests/llm/test_schemas.py`, `tests/llm/test_prompts.py`

**Interfaces :**
- Consumes : `Goal.target_time_s`, `Goal.target_source` (tâche 1).
- Produces :
  - `PlanResponse.estimated_time_s: int | None = None`
  - `validate_plan(plan, *, n_weeks, sessions_per_week, pace_available, estimate_min_s: int | None = None) -> list[str]` — `estimate_min_s` non `None` = estimation exigée et ≥ cette valeur.
  - `validate_adjustment(..., n_weeks: int, ...)` (mot-clé obligatoire).
  - `build_generation_prompt(...)` inchangé en signature : la consigne dépend de `goal.target_source`.
  - `build_adjustment_prompt(..., change_note: str | None = None)`.

- [ ] **Step 1 : Tests qui échouent**

```python
# test_schemas.py
def test_validate_plan_requires_estimate():
    errs = validate_plan(plan_without_estimate, n_weeks=..., sessions_per_week=..., pace_available=True, estimate_min_s=1000)
    assert any("estimated_time_s" in e for e in errs)

def test_validate_plan_rejects_implausible_estimate():
    # estimated_time_s=600, estimate_min_s=1000 → une erreur mentionnant estimated_time_s

def test_validate_plan_ignores_estimate_when_not_required():
    # estimated_time_s=None, estimate_min_s=None → []

def test_adjustment_rejects_week_beyond_plan():
    # add en semaine 15 avec n_weeks=14 → erreur "semaine 15 : au-delà de la dernière semaine du plan (14)"

# test_prompts.py
def test_goal_text_includes_target():
    assert "Temps visé : 1 h 50" in _goal_text(make_goal(target_time_s=6600, target_source="user"))

def test_generation_prompt_asks_estimate_in_claude_mode():
    p = build_generation_prompt(make_goal(target_source="claude"), ...)
    assert "estimated_time_s" in p and "Estime" in p

def test_generation_prompt_targets_user_time():
    p = build_generation_prompt(make_goal(target_time_s=6600, target_source="user"), ...)
    assert "Construis le plan pour atteindre ce temps visé" in p and "Estime" not in p

def test_adjustment_prompt_includes_change_note():
    p = build_adjustment_prompt(..., change_note="L'athlète a modifié son objectif : X")
    assert p.index("L'athlète a modifié") < p.index("Nous sommes en semaine")
```

- [ ] **Step 2 : Lancer** `uv run pytest tests/llm -v` → FAIL.

- [ ] **Step 3 : Implémenter.**
  - `_goal_text` ajoute ` Temps visé : {_fmt_duration(t)}.` quand `goal.target_time_s` est renseigné.
  - `build_generation_prompt`, après la consigne de semaines : si `goal.target_source == "claude"` et pas de temps, la consigne de la spec 4.1 (« Estime d'abord un temps réaliste … `estimated_time_s` (en secondes), puis construis le plan pour ce temps. ») ; si un temps est connu : « Construis le plan pour atteindre ce temps visé (allures cibles, volume). »
  - `build_adjustment_prompt` insère `change_note` juste après `_goal_text(goal)`.
  - `validate_adjustment` : erreur `f"{label} : semaine {w}, au-delà de la dernière semaine du plan ({n_weeks})"`.
  - `sync._propose` passe `n_weeks=calendar.n_weeks(goal.plan_start, goal.race_date)` (remplacé en tâche 4).
  - Ajouter `n_weeks=` (assez grand pour ne rien changer, ex. 52) aux appels existants de `validate_adjustment` dans `tests/llm/test_schemas.py`.

- [ ] **Step 4 : Lancer** `uv run pytest tests/llm tests/services/test_sync.py -v` → PASS.

- [ ] **Step 5 : Commit** `feat(llm): temps visé et estimation dans les prompts et les schémas`

---

### Task 3 : Création de l'objectif avec temps visé ou estimation

**Files :**
- Modify : `coach/services/plans.py` (`GoalInput`, `create_goal`, `generate_plan`, nouvelles fonctions)
- Modify : `coach/api/app.py` (`post_goal`, `_goal_dict`)
- Test : `tests/services/test_plans.py`, `tests/api/test_app.py`

**Interfaces :**
- Consumes : tâche 2 (`estimate_min_s`, `estimated_time_s`).
- Produces (dans `plans.py`) :
  - `MIN_PACE_S_KM = 150` et `TOO_FAST = "Temps visé invraisemblable : allure moyenne plus rapide que 2:30/km (format attendu h:mm, ex. 3:45)"` (déplacés depuis `race_strategy.py`, qui les importera en tâche 5).
  - `parse_target_time(text: str) -> int` — même règle que le front ; sinon `GoalError("Temps visé invalide : format attendu h:mm, ex. 3:45")`.
  - `check_target_time(seconds: int, distance_km: float) -> None` — `GoalError(TOO_FAST)` si `seconds < MIN_PACE_S_KM * distance_km`.
  - `GoalInput.target_time_s: int | None = Field(None, gt=0)`.
  - `_goal_dict` expose `target_time_s` et `target_source`.

- [ ] **Step 1 : Tests qui échouent**

```python
def test_parse_target_time():
    assert parse_target_time("3:45") == 13500 and parse_target_time("1:05:30") == 3930
    for bad in ("", "3h45", "3:75", "0:00"):
        with pytest.raises(GoalError): parse_target_time(bad)

def test_create_goal_with_user_time(repo, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(target_time_s=18000))
    assert (g.target_time_s, g.target_source) == (18000, "user")

def test_create_goal_without_time_is_claude_mode(repo, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input())
    assert (g.target_time_s, g.target_source) == (None, "claude")

def test_create_goal_rejects_implausible_time(repo, fake_garmin):
    with pytest.raises(GoalError, match="invraisemblable"):
        create_goal(repo, fake_garmin, goal_input(target_time_s=3600))  # 42 km en 1 h
    assert repo.active_goal() is None

def test_generate_saves_claude_estimate(repo, coach_home, fake_garmin):
    # FakeLLMProvider([valid_plan_json(..., estimated_time_s=19800)]) → goal.target_time_s == 19800

def test_regenerate_reestimates(...)   # 2e génération avec 20400 → 20400, source toujours "claude"

def test_generate_keeps_user_time(...) # source "user", réponse avec estimated_time_s=1 → temps inchangé
```

Si `valid_plan_json` (dans `tests/llm/factories.py`) n'accepte pas `estimated_time_s`, lui ajouter le paramètre.
Côté API :

```python
def test_post_goal_with_target_time(client):  # data={**GOAL_FORM, "target_time": "1:50"} → 200, json target_time_s == 6600, target_source == "user"
def test_post_goal_bad_target_time(client):   # "target_time": "abc" → 422
```

- [ ] **Step 2 : Lancer** `uv run pytest tests/services/test_plans.py tests/api/test_app.py -k "goal or target or generate" -v` → FAIL.

- [ ] **Step 3 : Implémenter.**
  - `create_goal` : `check_target_time` si un temps est fourni ; `target_source = "user" if data.target_time_s else "claude"`.
  - `generate_plan` : `estimate_min_s = round(MIN_PACE_S_KM * goal.distance_km) if goal.target_source == "claude" else None` ; dans la transaction, si `g.target_source == "claude"`, `g.target_time_s = plan.estimated_time_s`.
  - `post_goal` : `target_time: Annotated[str | None, Form()] = None`, converti par `parse_target_time` quand il est non vide.

- [ ] **Step 4 : Lancer** `uv run pytest -v` → PASS.

- [ ] **Step 5 : Commit** `feat(goal): temps visé fixé ou estimé par Claude à la création`

---

### Task 4 : Module d'ajustement partagé

**Files :**
- Create : `coach/services/adjust.py`
- Modify : `coach/services/sync.py` (`_propose` délègue)
- Test : `tests/services/test_adjust.py` ; `tests/services/test_sync.py` doit rester vert sans modification.

**Interfaces :**
- Produces :
  - `ask_adjustment(repo: Repo, garmin: GarminPort, llm: LLMProvider, goal: Goal, zones: Zones, sessions: list[Session], today: date, *, done: list[tuple[Session, Activity]] = (), missed: list[Session] = (), change_note: str | None = None) -> AdjustmentResponse` — calcule `current_week`, séances à venir, comptes par semaine, comparaisons, `n_weeks` depuis `goal` (éventuellement non enregistré), construit le prompt et appelle `ask_structured` avec `validate_adjustment`. N'écrit rien.
  - `save_proposal(db: DbSession, adj: AdjustmentResponse) -> int` — passe les `pending` en `stale`, ajoute la `Proposal`, `flush`, renvoie l'id.

- [ ] **Step 1 : Tests qui échouent**

```python
def test_ask_adjustment_writes_nothing(repo, coach_home, fake_garmin, accepted_plan):
    adj = ask_adjustment(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), goal, zones, repo.sessions(goal.id), TODAY)
    assert repo.pending_proposal() is None and adj.analysis

def test_ask_adjustment_passes_change_note(...):  # le prompt reçu par FakeLLMProvider contient la note

def test_save_proposal_stales_previous(repo):
    with repo.transaction() as db: first = save_proposal(db, adj_a)
    with repo.transaction() as db: second = save_proposal(db, adj_b)
    # first est "stale", second "pending"
```

Réutiliser les fixtures `accepted_plan` et `adjustment_json` de `test_sync.py` (les déplacer dans `tests/services/conftest.py` si besoin). Les prompts reçus sont dans `FakeLLMProvider.calls`.

- [ ] **Step 2 : Lancer** `uv run pytest tests/services/test_adjust.py -v` → FAIL.

- [ ] **Step 3 : Implémenter** en déplaçant le corps de `_propose` ; `_propose` devient `adj = ask_adjustment(...)` puis `with repo.transaction() as db: return save_proposal(db, adj)`.

- [ ] **Step 4 : Lancer** `uv run pytest tests/services -v` → PASS.

- [ ] **Step 5 : Commit** `refactor(sync): demande d'ajustement réutilisable`

---

### Task 5 : Stratégie du jour J sur le temps de l'objectif

**Files :**
- Modify : `coach/analysis/race_plan.py` (`RaceSettings`, `build_race_plan`)
- Modify : `coach/services/race_strategy.py` (`_compute`, `_fingerprint`, `_view`, `RaceView`, `export_race`, `_NO_REFERENCE`)
- Test : `tests/analysis/test_race_plan.py`, `tests/services/test_race_strategy.py`, `tests/api/test_app.py`, `tests/export/test_garmin_workout.py` (appel direct de `build_race_plan`)

**Interfaces :**
- Consumes : `Goal.target_time_s`, `Goal.target_source` ; `TOO_FAST`, `MIN_PACE_S_KM` (tâche 3).
- Produces :
  - `RaceSettings` sans `target_time_s` (les clés inconnues restent ignorées).
  - `build_race_plan(*, ..., settings, today, target_time_s: int | None = None) -> RacePlan`.
  - `_fingerprint(strategy: RaceStrategy, goal: Goal) -> str` — sha256 de `settings_json|basis_json|race_date|target_time_s`.
  - `RaceView.target_time_s: int | None`, `RaceView.target_source: str | None`.
  - `_NO_REFERENCE = "Pas de temps de référence : fixe un temps visé sur l'objectif"`.

- [ ] **Step 1 : Adapter et ajouter les tests**
  - Dans `test_race_plan.py`, remplacer `RaceSettings(target_time_s=X, …)` par `plan(..., target_time_s=X)` (le helper `plan` transmet le paramètre).
  - Dans `test_race_strategy.py`, les tests qui passaient le temps par `save_settings` posent `goal.target_time_s` via le repo ; supprimer ceux qui testaient `_TOO_FAST` dans `save_settings` (couverts en tâche 3).
  - Nouveaux tests :

```python
def test_view_uses_goal_target(...):  # goal.target_time_s=3600, source "claude" → view.plan.target_time_s == 3600, view.target_source == "claude"
def test_old_settings_with_target_still_load(...):  # settings_json avec "target_time_s": 999 → get_race_view OK, cible = celle de l'objectif
def test_export_stale_after_goal_date_change(...):  # export, puis goal.race_date += 7 j → export_stale is True
def test_export_stale_after_goal_target_change(...)
```
  - Dans `test_app.py` (~l. 840), le `PUT` du temps visé devient un `PUT` de réglages sans temps ; vérifier `target_time_s` dans la vue.

- [ ] **Step 2 : Lancer** `uv run pytest tests/analysis/test_race_plan.py tests/services/test_race_strategy.py -v` → FAIL.

- [ ] **Step 3 : Implémenter.** `build_race_plan` lit `target_time_s` en paramètre ; `_compute` passe `goal.target_time_s` et retire le contrôle `_TOO_FAST` ; `_view`, `export_race` passent `goal` à `_fingerprint`. Les exports Jour J faits avant la mise à jour apparaissent une fois « à réexporter » (empreinte changée) : acceptable.

- [ ] **Step 4 : Lancer** `uv run pytest -v` → PASS.

- [ ] **Step 5 : Commit** `feat(race): la stratégie du jour J reprend le temps visé de l'objectif`

---

### Task 6 : Modifier un objectif en cours (service et API)

**Files :**
- Modify : `coach/services/plans.py` (`GoalUpdate`, `update_goal`)
- Modify : `coach/services/garmin_export.py` (rendre `_mark_for_cleanup` public : `mark_for_cleanup`)
- Modify : `coach/api/app.py` (`PATCH /goals/{goal_id}`)
- Test : `tests/services/test_plans.py`, `tests/api/test_app.py`

**Interfaces :**
- Consumes : `ask_adjustment`, `save_proposal` (tâche 4) ; `parse_target_time`, `check_target_time` (tâche 3) ; `refresh_snapshot` (`coach.services.context`) pour les zones.
- Produces :
  - `class GoalUpdate(BaseModel): race_date: date | None = None; target_time: str | None = None`
  - `update_goal(repo, garmin, llm, goal_id: int, data: GoalUpdate) -> tuple[Goal, int]` (objectif enregistré, id de la proposition).
  - `PATCH /api/goals/{goal_id}`, corps JSON `GoalUpdate`, réponse `{"goal": _goal_dict(goal), "proposal_id": id}`.

- [ ] **Step 1 : Tests qui échouent** (objectif validé avec plan de 14 semaines, aujourd'hui = 2026-11-02 sauf mention)

```python
def test_update_goal_target_only(...):
    # target_time="5:30" → goal.target_time_s == 19800, source "user", race_date inchangée, proposition pending
    # le prompt envoyé contient "temps visé 5 h 30 au lieu de"

def test_update_goal_earlier_date_removes_weeks(...):
    # race_date avancée de 2 semaines → aucune séance todo en semaines 13-14 ;
    # les exported de ces semaines ont pending_removal True

def test_update_goal_date_in_current_week(...):
    # race_date = dimanche 2026-11-08 → n_weeks 1 ; toutes les séances todo des semaines ≥ 2 supprimées

def test_update_goal_removes_exported_after_race_day(...):
    # séance exported en dernière semaine, scheduled_date = race_date + 1 → marquée pour retrait

def test_update_goal_later_date_allows_new_weeks(...):
    # +2 semaines, réponse Claude avec un add en semaine 16 → accepté (proposition créée)

def test_update_goal_makes_pending_stale(...)

def test_update_goal_llm_failure_changes_nothing(...):
    # FakeLLMProvider avec deux réponses invalides → LLMInvalidResponse remonte ; date, temps, séances et propositions inchangés

def test_update_goal_rejections(...):
    # race_date <= aujourd'hui ; target_time "abc" ; target_time invraisemblable ;
    # mêmes valeurs qu'avant ou corps vide → GoalError("Aucune modification") ;
    # objectif non validé (plan_accepted False) ou archivé → GoalError
```

API :

```python
def test_patch_goal(client, ...):     # 200, json["goal"]["target_time_s"], json["proposal_id"] int
def test_patch_goal_invalid(client):  # {"race_date": "2020-01-01"} → 422
```

- [ ] **Step 2 : Lancer** `uv run pytest tests/services/test_plans.py tests/api/test_app.py -k update_goal -v` → FAIL.

- [ ] **Step 3 : Implémenter `update_goal`** selon la spec 4.3 :
  1. charger l'objectif (actif et `plan_accepted`), valider, construire `edited = goal.model_copy(update=…)` ;
  2. `n = calendar.n_weeks(goal.plan_start, edited.race_date)` ; `removed` = séances `todo`/`exported` avec `week_index > n` ou `scheduled_date > edited.race_date` ;
  3. note : « L'athlète a modifié son objectif : » + « course déplacée du {ancienne} au {nouvelle} » (dates `jj/mm/aaaa`) et/ou « temps visé {nouveau} au lieu de {ancien} » (`_fmt_duration` de `coach.llm.prompts`, renommé `fmt_duration` pour l'import ; « temps visé 5 h 30, aucun auparavant » si l'ancien est vide), joints par « ; », puis « Adapte les séances à venir en conséquence. » ;
  4. `adj = ask_adjustment(..., edited, zones, [s for s in sessions if s not in removed], today, change_note=note)` ;
  5. une transaction : recopier `race_date`, `target_time_s`, `target_source` sur la ligne `Goal` ; supprimer les `todo` retirées ; `mark_for_cleanup(s, removal=True)` sur les `exported` retirées ; `save_proposal(db, adj)`.

- [ ] **Step 4 : Lancer** `uv run pytest -v` → PASS.

- [ ] **Step 5 : Commit** `feat(goal): modifier la date et le temps visé d'un objectif en cours`

---

### Task 7 : Interface — création avec temps visé

**Files :**
- Modify : `web/src/lib/api.ts` (`Goal`, `GoalInput`, `createGoal`, `RaceView`, `updateGoal`, helper `patch`)
- Modify : `web/src/routes/Goal.svelte`
- Test : `web/src/routes/Goal.test.ts`

**Interfaces :**
- Produces :
  - `Goal` gagne `target_time_s: number | null; target_source: "user" | "claude" | null`.
  - `GoalInput.target_time?: string` ; `createGoal` l'envoie s'il est renseigné.
  - `RaceView` gagne `target_time_s` et `target_source`.
  - `const patch = <T>(p: string, b: unknown) => request<T>("PATCH", p, b)` ; `api.updateGoal(goalId: number, body: { race_date?: string; target_time?: string }) => patch<{ goal: Goal; proposal_id: number }>(...)`.
  - `goalTimeLabel(g: Goal): string | null` dans `web/src/lib/race.ts` : « Temps estimé par Claude : 1 h 52 » / « Temps visé : 1 h 50 » / `null`.

- [ ] **Step 1 : Tests qui échouent**

```ts
test("target time defaults to Claude estimate", ...)   // radio « Laisser Claude estimer » coché, pas de champ « Temps visé (h:mm) »
test("choosing my own time shows the field and sends it", ...)  // clic « Je fixe mon temps », saisie « 1:50 », submit → FormData du fetch contient target_time = "1:50"
test("invalid own time blocks submit", ...)  // « 1h50 » → message d'erreur, aucun POST /goals
test("draft shows Claude estimate", ...)     // plan brouillon avec goal.target_source "claude", target_time_s 6720 → texte « Temps estimé par Claude : 1 h 52 »
```
  Plus `goalTimeLabel` dans `web/src/lib/race.test.ts`.

- [ ] **Step 2 : Lancer** `cd web && npx vitest run src/routes/Goal.test.ts src/lib/race.test.ts` → FAIL.

- [ ] **Step 3 : Implémenter** le fieldset « Temps visé » (légende exacte, radios « Laisser Claude estimer » / « Je fixe mon temps », champ `Temps visé (h:mm)` validé par `parseTargetTime`) et la ligne du brouillon via `goalTimeLabel`.

- [ ] **Step 4 : Lancer** `cd web && npm test` → PASS.

- [ ] **Step 5 : Commit** `feat(web): choix du temps visé à la création de l'objectif`

---

### Task 8 : Interface — modification et Jour J en lecture seule

**Files :**
- Create : `web/src/components/GoalEditDialog.svelte`, `web/src/components/GoalEditDialog.test.ts`
- Modify : `web/src/routes/Goal.svelte` (carte « Objectif en cours »)
- Modify : `web/src/routes/Race.svelte`, `web/src/routes/Race.test.ts`
- Modify : `ROADMAP.md`

**Interfaces :**
- Consumes : `api.updateGoal`, `goalTimeLabel`, `parseTargetTime`, `fmtTargetTime` (tâche 7).
- Produces : `GoalEditDialog` avec props `{ goal: Goal; today: string; onclose: () => void; onsaved: (proposalId: number) => void }`, sur le modèle d'`ExportDialog.svelte`.

- [ ] **Step 1 : Tests qui échouent**

```ts
// GoalEditDialog.test.ts
test("prefills date and target time", ...)        // champs = race_date et fmtTargetTime(target_time_s)
test("sends only changed fields", ...)            // ne change que le temps → corps PATCH { target_time: "1:55" }
test("shows the new-goal hint", ...)              // « Pour changer la distance ou le type de course, crée un nouvel objectif. »
test("keeps dialog open with error on failure", ...) // fetch 422 → message affiché, onsaved non appelé
test("no change disables save", ...)
// Race.test.ts
test("target time is read-only with link to goal", ...) // pas de champ « Temps visé » ; texte « Temps visé : 1 h 52 · estimé par Claude » ; lien « Modifier l'objectif » vers #/goal
test("no goal time falls back to prediction label", ...) // « Pas de temps visé, référence : prédiction »
```

- [ ] **Step 2 : Lancer** `cd web && npx vitest run src/components/GoalEditDialog.test.ts src/routes/Race.test.ts` → FAIL.

- [ ] **Step 3 : Implémenter.**
  - Carte « Objectif en cours » de `Goal.svelte` : ajouter `goalTimeLabel(active)` et un bouton « Modifier » qui ouvre le dialogue. À l'enregistrement : état `busy = "Claude ajuste ton plan… (cela peut prendre une minute)"` pendant l'appel, puis `onchanged?.()` et `location.hash = "#/proposal"`.
  - `Race.svelte` : retirer `targetText`, `parsedTarget`, `targetInvalid` et le champ ; `current` = `draft` ; afficher la ligne en lecture seule à partir de `view.target_time_s` et `view.target_source`.
  - `ROADMAP.md` : ajouter sous « Fait » : `- [x] Temps visé de l'objectif (fixé ou estimé par Claude) et modification de la date et du temps d'un objectif en cours`.

- [ ] **Step 4 : Lancer** `cd web && npm test && npm run build`, puis `uv run pytest` → PASS.

- [ ] **Step 5 : Commit** `feat(web): modifier l'objectif en cours, temps visé en lecture seule au Jour J`
