# Jour J — guide de course : plan de mise en œuvre

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le tableau par km du Jour J par un guide de course (phases, passages, eau et nutrition, préparation, conseils Claude), lisible aussi sur mobile.

**Architecture:** Un module pur `coach/analysis/race_guide.py` tire du `RacePlan` existant un `RaceGuide` (phases, passages, prises, matin, préparation). Le service ajoute le guide et les conseils du coach à `RaceView`, et enregistre une copie JSON de la vue entière dans `racestrategy.view_json`. La PWA lit cette copie et l'affiche avec le même composant `Race.svelte`, en lecture seule.

**Tech Stack:** Python 3 / Pydantic / SQLModel / FastAPI, Svelte 5 + TypeScript, Vitest, libsql (PWA).

**Spec:** `docs/superpowers/specs/2026-11-26-jour-j-guide-design.md`

## Global Constraints

- Textes en français correct, tutoiement, phrases courtes ; aucune valeur exprimée au kilo de poids.
- Tranches de distance : `court` ≤ 12 km, `semi` ≤ 25 km, `marathon` ≤ 45 km, `ultra` au-delà.
- Nutrition recommandée par durée prévue : < 1 h 15 → 0 g/h, eau facultative ; ≤ 2 h 30 → 30–60 g/h ; > 2 h 30 → 60–90 g/h.
- La page s'affiche entièrement sans Claude ; Claude ne prescrit jamais une allure, une durée ou une heure absente de son prompt.
- La PWA n'écrit jamais en base ; un seul écran `Race.svelte` pour l'ordinateur et le mobile.
- Plus de tableau par km pour une route sans GPX.
- Tests Python : `uv run pytest` ; tests web : `cd web; npm test`. Chaque tâche finit avec les deux suites vertes sur les fichiers touchés.
- Commits en français, style du dépôt (`feat:`, `feat(web):`, `test:`).

## Review Focus

- **Sans temps de référence** (ni temps visé, ni prédiction Garmin) : le guide s'affiche avec conseils et préparation, sans allure, passage ni heure ; l'envoi montre reste refusé. → test Task 3 `test_guide_without_reference`.
- **Départ tôt ou ultra qui passe minuit** : les heures du matin et des passages restent au format `HH:MM` modulo 24 h (départ 04:00 → petit-déj 01:00). → test Task 3 `test_morning_wraps_midnight`.
- **Distances non entières** (21,0975 ; 42,195) : le dernier passage est l'arrivée exacte, aucun passage en double (5 km d'un 5 km), aucune phase au-delà de la distance. → tests Task 2 `test_splits_marathon`, `test_splits_5k_no_duplicate`.
- **Copie mobile absente ou illisible** (stratégie jamais ouverte, JSON d'un ancien format) : message « Ouvre le Jour J sur l'ordinateur pour préparer ce guide », jamais d'écran cassé. → test Task 8 `shows the desktop hint when the snapshot is missing or unreadable`.
- **Réponse de Claude citant un chiffre réel de l'historique** : acceptée ; une allure inventée : rejetée puis relancée. → tests Task 6 `test_advice_accepts_history_figures`, `test_advice_rejects_invented_pace`.

---

### Task 1: Départ prudent et final dans le plan route

**Files:**
- Modify: `coach/analysis/race_plan.py` (`_Timing`, `build_race_plan`)
- Test: `tests/analysis/test_race_plan.py`

**Interfaces:**
- Produces: `pacing_weight(start_km: float, end_km: float, distance_km: float) -> float` (multiplicateur moyen d'effort du tronçon) ; `_Timing(spans, run_s, stations, weights: list[float] | None = None)`.

Valeurs : départ = 12 % premiers de la distance, poids **1,02** ; final = 12 % derniers, poids **0,99** ; 1,0 ailleurs. Le temps de segment est `run_s × eq_km × poids / Σ(eq_km × poids)` : le total reste exact. Appliqué seulement si `trail` est faux.

- [ ] **Step 1: Tests**

```python
def test_road_start_slower_finish_faster():
    plan = build_race_plan(distance_km=10, trail=False, profile=None, basis=RaceBasis(**B, pred_5k_s=None,
        pred_10k_s=None, pred_half_s=None, pred_marathon_s=None), settings=RaceSettings(), today=date(2026, 11, 1),
        target_time_s=3000)
    paces = [s.pace_s_km for s in plan.segments]
    assert paces[0] > paces[5] > paces[-1]
    assert plan.segments[-1].elapsed_s == 3000
    assert 4 <= paces[0] - 300 <= 8  # ≈ +6 s/km au départ

def test_trail_pacing_unchanged():  # même profil plat, trail=True : toutes les allures égales
    ...
def test_pacing_weight_partial_overlap():
    assert pacing_weight(0, 1.2, 10) == pytest.approx(1.02)
    assert pacing_weight(1.0, 1.4, 10) == pytest.approx((0.2 * 1.02 + 0.2) / 0.4)
```

- [ ] **Step 2:** `uv run pytest tests/analysis/test_race_plan.py -v` → les 3 nouveaux tests échouent.
- [ ] **Step 3:** Implémenter `pacing_weight` et le paramètre `weights` de `_Timing` ; `build_race_plan` passe les poids pour la route. Mettre à jour les tests existants qui supposaient des allures égales sur route.
- [ ] **Step 4:** `uv run pytest tests/analysis tests/services tests/export -v` → PASS.
- [ ] **Step 5:** Commit `feat: départ prudent et final plus rapide dans le plan route`.

### Task 2: Guide — tranches, phases et passages

**Files:**
- Create: `coach/analysis/race_guide.py`
- Test: `tests/analysis/test_race_guide.py`

**Interfaces:**
- Consumes: `RacePlan`, `RaceSettings`, `RaceBasis`, `race_hr_zone`, `_clock` (rendre public sous le nom `clock_at`) de `race_plan.py`.
- Produces:
```python
DistanceBand = Literal["court", "semi", "marathon", "ultra"]
PhaseName = Literal["Départ", "Installation", "Cœur de course", "Final"]
def distance_band(distance_km: float) -> DistanceBand
class Phase(BaseModel):
    name: PhaseName; start_km: float; end_km: float
    pace_low_s_km: int | None; pace_high_s_km: int | None     # route
    hr_zone: HrZoneName | None; hr_low: int | None; hr_high: int | None  # trail
    elapsed_end_s: int | None; clock_end: str | None
    terrain: list[str]   # « Montée km 18–23, +600 m »
    advice: str          # rempli en Task 3 (chaîne vide ici)
class Split(BaseModel): km: float; label: str; elapsed_s: int; clock: str
def build_phases(plan: RacePlan, trail: bool, basis: RaceBasis, start_time: str) -> list[Phase]
def build_splits(plan: RacePlan, start_time: str) -> list[Split]
```

Phases **route** en part de la distance : `court` → Départ 0–15 %, Cœur 15–85 %, Final 85–100 % ; sinon Départ 0–10 %, Installation 10–40 %, Cœur 40–85 %, Final 85–100 %. Bornes arrondies au 0,5 km, dernière borne = distance exacte. Allure de phase = temps des segments couverts (interpolé) / longueur, fourchette ±5 s/km.

Phases **trail** sur les mêmes parts appliquées au **temps de course** de référence ; la borne km est retrouvée par interpolation dans les segments, puis calée sur un ravito si l'écart de temps est < 10 % de la durée de la phase. Zone FC = `race_hr_zone(reference)`, une zone plus bas pour le Départ ; bornes bpm depuis `basis.hr`.

`terrain` : montées des segments couverts avec `d_plus_m` ≥ 20 m (route) ou ≥ 100 m (trail), et en trail les descentes ≥ 150 m.

Passages (route seulement, `[]` en trail) : tous les 5 km jusqu'à `semi` ; `marathon` : 5, 10, semi (21,1), 25, 30, 35 ; `ultra` : tous les 10 km ; toujours l'arrivée (`label` « Arrivée »), sans doublon. Sans `reference_time_s` : `build_splits` renvoie `[]` et les phases ont allures, FC et heures à `None`.

- [ ] **Step 1: Tests** — `test_distance_band` (5 → court, 12 → court, 21.0975 → semi, 42.195 → marathon, 80 → ultra) ; `test_road_phases_10k` (3 phases, bornes 0/1.5/8.5/10, allure Départ > allure Cœur) ; `test_road_phases_marathon` (4 phases, dernière `end_km == 42.195`) ; `test_splits_marathon` (labels `5 km,10 km,Semi,25 km,30 km,35 km,Arrivée`, dernier `km == 42.195`) ; `test_splits_5k_no_duplicate` (un seul passage, « Arrivée ») ; `test_trail_phases_time_based_snap_to_aid` (profil montée puis descente, ravito proche d'une borne → `end_km == station.km`) ; `test_phase_terrain_lists_climbs`.
- [ ] **Step 2:** `uv run pytest tests/analysis/test_race_guide.py -v` → FAIL (module absent).
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** Même commande → PASS.
- [ ] **Step 5:** Commit `feat: phases et passages du guide de course`.

### Task 3: Guide — nutrition, matin, préparation et conseils

**Files:**
- Modify: `coach/analysis/race_plan.py` (`RaceSettings`, `_nutrition`, `recommended_intake`)
- Modify: `coach/analysis/race_guide.py`
- Create: `coach/analysis/race_guide_texts.py` (textes seulement)
- Test: `tests/analysis/test_race_guide.py`, `tests/analysis/test_race_plan.py`

**Interfaces:**
- Produces:
```python
# race_plan.py
class RaceSettings: carbs_g_h: int | None = None; water_ml_h: int | None = None   # mêmes bornes si renseignés
def recommended_intake(duration_s: int) -> tuple[int, int]   # (g/h, ml/h) : <4500 s → (0, 0) ; ≤9000 → (45, 400) ; sinon (75, 500)
# race_guide.py
class Intake(BaseModel): km: float; clock: str | None; what: str
class GuideNutrition(BaseModel): carbs_g_h: int; water_ml_h: int; recommended: bool; principle: str; intakes: list[Intake]
class MorningStep(BaseModel): clock: str; label: str
class PrepBlock(BaseModel): title: Literal["La semaine d'avant", "La veille", "Le matin"]; items: list[str]
class RaceGuide(BaseModel):
    band: DistanceBand; reference_time_s: int | None; avg_pace_s_km: int | None
    phases: list[Phase]; splits: list[Split]; nutrition: GuideNutrition
    morning: list[MorningStep]; preparation: list[PrepBlock]
def build_race_guide(*, plan: RacePlan, trail: bool, settings: RaceSettings, basis: RaceBasis) -> RaceGuide
```

- `_nutrition` utilise `recommended_intake(reference)` quand un champ est `None`.
- Prises route : gel de **25 g** ; premier à 40 min, puis tous les `25 / carbs_g_h` h ; aucun dans les 15 dernières minutes ; aucun si `carbs_g_h == 0`. `what` = « Gel (25 g) + quelques gorgées ». En trail, `intakes = []` (le tableau par tronçon couvre l'eau et les glucides).
- Matin (heures via `clock_at`, modulo 24 h) : petit-déjeuner départ − 3 h (`court` : − 2 h) ; arrivée sur place − 60 min ; échauffement `court` − 30 min (« 15–20 min de footing + 3 accélérations »), `semi` − 25 min (« 10 min de footing »), au-delà − 15 min (« 5 min de mobilité ») ; départ.
- `race_guide_texts.py` : `PHASE_ADVICE[(trail, band, phase)]`, `PREPARATION[(trail, band)] -> dict[title, list[str]]`, `PRINCIPLE[(trail, palier de durée)]`. Contenu : affûtage, sommeil, glucides les 2 jours avant (`marathon`, `ultra`), rien de nouveau le jour J, sac et dossard la veille, accès au départ ; en trail, marcher tôt dans les montées, manger avant d'avoir faim, garder du jus pour les descentes.

- [ ] **Step 1: Tests** — `test_recommended_intake_tiers` (4499 → (0,0), 4500 → (45,400), 9000 → (45,400), 9001 → (75,500)) ; `test_nutrition_uses_recommended_when_none` (trail 5 h, champs `None` → tronçons à 75 g/h) ; `test_road_gels_half` (semi 1:45, 45 g/h → gels à 40 min puis toutes les 33 min, aucun après 1:30) ; `test_no_gels_10k` ; `test_morning_wraps_midnight` (départ 04:00 semi → petit-déj « 01:00 ») ; `test_guide_without_reference` (plan sans référence : `splits == []`, allures `None`, `preparation` non vide, `morning` toujours daté depuis l'heure de départ) ; `test_every_phase_has_advice` (toutes tranches × route/trail : `advice` non vide).
- [ ] **Step 2:** `uv run pytest tests/analysis -v` → FAIL.
- [ ] **Step 3:** Implémenter ; écrire les textes.
- [ ] **Step 4:** `uv run pytest tests/analysis tests/services -v` → PASS.
- [ ] **Step 5:** Commit `feat: nutrition, matin et préparation du guide de course`.

### Task 4: Stockage, migration et copie de la vue

**Files:**
- Modify: `coach/plan/models.py` (`RaceStrategy`), `coach/plan/repo.py` (`SCHEMA_VERSION = 5`, `_MIGRATED`, `_migrate`)
- Modify: `coach/services/race_strategy.py` (`RaceView`, `_view`, `_get_or_create`)
- Test: `tests/plan/` (test de migration existant à étendre), `tests/services/test_race_strategy.py`

**Interfaces:**
- Produces: colonnes `RaceStrategy.view_json: str | None`, `view_updated_at: datetime | None`, `advice_json: str | None`, `advice_at: datetime | None`, `advice_hash: str | None` ; `RaceView.guide: RaceGuide`, `RaceView.advice: CoachAdvice | None` (type défini en Task 6, ici `None`), `RaceView.advice_at`, `RaceView.advice_stale: bool`, `RaceView.updated_at` ; `refresh_snapshot(repo: Repo, goal: Goal, today: date) -> None` (recalcule et écrit `view_json` si la stratégie existe et que le JSON a changé ; sans stratégie, ne fait rien).

- Migration : `racestrategy` rejoint `_MIGRATED` ; ajout des 5 colonnes ; pour chaque stratégie d'un objectif `route`, `carbs_g_h` et `water_ml_h` passent à `null` dans `settings_json`. Idempotente.
- `_get_or_create` : nouvelle stratégie avec `carbs_g_h = water_ml_h = None`.
- `_view` construit la vue puis appelle l'écriture de copie ; une lecture sans changement n'écrit rien.

- [ ] **Step 1: Tests** — migration d'une base v4 : colonnes présentes, route remise à `null`, trail inchangé, seconde exécution sans effet ; `test_view_has_guide` ; `test_snapshot_written_once` (deux lectures → `view_updated_at` inchangé à la seconde) ; `test_refresh_snapshot_without_strategy_is_noop`.
- [ ] **Step 2:** `uv run pytest tests/plan tests/services/test_race_strategy.py -v` → FAIL.
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** `uv run pytest -q` → PASS (régénérer `tests/mobile_fixtures` si leurs tests l'exigent : `uv run python -m tests.mobile_fixtures`).
- [ ] **Step 5:** Commit `feat: copie de la vue Jour J en base pour le mobile`.

### Task 5: Rafraîchir la copie partout où la course change ; montre par phases

**Files:**
- Modify: `coach/services/goals.py` (`update_goal`, après écriture), `coach/services/plans.py` (après `estimated_times`), `coach/services/garmin_export.py` (`apply_proposal`, après `_apply_estimates`)
- Modify: `coach/export/garmin_workout.py`, `coach/services/race_strategy.py` (`export_race`)
- Test: `tests/services/test_goals.py`, `test_plans.py`, `test_garmin_export.py`, `tests/export/test_garmin_workout.py`, `test_race_strategy.py`

**Interfaces:**
- Consumes: `refresh_snapshot` (Task 4), `RaceGuide.phases` (Task 2).
- Produces: `race_phases_to_workout_json(guide: RaceGuide, *, name: str) -> dict` : une étape par phase, à la distance (`(end_km − start_km) × 1000`), cible allure `pace_low/high`, description « {nom} – {allure basse}–{haute} /km ».

`export_race` : route sans profil → `race_phases_to_workout_json` ; sinon inchangé. `refresh_snapshot` est appelé hors transaction, et une erreur y est journalisée sans faire échouer l'action appelante.

- [ ] **Step 1: Tests** — modifier le temps visé via `update_goal` → `view_json` reflète le nouveau temps ; estimation Claude acceptée (génération, proposition) → idem ; `test_phases_workout_10k` (3 étapes, distances 1500/7000/1500) ; `test_export_road_without_gpx_uses_phases`.
- [ ] **Step 2:** `uv run pytest tests/services tests/export -v` → FAIL.
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** Même commande → PASS.
- [ ] **Step 5:** Commit `feat: copie du Jour J à jour et envoi montre par phases`.

### Task 6: Conseils du coach (Claude)

**Files:**
- Modify: `coach/llm/schemas.py`, `coach/llm/prompts.py`
- Create: `coach/services/race_advice.py`
- Modify: `coach/api/app.py` (route), `coach/services/race_strategy.py` (vue)
- Test: `tests/llm/test_prompts.py`, `tests/services/test_race_advice.py`, `tests/api/` (route)

**Interfaces:**
- Produces:
```python
class AdviceTip(_Strict): title: str = Field(max_length=60); text: str = Field(max_length=400)
class CoachAdvice(_Strict): tips: list[AdviceTip] = Field(min_length=3, max_length=6)
def validate_advice(advice: CoachAdvice, prompt: str) -> list[str]
def build_race_advice_prompt(goal: Goal, view: RaceView, history: list[Activity], long_history: LongHistory | None, recent: list[Goal]) -> str
def ask_race_advice(repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int) -> RaceView
def advice_fingerprint(goal: Goal, plan: RacePlan) -> str   # reference_time_s | race_date | distance | gpx_summary_json | notes
```
- Route : `POST /api/goals/{goal_id}/race-plan/advice` → `RaceView`.
- Prompt : objectif avec notes (`_goal_line`), guide (temps, allure, phases, passages, nutrition), `_history_text`, `_long_history_text`, courses récentes ; consigne : ne citer que des chiffres présents ci-dessus, ne jamais en proposer de nouveaux.
- `validate_advice` : chaque allure (`\d{1,2}[:']\d{2}` suivi de `/km` ou `min/km`), heure (`\d{1,2}[h:]\d{2}`) ou durée (`\d+ ?h ?\d{0,2}`, `\d+ ?min`) du texte, normalisée, doit apparaître dans le prompt ; sinon message d'erreur citant le chiffre.
- `tracked(repo, "race_advice")` ; enregistre `advice_json`, `advice_at`, `advice_hash`, puis `refresh_snapshot`. `RaceView.advice_stale = advice_hash != advice_fingerprint(...)`.

- [ ] **Step 1: Tests** — `test_advice_accepts_history_figures` (prompt contenant « 1:48 », conseil citant « 1:48 » → `[]`) ; `test_advice_rejects_invented_pace` (« 4:30/km » absent → 1 erreur) ; `test_ask_race_advice_saves_and_marks_fresh` (`FakeLLMProvider`) ; `test_advice_stale_after_target_change` ; `test_advice_not_stale_after_start_time_change` ; `test_prompt_contains_notes_and_phases`.
- [ ] **Step 2:** `uv run pytest tests/llm tests/services/test_race_advice.py tests/api -v` → FAIL.
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** Même commande → PASS.
- [ ] **Step 5:** Commit `feat: conseils du coach pour le jour J`.

### Task 7: Page Jour J (ordinateur)

**Files:**
- Modify: `web/src/lib/api.ts` (types `RaceGuide`, `Phase`, `Split`, `GuideNutrition`, `MorningStep`, `PrepBlock`, `CoachAdvice` ; champs de `RaceView` ; `carbs_g_h`/`water_ml_h` nullables ; `api.raceAdvice(goalId)`)
- Modify: `web/src/lib/race.ts` (`settingsError` accepte `null`)
- Create: `web/src/components/race/RaceGuide.svelte` (encadré « À retenir le matin », phases, passages, eau et nutrition, préparation), `web/src/components/race/CoachAdvice.svelte`
- Modify: `web/src/routes/Race.svelte`
- Test: `web/src/routes/Race.test.ts`, `web/src/lib/race.test.ts`

Encadré route : temps, allure moyenne, consigne du Départ, passages, matin, prises. Encadré trail : temps, consigne FC, résumé des phases, passages aux ravitos avec marge sur la barrière (`plan.aid_passages`), glucides par heure et eau à emporter.

Ordre de la page : en-tête, encadré, réglages (heure de départ, Modifier l'objectif, glucides et eau pour tous — vides = « recommandé : X »), Pendant la course, Passages, Eau et nutrition, Préparation, Conseils du coach (bouton « Demander les conseils du coach », date, mention « Objectif modifié depuis : redemande les conseils », erreur locale sans casser la page), Parcours (`<details>` replié avec profil et tableau des segments, **seulement** si `profile` ou trail), Ravitaillements (trail), actions.

- [ ] **Step 1: Tests** — `a road goal without GPX shows phases and splits, no segment table` ; `a road goal with a profile keeps the segment table folded` ; `empty carbs show the recommended value` ; `coach advice button posts and renders tips` ; `stale advice shows the redo hint` ; `advice error stays inside its section` ; adapter les tests existants.
- [ ] **Step 2:** `cd web; npm test -- Race` → FAIL.
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** `cd web; npm test` → PASS.
- [ ] **Step 5:** Commit `feat(web): page Jour J en guide de course`.

### Task 8: Jour J sur mobile

**Files:**
- Modify: `web/src/lib/turso/reads.ts` (`raceView(db, goalId): Promise<RaceView | null>` lit `view_json` de `racestrategy` ; `null` si absent ou JSON illisible), `web/src/lib/turso/index.ts`
- Modify: `web/src/lib/api.ts` (`racePlan` : branche `READONLY`), `web/src/App.svelte` (`race` dans les routes `READONLY`), `web/src/components/Sidebar.svelte` (lien Jour J visible en `READONLY`)
- Modify: `web/src/routes/Race.svelte` (`READONLY` : réglages, boutons, édition des ravitos et conseils masqués ; « mis à jour le … » ; vue `null` → « Ouvre le Jour J sur l'ordinateur pour préparer ce guide »)
- Modify: `tests/mobile_fixtures.py` (une stratégie avec copie), régénérer les fixtures
- Test: `web/src/lib/turso/reads.test.ts`, `web/src/routes/Race.test.ts`, `web/src/App.test.ts`

- [ ] **Step 1: Tests** — `raceView matches the Python view` (fixture) ; `shows the desktop hint when the snapshot is missing or unreadable` ; `readonly hides settings and buttons` ; `readonly sidebar shows the Jour J link` ; garde-fou existant « la PWA n'écrit jamais » toujours vert.
- [ ] **Step 2:** `uv run python -m tests.mobile_fixtures; cd web; npm test` → FAIL.
- [ ] **Step 3:** Implémenter.
- [ ] **Step 4:** `uv run pytest -q; cd web; npm test` → PASS.
- [ ] **Step 5:** Commit `feat(web): Jour J lisible sur mobile`.
