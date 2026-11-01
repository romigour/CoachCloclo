# Prévu / réalisé étape par étape — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rapprocher les tours Garmin des étapes du workout d'une séance réalisée, l'afficher dans la carte de séance et le transmettre à Claude lors de l'ajustement.

**Architecture:** Les tours sont lus par une nouvelle méthode du port Garmin, stockés dans une table `ActivityLaps` (synchro et rattachement manuel), puis comparés à la lecture par une fonction pure `compare_session` (`coach/analysis/laps.py`). Le même `StepComparison` alimente `GET /sessions/{id}/comparison`, la carte de séance Svelte et le prompt d'ajustement.

**Tech Stack:** Python 3 / FastAPI / SQLModel (SQLite) / pydantic / `garminconnect` ; Svelte 5 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-01-laps-vs-steps-design.md`

## Global Constraints

- Commentaires, docstrings, messages et libellés en français, comme le reste du code.
- Pas de migration : uniquement une nouvelle table (`create_all` ne modifie pas les tables existantes, aucune colonne n'est ajoutée à `Activity`).
- Une erreur Garmin sur les tours (`GarminUnavailable`, `GarminRateLimited`, `GarminAuthRequired`) ne fait jamais échouer une synchro ni un rattachement manuel : journalisée (`logging.getLogger(__name__)`), ignorée.
- Pas de tolérance sur les verdicts : les bornes de zone font foi.
- Zones du verdict : dernier `AthleteSnapshot` (`Zones.model_validate_json(snap.zones_json)`) ; sans snapshot, aucun verdict.
- Plafond du mode dégradé dans le prompt : 30 tours, puis `… N tours de plus`.
- Messages de commit au format du dépôt (`feat(laps): …`), sans signature ni trailer Claude.
- Tests Python : `uv run pytest` (les tests `live` sont exclus par défaut) ; front : `npm test` dans `web/`.

## Review Focus

- Activité rattachée dont Garmin renvoie **zéro tour** (saisie manuelle, tapis sans tours) : on stocke une liste vide (pas de nouvel appel à chaque synchro), la comparaison est en mode dégradé avec `laps=[]`, la carte affiche « Aucun tour enregistré ». → tests en Tâches 4, 5 et 8.
- Tour de **distance nulle** (récup statique chronométrée) : allure `None`, pas de verdict d'allure, aucune division par zéro (normalisation et fusion). → tests en Tâches 2 et 4.
- **Garmin non connecté** au moment d'un rattachement manuel : la fabrique Garmin lève `GarminAuthRequired` ; le rattachement doit répondre 200 quand même. → test en Tâche 6.
- **Aucun snapshot** (zones inconnues) quand on ouvre le détail : comparaison affichée sans verdicts, pas d'erreur 500. → test en Tâche 6.
- **Rattachement déplacé** vers une autre séance : les tours restent liés à l'activité et la nouvelle séance affiche sa comparaison sans nouvel appel Garmin. → test en Tâche 6.

---

### Task 1: Numérotation à plat des étapes (partagée avec l'export)

**Files:**
- Modify: `coach/export/garmin_workout.py`
- Test: `tests/export/test_garmin_workout.py`

**Interfaces:**
- Produces:
  ```python
  class FlatStep(BaseModel):
      group: int             # rang (1-based) de l'élément de premier niveau dans spec.steps
      iteration: int | None  # 1..repeat pour une étape de répétition, None sinon
      position: int          # rang (0-based) de l'étape dans son groupe de répétition, 0 sinon
      step: StepSpec
      step_order: int        # stepOrder Garmin de l'étape exécutable

  def flat_steps(spec: SessionSpec) -> list[FlatStep]
  ```

- [ ] **Step 1: Write the failing tests**

```python
def test_flat_steps_unrolls_repeats_with_garmin_step_orders():
    spec = make_session(steps=[
        StepSpec(kind="warmup", duration_s=900),
        RepeatSpec(repeat=3, steps=[StepSpec(kind="active", distance_m=400, zone="Z5"),
                                    StepSpec(kind="recovery", distance_m=200)]),
        StepSpec(kind="cooldown", duration_s=600),
    ])
    flat = flat_steps(spec)
    assert [f.step_order for f in flat] == [1, 3, 4, 3, 4, 3, 4, 5]
    assert [(f.group, f.iteration, f.position) for f in flat][:3] == [(1, None, 0), (2, 1, 0), (2, 1, 1)]
    assert flat[-1].group == 3 and flat[-1].iteration is None

def test_flat_steps_orders_match_exported_workout():
    # même spec que ci-dessus : les stepOrder des ExecutableStepDTO du JSON exporté
    # (parcours en profondeur) sont exactement {f.step_order for f in flat_steps(spec)}
```

- [ ] **Step 2: Run** `uv run pytest tests/export/test_garmin_workout.py -v` — Expected: FAIL (`flat_steps` introuvable).

- [ ] **Step 3: Implement `flat_steps` in `coach/export/garmin_workout.py`**

Même compteur que `session_to_workout_json` (le groupe de répétition consomme un numéro avant ses enfants), puis dépliage des itérations : les enfants gardent le même `step_order` à chaque itération. Factoriser la numérotation dans une aide privée utilisée par les deux fonctions pour qu'elles ne puissent pas diverger.

- [ ] **Step 4: Run** `uv run pytest tests/export -v` — Expected: PASS (tests d'export existants inchangés).

- [ ] **Step 5: Commit** `feat(laps): numérotation à plat des étapes du workout`

---

### Task 2: Tours d'une activité dans le port Garmin

**Files:**
- Modify: `coach/garmin/port.py`, `coach/garmin/client.py`
- Create: `tests/fixtures/garmin/activity_splits.json`
- Test: `tests/garmin/test_client.py`, `tests/garmin/test_live.py`

**Interfaces:**
- Produces (dans `coach/garmin/port.py`) :
  ```python
  class LapSummary(BaseModel):
      index: int
      duration_s: float
      distance_m: float
      avg_hr: int | None = None
      max_hr: int | None = None
      avg_pace_s_km: float | None = None
      step_order: int | None = None  # stepOrder Garmin de l'étape exécutée, None hors workout
      raw: dict = {}
  ```
  `GarminPort.activity_laps(self, garmin_id: int) -> list[LapSummary]` ;
  `FakeGarminClient(..., laps: dict[int, list[LapSummary]] | None = None)` dont `activity_laps` appelle `self._check("activity_laps")` puis renvoie `list(self._laps.get(garmin_id, []))`.

- [ ] **Step 1: Capture réelle (prérequis, manuel)**

Ajouter à `tests/garmin/test_live.py` un test `@pytest.mark.live` qui appelle `api.get_activity_splits(id)` sur deux activités de l'utilisateur (une courue avec un workout CoachCloclo, une sans) et écrit la réponse dans `tests/fixtures/garmin/activity_splits.json` sous la forme `{"workout": {...}, "free": {...}}` (données personnelles minimales : retirer coordonnées GPS et identifiants autres que `activityId`). Le faire lancer par l'utilisateur :

```bash
uv run pytest tests/garmin/test_live.py -m live -k splits -v
```

Relever dans la fixture : le nom du champ d'étape sur chaque `lapDTO` (attendu `wktStepIndex`) et sa base. **Si ce champ n'est ni le `stepOrder` Garmin ni ce même numéro décalé de 1** (par exemple un index d'étape dépliée par itération), arrêter et réviser l'algorithme de la Tâche 4 avec l'utilisateur avant de continuer.

- [ ] **Step 2: Write the failing tests** (`tests/garmin/test_client.py`, sur la fixture, avec un faux `api` comme les tests existants)

```python
def test_activity_laps_workout_maps_step_orders():
    laps = client_with(splits=FIXTURE["workout"]).activity_laps(1)
    assert [l.index for l in laps] == list(range(len(laps)))
    assert all(l.step_order is not None for l in laps)
    assert laps[0].avg_pace_s_km == pytest.approx(1000 / FIXTURE["workout"]["lapDTOs"][0]["averageSpeed"])

def test_activity_laps_free_run_has_no_step_order():
    assert all(l.step_order is None for l in client_with(splits=FIXTURE["free"]).activity_laps(2))

def test_activity_laps_zero_distance_has_no_pace():
    laps = client_with(splits={"lapDTOs": [{"duration": 60, "distance": 0, "averageSpeed": 0}]}).activity_laps(3)
    assert laps[0].distance_m == 0 and laps[0].avg_pace_s_km is None

def test_activity_laps_skips_malformed_laps():
    splits = {"lapDTOs": [{"duration": "x"}, None, {"duration": 120, "distance": 400, "averageSpeed": 3.5}]}
    assert len(client_with(splits=splits).activity_laps(4)) == 1
```

- [ ] **Step 3: Run** `uv run pytest tests/garmin/test_client.py -v` — Expected: FAIL.

- [ ] **Step 4: Implement**

`GarminClient.activity_laps` : `self._call(self._api.get_activity_splits, str(garmin_id))`, puis normalisation de `lapDTOs` (liste absente ou non-liste → `[]`). Un tour sans `duration` numérique est ignoré ; `distance` absente vaut 0. L'allure vient de `averageSpeed` en m/s : `1000 / speed` si `speed > 0`, sinon `None` — ne **pas** réutiliser `_pace_s_km` (son facteur ×10 et sa garde de plausibilité concernent le seuil lactique). `step_order` depuis le champ relevé au Step 1, converti en `stepOrder` Garmin. `index` = rang du tour conservé. Ajouter `activity_laps` au `Protocol` et au `FakeGarminClient`.

- [ ] **Step 5: Run** `uv run pytest tests/garmin -v` — Expected: PASS.

- [ ] **Step 6: Commit** `feat(laps): lecture des tours d'une activité Garmin`

---

### Task 3: Stockage des tours

**Files:**
- Modify: `coach/plan/models.py`, `coach/plan/repo.py`
- Test: `tests/plan/test_repo.py`

**Interfaces:**
- Consumes: `LapSummary` (Tâche 2).
- Produces:
  ```python
  class ActivityLaps(SQLModel, table=True):
      id: int | None = Field(default=None, primary_key=True)
      activity_id: int = Field(unique=True, index=True)
      laps_json: str
      fetched_at: dt.datetime = Field(default_factory=_now)
  ```
  `Repo.laps(activity_id: int) -> list[LapSummary] | None` (None = jamais récupérés) ;
  `Repo.save_laps(activity_id: int, laps: list[LapSummary]) -> None` (remplace une ligne existante) ;
  `Repo.activity_of_session(session_id: int) -> Activity | None`.
  `laps_json` exclut `raw` (`model_dump(exclude={"raw"})`).

- [ ] **Step 1: Write the failing tests**

```python
def test_laps_absent_then_saved_then_replaced(repo):
    assert repo.laps(1) is None
    repo.save_laps(1, [LapSummary(index=0, duration_s=60, distance_m=200, raw={"x": 1})])
    assert repo.laps(1)[0].distance_m == 200 and repo.laps(1)[0].raw == {}
    repo.save_laps(1, [])
    assert repo.laps(1) == []

def test_activity_of_session(repo):
    a = repo.add(make_activity(session_id=7))
    assert repo.activity_of_session(7).id == a.id and repo.activity_of_session(8) is None
```

- [ ] **Step 2: Run** `uv run pytest tests/plan/test_repo.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** the table and the three methods (style des méthodes voisines de `Repo`).
- [ ] **Step 4: Run** `uv run pytest tests/plan -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(laps): table ActivityLaps`

---

### Task 4: Rapprochement et verdict

**Files:**
- Create: `coach/analysis/laps.py`
- Test: `tests/analysis/test_laps.py`

**Interfaces:**
- Consumes: `flat_steps`, `FlatStep` (Tâche 1) ; `LapSummary` (Tâche 2) ; `Zones`.
- Produces: `StepResult`, `StepComparison` exactement comme en section 4.5 du spec, avec en plus `position: int` dans `StepResult` (repris de `FlatStep`, utile au prompt et au front), et
  `compare_session(spec: SessionSpec, laps: list[LapSummary], zones: Zones | None) -> StepComparison`.
  `laps` du résultat : toujours les tours reçus, `raw` vidé.

- [ ] **Step 1: Write the failing tests** — fabrique locale `lap(i, order, dur, dist, hr=None)` (allure = `dur / (dist / 1000)` si `dist`), zones `ZONES` avec `pace["VMA"] == (220, 235)` et `hr["Z5"] == (171, 190)` ; séance `6×(actif 400 m VMA, récup 200 m)` encadrée d'un échauffement et d'un retour au calme (orders 1, 3, 4, 5) :

```python
def test_one_lap_per_step_matches_all():           # 14 tours → 14 StepResult done, followed_workout True
def test_manual_lap_inside_step_is_merged():        # deux tours order 1 (300 s/1000 m + 300 s/1000 m) → 600 s, 2000 m, allure 300
def test_merged_hr_is_duration_weighted():          # 100 s à 150 + 300 s à 170 → 165
def test_skipped_step_is_not_done():                # voir le cas décrit sous ce bloc
def test_stopped_early_leaves_remaining_not_done(): # tours pour 1, 3, 4 seulement → 11 étapes done False
def test_going_back_falls_back_to_degraded():       # orders 1, 5, 3 → followed_workout False, steps == []
def test_lap_without_step_order_is_degraded():      # un seul tour à None suffit
def test_unknown_step_order_is_degraded():          # order 9 absent du plan
def test_no_laps_is_degraded_with_empty_list():     # laps == [] → followed_workout False, laps == []
def test_single_step_repeat_laps_are_iterations():  # RepeatSpec(repeat=3, [actif 60 s]) + 3 tours order 2 → 3 itérations done
def test_pace_verdicts_at_bounds():                 # 220 → in, 235 → in, 219 → fast, 236 → slow
def test_hr_verdicts():                             # cible hr Z5 : 170 → hr_low, 191 → hr_high, 171 → in
def test_no_verdict_without_zone_or_data():         # étape sans zone ; tour sans FC sur cible hr ; zones None ; zones.pace None
def test_zero_distance_lap_has_no_pace_verdict():   # récup 60 s, 0 m, zone récup → verdict None, pas d'exception
def test_planned_volume_is_reported():              # planned_distance_m == 400 et distance_m == 412
```

Pour l'étape sautée : tours d'orders `1, 3, 3, 4` sur la séance ci-dessus, où le deuxième `3` arrive alors que l'étape attendue est la récup (order 4) de l'itération 1 → il démarre l'actif de l'itération 2 et la récup de l'itération 1 est `done=False`.

- [ ] **Step 2: Run** `uv run pytest tests/analysis/test_laps.py -v` — Expected: FAIL (module absent).

- [ ] **Step 3: Implement `compare_session`**

Rapprochement (section 4.2 du spec) :

```python
plan = flat_steps(spec)
if not laps or any(l.step_order is None for l in laps) or {l.step_order for l in laps} - {f.step_order for f in plan}:
    return degraded
groups: list[list[LapSummary]] = [[] for _ in plan]
i = -1
for lap in laps:
    nxt = plan[i + 1].step_order if i + 1 < len(plan) else None
    if i >= 0 and plan[i].step_order == lap.step_order and nxt != lap.step_order:
        groups[i].append(lap)          # appui manuel dans la même étape : fusion
        continue
    j = next((k for k in range(i + 1, len(plan)) if plan[k].step_order == lap.step_order), None)
    if j is None:
        return degraded                # retour en arrière
    i = j
    groups[i].append(lap)
```

Fusion d'un groupe : durées et distances additionnées ; allure `duration / (distance / 1000)` si `distance > 0` sinon `None` ; FC moyenne pondérée par la durée sur les tours qui en ont, arrondie (`None` si aucun). Verdict (section 4.4) : zone d'allure → `target_low, target_high = zones.pace[zone]` (rapide, lente) ; zone FC → `zones.hr[zone]`. `target_kind` = `spec.target_kind`.

- [ ] **Step 4: Run** `uv run pytest tests/analysis -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(laps): rapprochement des tours et des étapes`

---

### Task 5: Récupération des tours à la synchro

**Files:**
- Create: `coach/services/laps.py`
- Modify: `coach/services/sync.py`
- Test: `tests/services/test_laps.py`, `tests/services/test_sync.py`

**Interfaces:**
- Consumes: `GarminPort.activity_laps`, `Repo.laps/save_laps/activity_of_session`, `compare_session`.
- Produces (dans `coach/services/laps.py`) :
  - `fetch_laps(repo: Repo, garmin: GarminPort, activity: Activity) -> bool` — lit et enregistre les tours ; `False` (journalisé, rien d'enregistré) sur `GarminUnavailable | GarminRateLimited | GarminAuthRequired`.
  - `fetch_missing_laps(repo: Repo, garmin: GarminPort) -> int` — pour chaque activité avec `session_id` non nul et `repo.laps(a.id) is None` ; retourne le nombre enregistré.
  - `session_comparison(repo: Repo, session: Session, zones: Zones | None) -> StepComparison | Literal["no_activity", "no_laps"]`.
  - `latest_zones(repo: Repo) -> Zones | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/services/test_laps.py
def test_fetch_missing_laps_only_for_matched_activities(repo):   # 1 rattachée + 1 libre → 1 appel, 1 ligne
def test_fetch_missing_laps_skips_already_fetched(repo):         # liste vide déjà stockée → aucun appel
def test_fetch_laps_error_is_swallowed(repo):                    # fail_on={"activity_laps"} → False, repo.laps is None
def test_session_comparison_reasons(repo):                       # "no_activity", puis "no_laps", puis StepComparison

# tests/services/test_sync.py
def test_sync_fetches_laps_of_matched_activities(repo, coach_home):   # FakeGarminClient(laps={1: [...]}) → repo.laps(activity.id) non None
def test_sync_survives_laps_error_and_retries_next_time(repo, coach_home):
    # 1re synchro avec fail_on={"activity_laps"} → SyncResult normal, laps None ;
    # 2e synchro sans erreur → laps enregistrés
```

- [ ] **Step 2: Run** `uv run pytest tests/services/test_laps.py tests/services/test_sync.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `coach/services/laps.py`, puis dans `sync()` appeler `fetch_missing_laps(repo, garmin)` après la transaction de rattachement (si `goal is not None`) et avant `_propose`.
- [ ] **Step 4: Run** `uv run pytest tests/services -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(laps): récupération des tours à la synchro`

---

### Task 6: API — comparaison et rattachement manuel

**Files:**
- Modify: `coach/api/app.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: `fetch_laps`, `session_comparison`, `latest_zones` (Tâche 5).
- Produces: `GET /api/sessions/{session_id}/comparison` →
  - 404 `not_found` si la séance n'existe pas ;
  - `{"available": false, "reason": "no_activity" | "no_laps"}` ;
  - `{"available": true, **comparison.model_dump()}` (tours sans `raw`).

- [ ] **Step 1: Write the failing tests**

```python
def test_comparison_reasons_and_payload(make_client, repo, fake_garmin):
    # séance sans activité → no_activity ; activité rattachée sans tours → no_laps ;
    # tours stockés + snapshot → available True, followed_workout True, steps[0]["verdict"] renseigné
def test_comparison_unknown_session_is_404(make_client):
def test_comparison_without_snapshot_has_no_verdicts(make_client, repo):
def test_manual_match_fetches_laps(make_client, repo, fake_garmin):        # fake_garmin._laps rempli → repo.laps non None
def test_manual_match_ok_when_garmin_logged_out(make_client, repo):        # make_client(garmin="auth") → 200, laps None
def test_manual_match_ok_when_laps_fail(make_client, repo, fake_garmin):   # fail_on={"activity_laps"} → 200
def test_rematched_activity_keeps_its_laps(make_client, repo, fake_garmin):
    # tours déjà stockés, rattachement vers une autre séance → aucun appel activity_laps, comparaison disponible
```

- [ ] **Step 2: Run** `uv run pytest tests/api/test_app.py -k "comparison or manual_match or rematched" -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

Endpoint `GET /sessions/{session_id}/comparison` (même routeur `api` que `/sessions/{id}/export`). Dans `post_match`, après la transaction et seulement si `body.session_id` n'est pas nul et `repo.laps(activity.id) is None` : obtenir le client par `app.state.garmin_factory()` dans un `try` qui attrape `GarminAuthRequired` (pas de `GarminDep`, qui ferait répondre 401), puis `fetch_laps(...)`. La réponse reste `{"status": "ok"}`.

- [ ] **Step 4: Run** `uv run pytest tests/api -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(laps): comparaison prévu / réalisé dans l'API`

---

### Task 7: Détail par étape dans le prompt d'ajustement

**Files:**
- Modify: `coach/llm/prompts.py`, `coach/services/sync.py`
- Test: `tests/llm/test_prompts.py`, `tests/services/test_sync.py`

**Interfaces:**
- Consumes: `StepComparison` (Tâche 4), `session_comparison` (Tâche 5).
- Produces: `build_adjustment_prompt(..., history, comparisons: dict[int, StepComparison] | None = None)` — clé = `Session.id` ; une séance absente du dictionnaire garde la ligne actuelle.

- [ ] **Step 1: Write the failing tests**

```python
def test_adjustment_prompt_details_workout_steps():
    # comparaison 6×400 VMA : la ligne de répétition est exactement
    # "    · 6× actif 400 m VMA [3:40–3:55/km] : 3:48, 3:50, 3:52, 3:58 (trop lent), 4:01 (trop lent), non réalisée"
    # et l'échauffement "    · échauffement 15 min : 15:02, 5:31/km, 138 bpm"
def test_adjustment_prompt_hr_target_lists_bpm():          # cible FC : valeurs "172 bpm", verdict "(FC trop haute)"
def test_adjustment_prompt_degraded_caps_at_30_laps():     # 35 tours → 30 lignes de tour + "… 5 tours de plus"
def test_adjustment_prompt_without_comparison_unchanged(): # comparisons=None → identique au prompt actuel
def test_adjustment_prompt_mentions_step_detail_rule():    # la consigne du spec section 7 est présente quand comparisons non vide

# tests/services/test_sync.py
def test_proposal_prompt_contains_step_detail(repo, coach_home):  # FakeLLMProvider capture le prompt : contient "· échauffement"
```

- [ ] **Step 2: Run** `uv run pytest tests/llm/test_prompts.py tests/services/test_sync.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

Rendu (copie fixée par le spec, section 7), lignes indentées de 4 espaces et préfixées `· ` sous la ligne `_done_line` :
- libellés : `warmup` « échauffement », `active` « actif », `recovery` « récup », `cooldown` « retour au calme » ; volume `400 m` / `15 min` (ou `90 s` sous la minute) ; zone et plage `VMA [3:40–3:55/km]` ou `Z5 [171–190 bpm]` si la zone existe ;
- étape simple : `{libellé} {volume}[ {zone} [{plage}]] : {durée m:ss}, {allure}/km, {FC} bpm[ ({verdict})]` (éléments manquants omis) ou `: non réalisée` ;
- répétition : une ligne par `position` du groupe : `{repeat}× {libellé} {volume}[ zone] : ` + valeurs des itérations séparées par `, ` — l'allure (`m:ss`) si `target_kind == "pace"`, sinon `{FC} bpm` — chacune suivie de ` ({verdict})` si le verdict n'est pas `in`, ou `non réalisée` ;
- verdicts : `fast` « trop vite », `slow` « trop lent », `hr_high` « FC trop haute », `hr_low` « FC trop basse » ;
- dégradé : `    séance non suivie sur la montre, tours :` puis `    · tour {n} : {distance} m, {durée}, {allure}/km, {FC} bpm` (n à partir de 1), 30 au plus, puis `    … {k} tours de plus` ;
- consigne ajoutée au bloc « Séances réalisées » : « Le détail par étape compare le réalisé aux zones cibles ; appuie ton analyse dessus quand il est présent. »

Dans `_propose`, construire `comparisons` avec `session_comparison(repo, s, zones)` pour chaque séance de `done`, en ne gardant que les résultats `StepComparison`.

- [ ] **Step 4: Run** `uv run pytest -v` — Expected: PASS (toute la suite Python).
- [ ] **Step 5: Commit** `feat(laps): détail par étape transmis à Claude`

---

### Task 8: Bloc « Prévu / réalisé » dans la carte de séance

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/components/SessionCard.svelte`
- Create: `web/src/lib/comparison.ts`, `web/src/lib/comparison.test.ts`
- Test: `web/src/components/SessionCard.test.ts`

**Interfaces:**
- Consumes: `GET /api/sessions/{id}/comparison` (Tâche 6).
- Produces (dans `api.ts`) : types `Lap`, `StepResult`, `Comparison` (`{ available: false; reason: "no_activity" | "no_laps" } | ({ available: true } & StepComparison)`) et `api.comparison(sessionId: number) => get<Comparison>(`/sessions/${sessionId}/comparison`)`.
  Dans `comparison.ts` :
  - `stepLabel(s: StepResult): string` → `"3.2 · Actif 400 m"` (`{group}.{iteration}` pour une répétition, `{group}` sinon) ;
  - `targetLabel(s: StepResult, kind: "pace" | "hr"): string | null` → `"VMA 3:40–3:55/km"` ou `"Z5 171–190 bpm"` ;
  - `doneLabel(s: StepResult): string` → `"412 m · 3:48/km · 172 bpm"` (éléments manquants omis) ;
  - `VERDICT_LABEL: Record<Verdict, string>` (« dans la cible », « trop vite », « trop lent », « FC trop haute », « FC trop basse ») ;
  - `repeatSummary(steps: StepResult[], group: number): string | null` → `"5/6 fractions dans la cible"` (étapes `active` du groupe avec verdict `in` sur étapes `active` du groupe ; `null` hors répétition).

- [ ] **Step 1: Write the failing tests**

```ts
// comparison.test.ts
test("stepLabel numbers repeat iterations", () => expect(stepLabel(rep(3, 2, "active", 400))).toBe("3.2 · Actif 400 m"));
test("targetLabel formats pace and hr ranges", ...);      // "VMA 3:40–3:55/km", "Z5 171–190 bpm", null sans zone
test("doneLabel omits missing values", ...);               // pas de FC → "412 m · 3:48/km"
test("repeatSummary counts active steps in target", ...);  // "5/6 fractions dans la cible"

// SessionCard.test.ts (stubApi étendu : /api/sessions/7/comparison renvoie `comparison`)
test("Prévu / réalisé loads on first expand and shows verdicts", ...);   // aucun appel avant le clic ; "dans la cible" visible
test("degraded comparison lists raw laps", ...);                         // "Séance non suivie sur la montre : tours bruts"
test("no laps yet shows the next-sync hint", ...);                       // "Détail par étape disponible après la prochaine synchro"
test("zero laps shows the empty message", ...);                          // followed_workout false, laps [] → "Aucun tour enregistré"
test("block hidden when not done or readonly", ...);
```

- [ ] **Step 2: Run** `cd web && npm test -- --run comparison SessionCard` — Expected: FAIL.

- [ ] **Step 3: Implement**

Dans `SessionCard.svelte`, sous la ligne « Activité : … », si `!readonly && session.status === "done" && matched` : un `<details>` « Prévu / réalisé » dont l'ouverture (`ontoggle`) déclenche `api.comparison(session.id)` une seule fois (état `comparison`, erreurs vers `onerror`). Rendu selon la section 6 du spec : liste compacte d'étapes (synthèse `repeatSummary` en tête de chaque groupe de répétition, étapes non réalisées grisées, pastille de verdict verte/orange/grise via les variables CSS existantes), liste de tours en mode dégradé, messages `no_laps` et zéro tour. Réutiliser `fmtPace` et `fmtClock` de `lib/stats/format.ts`.

- [ ] **Step 4: Run** `cd web && npm test -- --run` — Expected: PASS (toute la suite front).
- [ ] **Step 5: Vérification visuelle** — lancer l'appli (skill `run`), ouvrir une séance réalisée, contrôler le bloc en largeur téléphone (375 px) et en thème sombre.
- [ ] **Step 6: Commit** `feat(laps): prévu / réalisé dans la carte de séance`
