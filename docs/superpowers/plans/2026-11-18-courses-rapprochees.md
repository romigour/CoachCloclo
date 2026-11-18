# Courses rapprochées et week-ends défi — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** remplacer le refus des objectifs non-Plaisir à moins de 14 jours par des blocs (0–2 jours) et des groupes rapprochés (< 14 jours) avec une course affûtée désignée, transmis à Claude et affichés à l'athlète.

**Architecture :** une règle pure (`proximity`) dans `coach/plan/goals.py` range les objectifs en blocs et groupes et désigne le bloc affûté. `cycle_end` s'en sert pour la fin de cycle, les prompts pour les consignes, l'API pour le `notice` et le libellé de chaque objectif. Pas de migration.

**Tech Stack :** Python 3 / SQLModel / FastAPI (`uv run pytest`), Svelte 5 + vitest (`cd web; npm test`).

**Spec :** `docs/superpowers/specs/2026-11-18-courses-rapprochees-design.md`

## Global Constraints

- Bloc : écart entre deux objectifs consécutifs **≤ 2 jours** (`BLOCK_MAX_GAP_DAYS = 2`) ; les Plaisir en font partie.
- Groupe rapproché : blocs non-Plaisir dont l'écart fin → début est **< 14 jours** (`MIN_GAP_DAYS = 14`, conservé), transitif.
- Bloc affûté : plus haute priorité (principal > secondaire > plaisir) ; à égalité, le **plus tardif**.
- Rôles : `"affute"`, `"integre"` (bloc avant l'affûté), `"rebond"` (bloc après l'affûté).
- Objectifs pris en compte : `active` + `done` dont la date est dans les **14 derniers jours** ; `archived` ignorés. Les `done` ne reçoivent pas de consigne de préparation.
- Plus aucun refus pour écart ; aucune migration de base.
- Textes visibles en français, dates au format `%d/%m` dans les libellés, comme `goal_label`.
- Pas de nouvelle métrique Garmin.

## Review Focus

1. **Un objectif sans id (ajout pas encore enregistré) passé aux prompts** : `proximity` doit le traiter (clé `0`, comme `NEW_GOAL_ID`), sans planter ni le confondre avec un autre. → test dans la tâche 1.
2. **Le jour 2 d'un bloc après que le jour 1 est passé à `done`** (ajustement du dimanche matin) : le prompt garde la consigne de bloc et le texte « objectif unique » n'est pas utilisé. → test dans la tâche 3.
3. **Un objectif Principal seul et loin de tout** : le texte « objectif unique » d'avant les cycles reste inchangé, mot pour mot. → test dans la tâche 3.
4. **Retirer un objectif d'un bloc** : l'autre redevient isolé, sans `notice` ni libellé. → test dans la tâche 5.
5. **Mode lecture seule (Turso, mobile)** : les objectifs n'ont pas `proximity_label` ; la page Objectifs doit s'afficher sans ce champ. → test dans la tâche 6.

---

### Task 1 : règle pure `proximity`

**Files :**
- Modify : `coach/plan/goals.py`
- Test : `tests/plan/test_goals.py`

**Interfaces :**
- Produces (dans `coach/plan/goals.py`) :
  - `BLOCK_MAX_GAP_DAYS = 2`
  - `Role = Literal["affute", "integre", "rebond"]`
  - `@dataclass(frozen=True) class RaceBlock: goals: tuple[Goal, ...]` (triés par date) avec propriétés `start: date`, `end: date`, `priority: str` (la plus haute), `distance_km: float`, `d_plus_m: int` (sommes).
  - `@dataclass(frozen=True) class Proximity: block: RaceBlock; role: Role | None; tapered: RaceBlock | None; group: tuple[RaceBlock, ...]` — `role`, `tapered` à `None` et `group == (block,)` hors groupe rapproché.
  - `goal_key(goal: Goal) -> int` : `goal.id` ou `0` si `None` (même valeur que `NEW_GOAL_ID` des prompts).
  - `race_blocks(goals: Iterable[Goal]) -> list[RaceBlock]` : ignore `archived`, triés par date.
  - `proximity(goals: Iterable[Goal]) -> dict[int, Proximity]` : clé `goal_key`.
  - `block_label(block: RaceBlock) -> str` : libellés datés de ses objectifs joints par `" + "` — « Trail de 20 km (20/03) » pour un bloc d'un objectif, « Trail de 20 km (27/03) + Trail de 30 km (28/03) » sinon.
  - `proximity_label(goal: Goal, prox: dict[int, Proximity]) -> str | None` et `proximity_notice(goal: Goal, prox: dict[int, Proximity]) -> str | None` (textes ci-dessous).
- `gap_conflict` reste pour l'instant (retiré en tâche 4).

- [ ] **Step 1 : écrire les tests qui échouent** (dans `tests/plan/test_goals.py`, avec `make_goal` de `tests/plan/factories.py`)

```python
from datetime import date
from coach.plan.goals import block_label, proximity, proximity_label, proximity_notice, race_blocks

def g(id, d, prio="secondaire", km=20, dplus=450, status="active"):
    return make_goal(id=id, race_date=d, priority=prio, distance_km=km, d_plus_m=dplus, status=status)

def test_blocks_up_to_two_days():
    a, b, c = g(1, date(2027, 3, 27)), g(2, date(2027, 3, 29)), g(3, date(2027, 4, 1))
    blocks = race_blocks([c, a, b])
    assert [[x.id for x in bl.goals] for bl in blocks] == [[1, 2], [3]]

def test_block_includes_plaisir_and_takes_highest_priority():
    a, b = g(1, date(2027, 3, 27), "plaisir"), g(2, date(2027, 3, 28), "secondaire", km=30, dplus=600)
    (bl,) = race_blocks([a, b])
    assert bl.priority == "secondaire" and bl.distance_km == 50 and bl.d_plus_m == 1050
    assert block_label(bl) == "Trail de 20 km (27/03) + Trail de 30 km (28/03)"

def test_user_case_semi_plaisir_outside_group():
    semi = g(1, date(2027, 3, 21), "plaisir", km=21.1, dplus=0)
    sat, sun = g(2, date(2027, 3, 27)), g(3, date(2027, 3, 28), km=30, dplus=600)
    ultra = g(4, date(2027, 5, 22), "principal", km=80, dplus=4000)
    p = proximity([semi, sat, sun, ultra])
    assert p[1].role is None and p[2].role is None and p[4].role is None
    assert p[2].block is p[3].block

def test_tie_tapers_latest_and_earlier_is_integrated():
    a, b = g(1, date(2027, 3, 13)), g(2, date(2027, 3, 20))
    p = proximity([a, b])
    assert p[1].role == "integre" and p[2].role == "affute"
    assert p[1].tapered is p[2].block

def test_higher_priority_first_makes_later_a_rebound():
    a, b = g(1, date(2027, 3, 13), "principal"), g(2, date(2027, 3, 20), "secondaire")
    p = proximity([a, b])
    assert p[1].role == "affute" and p[2].role == "rebond"

def test_group_is_transitive():
    a, b, c = g(1, date(2027, 3, 1)), g(2, date(2027, 3, 12)), g(3, date(2027, 3, 23))
    p = proximity([a, b, c])
    assert [p[i].role for i in (1, 2, 3)] == ["integre", "integre", "affute"]

def test_thirteen_days_grouped_fourteen_not():
    assert proximity([g(1, date(2027, 3, 1)), g(2, date(2027, 3, 14))])[1].role == "integre"
    assert proximity([g(1, date(2027, 3, 1)), g(2, date(2027, 3, 15))])[1].role is None

def test_archived_ignored_recent_done_counted():
    done = g(1, date(2027, 3, 27), status="done")
    arch = g(2, date(2027, 3, 26), status="archived")
    sun = g(3, date(2027, 3, 28))
    p = proximity([done, arch, sun])
    assert 2 not in p and [x.id for x in p[3].block.goals] == [1, 3]

def test_unsaved_goal_keyed_zero():
    new = make_goal(id=None, race_date=date(2027, 3, 28), priority="secondaire")
    p = proximity([g(1, date(2027, 3, 27)), new])
    assert p[0].block is p[1].block

def test_labels_and_notice():
    sat, sun = g(2, date(2027, 3, 27)), g(3, date(2027, 3, 28), km=30, dplus=600)
    p = proximity([sat, sun])
    assert proximity_label(sat, p) == "Bloc avec Trail de 30 km (28/03)"
    assert proximity_notice(sun, p) == (
        "Trail de 20 km (27/03) + Trail de 30 km (28/03) seront préparés comme un seul bloc."
    )
    a, b = g(1, date(2027, 3, 13)), g(4, date(2027, 3, 20))
    p = proximity([a, b])
    assert proximity_label(a, p) == "Intégré à l'affûtage de Trail de 20 km (20/03)"
    assert proximity_notice(a, p) == (
        "Trail de 20 km (13/03) et Trail de 20 km (20/03) sont à moins de 14 jours : "
        "Trail de 20 km (20/03) sera affûté ; Trail de 20 km (13/03) sera intégré à son affûtage."
    )
    alone = g(5, date(2027, 6, 1))
    assert proximity_label(alone, proximity([alone])) is None
    assert proximity_notice(alone, proximity([alone])) is None
```

- [ ] **Step 2 : lancer et constater l'échec**

Run : `uv run pytest tests/plan/test_goals.py -q`
Expected : ImportError sur `proximity`.

- [ ] **Step 3 : implémenter dans `coach/plan/goals.py`**

Règles des textes :
- Libellé daté d'un objectif : `f"{goal_label(g)} ({g.race_date:%d/%m})"` ; `block_label` joint ceux du bloc par `" + "`.
- `proximity_label` : morceaux joints par `" · "` : `"Bloc avec " + autres objectifs du bloc (libellés datés, joints par " + ")` si le bloc a plusieurs objectifs ; `"Intégré à l'affûtage de {block_label(tapered)}"` pour `integre` ; `"Course de rebond après {block_label(tapered)}"` pour `rebond` ; `"Affûté (courses rapprochées)"` pour `affute`. `None` si aucun morceau.
- `proximity_notice` : phrases jointes par `" "` : bloc de plusieurs objectifs → `"{block_label} seront préparés comme un seul bloc."` ; groupe de plusieurs blocs → `"{block_label des blocs joints par ', ' et ' et ' pour le dernier} sont à moins de 14 jours : {tapered} sera affûté"` + pour chaque autre bloc, dans l'ordre des dates, `" ; {bloc} sera intégré à son affûtage"` ou `" ; {bloc} sera une course de rebond"`, puis `"."`.
- Priorité : `{"principal": 3, "secondaire": 2, "plaisir": 1}`.

- [ ] **Step 4 : relancer**

Run : `uv run pytest tests/plan/test_goals.py -q` → Expected : PASS.

- [ ] **Step 5 : commit** — `feat(plan): blocs et groupes de courses rapprochées`

---

### Task 2 : fin de cycle étendue au bloc et au bloc affûté

**Files :**
- Modify : `coach/plan/goals.py` (`cycle_end`)
- Test : `tests/plan/test_goals.py`

**Interfaces :**
- Consumes : `proximity`, `Proximity` (tâche 1).
- Produces : `cycle_end(goals: list[Goal]) -> date | None`, signature inchangée. `next_bounds` (`coach/services/cycles.py`) et `_reshape` (`coach/services/goals.py`) en profitent sans modification.

- [ ] **Step 1 : tests qui échouent**

```python
def test_cycle_end_extends_over_two_day_block():
    p, s = g(1, date(2027, 3, 27), "principal"), g(2, date(2027, 3, 29), "plaisir")
    assert cycle_end([p, s]) == date(2027, 3, 29)

def test_cycle_end_reaches_tapered_block_of_principal_group():
    a, b = g(1, date(2027, 3, 10), "principal"), g(2, date(2027, 3, 18), "principal")
    assert cycle_end([a, b]) == date(2027, 3, 18)

def test_cycle_end_stops_before_rebound():
    a, b = g(1, date(2027, 3, 10), "principal"), g(2, date(2027, 3, 18), "secondaire")
    assert cycle_end([a, b]) == date(2027, 3, 10)

def test_cycle_end_without_principal_is_last_block_end():
    a, b = g(1, date(2027, 3, 27)), g(2, date(2027, 3, 28))
    assert cycle_end([a, b]) == date(2027, 3, 28)
```

Les tests `cycle_end` existants doivent rester verts.

- [ ] **Step 2 : lancer** — `uv run pytest tests/plan/test_goals.py -q` → FAIL sur les deux premiers.

- [ ] **Step 3 : implémenter** : premier Principal `P` (par date) ; `pr = proximity(goals)[goal_key(P)]` ; fin = `pr.tapered.end` si `pr.role == "integre"`, sinon `pr.block.end`. Sans Principal : `race_blocks(goals)[-1].end`. Mettre à jour la docstring.

- [ ] **Step 4 : lancer** `uv run pytest tests/plan tests/services/test_cycles.py tests/services/test_goals.py -q` → PASS (ces services appellent `cycle_end`).

- [ ] **Step 5 : commit** — `feat(plan): fin de cycle étendue aux blocs et au bloc affûté`

---

### Task 3 : consignes à Claude

**Files :**
- Modify : `coach/plan/repo.py`, `coach/llm/prompts.py`, `coach/services/plans.py`, `coach/services/adjust.py`
- Test : `tests/llm/test_prompts.py`, `tests/plan/test_repo.py` (ou le fichier de tests du repo existant)

**Interfaces :**
- Consumes : `proximity`, `block_label`, `goal_key`, `RaceBlock` (tâche 1).
- Produces :
  - `Repo.recent_done_goals(today: date, days: int = 14) -> list[Goal]` : objectifs `done` avec `today - timedelta(days=days) <= race_date <= today`, triés par date.
  - `build_generation_prompt(..., recent: Sequence[Goal] = ())` et `build_adjustment_prompt(..., recent: Sequence[Goal] = ())` : nouveau mot-clé, en dernier.
  - `_cycle_rules(goals, horizon, recent=())`, `_goals_text(goals, horizon, *, generation=False, plan_start=None, recent=())`, `_is_single(goals, horizon, recent=())`.

- [ ] **Step 1 : tests qui échouent** (dans `tests/llm/test_prompts.py`, en suivant les fabriques existantes du fichier)

- `test_secondary_rule_is_proportional` : le prompt de génération d'un cycle à plusieurs objectifs contient `"proportionné"` dans la ligne Secondaire et `"charge de fond du Principal"`.
- `test_block_rules_for_weekend` : cycle sam. 27/03 + dim. 28/03 Secondaires et ultra Principal → le prompt contient `"Trail de 20 km (27/03) + Trail de 30 km (28/03)"`, `"un seul défi"`, `"jambes fatiguées"` (fatigue → estimation de temps de chaque jour) et `"cumul"` ; il ne contient plus `"(enchaînés, à traiter comme un bloc)"` (remplacer l'assertion de la ligne 588 actuelle).
- `test_close_group_rules` : Secondaires 13/03 et 20/03 → contient `"Trail de 20 km (13/03) est intégré à l'affûtage de Trail de 20 km (20/03)"` ; Principal 13/03 + Secondaire 20/03 → contient `"course de rebond après"`.
- `test_rebound_after_done_principal` : cycle avec seulement le Secondaire du 20/03, `recent=[Principal done du 13/03]` → contient `"course de rebond après"` et pas de consigne de préparation pour le 13/03 (pas de ligne `"- 2027-03-13"`).
- `test_day_two_keeps_block_rules_after_day_one_done` *(Review Focus 2)* : `goals=[dimanche Principal]`, `recent=[samedi done]` → contient `"un seul défi"` et pas le texte « objectif unique » (`"Objectif : course de type"`).
- `test_single_goal_text_unchanged` *(Review Focus 3)* : un Principal seul, sans horizon ni `recent` → même texte qu'avant (l'assertion exacte existante reste verte).
- `test_horizon_end_names_tapered_block` : deux Principaux 10/03 et 18/03 dans le cycle et un Principal à l'horizon → `"Termine ce cycle par l'affûtage de Trail de 42 km (18/03)"`.
- `test_horizon_marks_blocks` : cycle avec un Principal, horizon sam. + dim. → la ligne d'horizon du samedi finit par `"(bloc avec Trail de 30 km (28/03))"`.
- Repo : `test_recent_done_goals` : `done` à J-3 inclus, `done` à J-20 exclu, `active` exclu.

- [ ] **Step 2 : lancer** `uv run pytest tests/llm/test_prompts.py -q` → FAIL.

- [ ] **Step 3 : implémenter**

- `PRIORITY_RULES`, ligne Secondaire : séance spécifique dans les 10 jours avant ; mini-affûtage **proportionné** à la taille de la course ou du bloc (quelques jours pour une course courte, jusqu'à environ une semaine pour une course longue ou un bloc) et à sa distance au Principal ; volume réduit, intensité conservée ; récupération après ; la charge de fond du Principal est maintenue. Principal et Plaisir inchangés.
- `_goal_line` perd le paramètre `block` ; `_goals_text` ne liste toujours que `goals` (jamais `recent`).
- `_cycle_rules` calcule `prox = proximity([*goals, *horizon, *recent])` et ajoute, après `RACE_DAY_RULE` :
  - pour chaque bloc de plusieurs objectifs qui contient un objectif de `goals` : « Bloc {block_label} ({distance cumulée} km, {D+ cumulé} m de D+) : un seul défi, affûtage unique avant le premier jour ; prépare les enchaînements dos à dos et, s'il y a du D+, la montée et la descente ; chaque jour se court sur les jambes fatiguées des jours précédents, estime le temps de chaque jour en conséquence ; récupération après dimensionnée sur le cumul. »
  - pour chaque bloc `integre` / `rebond` d'un groupe qui touche `goals` (le bloc lui-même ou l'affûté), dont au moins un objectif est dans `goals` : « {block_label} est intégré à l'affûtage de {tapered} : pas d'affûtage propre, à courir comme une grosse séance d'intensité, récupération courte. » / « {block_label} est une course de rebond après {tapered} : pas d'affûtage, la récupération en tient lieu, objectif réaliste compte tenu de la fatigue. »
  - les règles de priorité s'affichent aussi quand ces lignes existent.
  - lignes d'horizon (spec §5.4) : un objectif de l'horizon dans un bloc de plusieurs objectifs porte le suffixe `" (bloc avec {autres objectifs datés})"` ; test `test_horizon_marks_blocks` dans le Step 1.
  - ligne de fin de cycle de l'horizon : nomme `block_label` du bloc affûté du groupe du premier Principal (rôle `integre`) ou du bloc de ce Principal.
- `_is_single` est faux si `recent` contient un objectif à moins de 14 jours de l'objectif unique.
- `generate_plan` (`services/plans.py`) et `ask_adjustment` (`services/adjust.py`) passent `recent=repo.recent_done_goals(today)`.

- [ ] **Step 4 : lancer** `uv run pytest tests/llm tests/services/test_plans.py tests/services/test_adjust.py tests/plan -q` → PASS.

- [ ] **Step 5 : commit** — `feat(llm): consignes pour blocs et courses rapprochées`

---

### Task 4 : plus de refus, note de récupération du bloc

**Files :**
- Modify : `coach/services/goals.py`, `coach/plan/goals.py` (retrait de `gap_conflict`), `coach/services/plans.py` (`_recovery_note`)
- Test : `tests/services/test_goals.py`, `tests/services/test_plans.py`, `tests/plan/test_goals.py`

**Interfaces :**
- Consumes : `race_blocks`, `block_label` (tâche 1).
- Produces : rien de nouveau ; `GoalError` n'est plus levée pour un écart.

- [ ] **Step 1 : tests qui échouent**

- Remplacer `test_add_goal_gap_conflict_saves_nothing` par `test_add_goal_one_day_after_secondary_is_accepted` : ajout d'un Secondaire le lendemain d'un Secondaire existant → objectif enregistré (`status == "active"`).
- Remplacer `test_update_goal_date_respects_gap` par `test_update_goal_date_close_to_other_is_accepted` : déplacer un objectif à 7 jours d'un autre non-Plaisir → enregistré.
- `test_create_first_ignores_gap` : sans cycle actif, création d'un objectif à 5 jours d'un objectif `active` existant → acceptée (mêmes fixtures que les tests `_create_first` existants).
- `test_recovery_note_names_block` (`test_plans.py`) : cycle dont `recovery_from_goal_id` est le dimanche d'un bloc sam. 27/03 (20 km, 450 m) + dim. 28/03 (30 km, 600 m) tous deux `done` → `_recovery_note(repo, cycle)` vaut « Commence par une récupération adaptée au bloc Trail de 20 km (27/03) + Trail de 30 km (28/03), soit 50 km et 1050 m de D+ en 2 jours. » ; un objectif seul garde le texte actuel.
- Supprimer les tests `gap_conflict` de `tests/plan/test_goals.py`.

- [ ] **Step 2 : lancer** `uv run pytest tests/services/test_goals.py tests/services/test_plans.py -q` → FAIL.

- [ ] **Step 3 : implémenter** : retirer les deux appels à `gap_conflict` (`_reshape` et `_create_first`) et leurs mentions dans les docstrings ; supprimer `gap_conflict` ; `_recovery_note` cherche le bloc de l'objectif dans `race_blocks(repo.past_goals())` et utilise le texte bloc s'il a plusieurs objectifs.

- [ ] **Step 4 : lancer** `uv run pytest -q` → PASS (suite complète).

- [ ] **Step 5 : commit** — `feat(goals): courses rapprochées acceptées, récupération après un bloc`

---

### Task 5 : API — `notice` et `proximity_label`

**Files :**
- Modify : `coach/api/app.py` (`_goal_dict`, `_change_dict`, `/status`, `/cycle`, routes `POST /goals`, `PATCH /goals/{id}`)
- Test : `tests/api/test_app.py`

**Interfaces :**
- Consumes : `proximity`, `proximity_label`, `proximity_notice` (tâche 1), `Repo.recent_done_goals` (tâche 3).
- Produces (JSON) : chaque objectif sérialisé porte `"proximity_label": str | null` ; la réponse de `POST /goals` et `PATCH /goals/{id}` porte `"notice": str | null` ; `DELETE /goals/{id}` porte `"notice": null`.

- [ ] **Step 1 : tests qui échouent**

- `test_post_goal_returns_block_notice` : avec un Secondaire le 27/03 existant, `POST /goals` d'un Secondaire le 28/03 → `notice` contient `"seront préparés comme un seul bloc"` et `goal.proximity_label == "Bloc avec Trail de 20 km (27/03)"` (adapter la distance aux fixtures).
- `test_status_goals_have_proximity_label` : `/status` → `goals[i].proximity_label` renseigné pour les deux, `null` pour un objectif isolé.
- `test_delete_goal_from_block_clears_label` *(Review Focus 4)* : retirer le samedi → `/status` donne `proximity_label` `null` pour le dimanche.

- [ ] **Step 2 : lancer** `uv run pytest tests/api/test_app.py -q` → FAIL.

- [ ] **Step 3 : implémenter** : `_goal_dict(goal, prox: dict[int, Proximity] | None = None)` ajoute `proximity_label` (`None` sans `prox`) ; un helper `_prox(repo)` = `proximity([*repo.upcoming_goals(), *repo.recent_done_goals(date.today())])` ; `/status` et `/cycle` le passent à chaque `_goal_dict` (y compris `past_goals` et `horizon`) ; `_change_dict(result, goal, prox)` ajoute `notice = proximity_notice(goal, prox)` (calculé après l'enregistrement).

- [ ] **Step 4 : lancer** `uv run pytest -q` → PASS.

- [ ] **Step 5 : commit** — `feat(api): avertissement et libellé des courses rapprochées`

---

### Task 6 : web — bandeau et libellé

**Files :**
- Modify : `web/src/lib/api.ts`, `web/src/routes/Goal.svelte`
- Test : `web/src/routes/Goal.test.ts`

**Interfaces :**
- Consumes : JSON de la tâche 5.
- Produces : `Goal.proximity_label?: string | null` ; `PlanChange.notice?: string | null` (champs facultatifs : absents en mode lecture seule Turso).

- [ ] **Step 1 : tests qui échouent** (en suivant les mocks d'API existants de `Goal.test.ts`)

- `shows notice after adding a goal` : `addGoal` renvoie `{ proposal_id: null, needs_generation: true, notice: "… seront préparés comme un seul bloc.", goal }` → le texte apparaît dans un élément `role="status"`.
- `shows proximity label under goal` : statut avec `proximity_label: "Bloc avec Trail de 30 km (28/03)"` → texte affiché sous l'objectif.
- `renders goals without proximity_label` *(Review Focus 5)* : objectifs sans le champ → la liste s'affiche, aucun libellé vide.

- [ ] **Step 2 : lancer** `cd web; npm test -- Goal` → FAIL.

- [ ] **Step 3 : implémenter** : dans `changed(r)`, garder `r.notice` dans un état `notice` affiché en `<p class="card" role="status">` au-dessus de la liste, effacé à l'action suivante ; quand `proposal_id` redirige vers `#/proposal`, le libellé persistant de la liste suffit. Sous `details(g)`, `{#if g.proximity_label}<span class="meta">{g.proximity_label}</span>{/if}`.

- [ ] **Step 4 : lancer** `cd web; npm test` → PASS.

- [ ] **Step 5 : commit** — `feat(web): courses rapprochées sur la page Objectifs`
