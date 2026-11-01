# Stratégie du jour J — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une page « Jour J » qui tire du GPX de l'objectif actif une prédiction de temps, un découpage par segment avec allures et temps de passage, et en trail les passages aux ravitos, barrières et nutrition ; exportable sur la montre et résumée en une ligne pour Claude.

**Architecture:** Calcul déterministe et pur dans `coach/analysis/race_plan.py` (Minetti + Riegel), alimenté par un profil GPX rééchantillonné (`gpx.py`). Une table `RaceStrategy` stocke les réglages et une base de référence capturée depuis Garmin ; le plan est recalculé à chaque lecture par `coach/services/race_strategy.py`, exposé par cinq routes FastAPI et affiché par une route Svelte `#/race`.

**Tech Stack:** Python 3.12, pydantic, SQLModel/SQLite, FastAPI, gpxpy ; Svelte 5, TypeScript, ECharts 5, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-01-race-strategy-design.md`

## Global Constraints

- Aucune colonne ajoutée à une table existante : toute persistance nouvelle va dans la table `RaceStrategy` (`create_all` sans migration).
- Calcul déterministe : aucun appel LLM pour le plan ; mêmes entrées, même plan.
- Profil rééchantillonné tous les **50 m** ; pente de classement glissante sur **200 m** ; montée **> +3 %**, descente **< −3 %**.
- Multiplicateur de Minetti borné entre **0,8** et **6**, pente bornée à **±0,45**.
- Riegel exposant **1,06**, puis **1,10** au-delà de **42,195** km équivalents ; repli allure marathon = allure seuil × **1,09**.
- Segments : absorption sous **500 m**, au plus **25** segments.
- Défauts : départ `08:00`, **60** g/h, **500** ml/h, contenance **1 000** ml, arrêt **1** min (`eau`) / **3** min (`complet`).
- Statut barrière : `ok` > 30 min, `serré` 0–30 min, `hors délai` < 0.
- Zone FC de course : **Z4** < 1 h 30, **Z3** ≤ 4 h, **Z2** au-delà ; zone inférieure en descente. Cible d'allure route : ± **5** s/km.
- Waypoints à plus de **200 m** de la trace ignorés. Base de plus de **30** jours : avertissement.
- Textes utilisateur en français, sans signature Claude dans les commits.
- Tests : `uv run pytest` (Python), `npm test` dans `web/` (front).

## Review Focus

- **Waypoints « Départ » / « Arrivée » du GPX organisateur** : ils se projettent à km 0 ou à la distance totale ; ils ne doivent pas devenir des ravitos (test dans la tâche 1).
- **Distance saisie ≠ distance du GPX** (42 saisis, 43,1 dans le GPX) : le plan utilise la distance du profil quand il existe, sinon celle de l'objectif ; la validation des ravitos utilise la même (test dans la tâche 6).
- **Départ tardif d'un ultra** : l'heure de passage affichée boucle sur 24 h (`00:18`, jamais `24:18`) (test dans la tâche 5).
- **Parcours très court ou entièrement plat** : le découpage termine et rend un seul segment couvrant toute la distance (test dans la tâche 4).
- **Ancien workout déjà supprimé à la main sur Garmin** : le ré-export réussit quand même, l'id passe en `pending_old_*` (test dans la tâche 7).

---

### Task 1: Profil et waypoints du GPX

**Files:**
- Modify: `coach/analysis/gpx.py`
- Modify: `tests/fixtures/gpx/make_fixtures.py` (+ fichier généré `tests/fixtures/gpx/trail_wpt.gpx`)
- Test: `tests/analysis/test_gpx.py`

**Interfaces:**
- Produces:
  - `class ProfilePoint(BaseModel): km: float; ele_m: float`
  - `class Waypoint(BaseModel): name: str; km: float`
  - `profile(data: bytes) -> list[ProfilePoint] | None` — `None` si la trace n'a pas d'altitude ; premier point à km 0, un point tous les 0,05 km, dernier point exactement à la distance totale.
  - `waypoints(data: bytes) -> list[Waypoint]` — triés par km, seulement ceux à ≤ 200 m de la trace et avec `0 < km < distance` (strictement, après arrondi à 0,01 km).
  - Les deux lèvent `GpxError` comme `analyze_gpx`.

- [ ] **Step 1: Générer le fixture `trail_wpt.gpx`**

Dans `make_fixtures.py`, réutiliser le tracé de `climb.gpx` et ajouter quatre `<wpt>` avant `<trk>` : « Départ » au premier point, « Ravito Col » au point du km 4, « Parking » décalé de 0,01° en longitude du point du km 6 (≈ 790 m de la trace), « Arrivée » au dernier point. `_gpx` prend un paramètre `wpts: list[tuple[str, float, float]] = ()`. Lancer `uv run python tests/fixtures/gpx/make_fixtures.py` et committer le fichier généré.

- [ ] **Step 2: Écrire les tests**

```python
def test_profile_resampled_every_50_m():
    p = profile(FIX("climb.gpx"))
    assert p[0].km == 0
    assert p[-1].km == pytest.approx(analyze_gpx(FIX("climb.gpx")).distance_km, abs=0.01)
    assert all(b.km - a.km == pytest.approx(0.05, abs=1e-6) for a, b in zip(p, p[1:-1]))
    top = max(p, key=lambda x: x.ele_m)
    assert top.ele_m == pytest.approx(400, abs=15) and top.km == pytest.approx(4.0, abs=0.2)

def test_profile_none_without_elevation():
    assert profile(FIX("flat_no_ele.gpx")) is None

def test_profile_broken_raises():
    with pytest.raises(GpxError):
        profile(FIX("broken.gpx"))

def test_waypoints_projected_and_filtered():
    w = waypoints(FIX("trail_wpt.gpx"))
    assert [x.name for x in w] == ["Ravito Col"]  # départ/arrivée à km 0 / fin, parking hors trace
    assert w[0].km == pytest.approx(4.0, abs=0.05)

def test_waypoints_empty_when_none():
    assert waypoints(FIX("climb.gpx")) == []
```

- [ ] **Step 3: Lancer les tests et vérifier l'échec**

Run: `uv run pytest tests/analysis/test_gpx.py -v`
Expected: FAIL (`ImportError: cannot import name 'profile'`).

- [ ] **Step 4: Implémenter**

Factoriser `_parse(data) -> tuple[list[GPXTrackPoint], list[float]]` (points et km cumulés, lève `GpxError`), utilisé par `analyze_gpx`, `profile` et `waypoints`. `profile` lisse avec `_smooth` puis interpole linéairement l'altitude aux km multiples de 0,05 et à la distance finale. `waypoints` lit `gpx.waypoints`, prend le point de trace le plus proche (`gpxpy.geo.distance`), garde `name or "Ravito"`.

- [ ] **Step 5: Lancer les tests**

Run: `uv run pytest tests/analysis/test_gpx.py -v`
Expected: PASS (tests existants compris).

- [ ] **Step 6: Commit**

```bash
git add coach/analysis/gpx.py tests/analysis/test_gpx.py tests/fixtures/gpx/
git commit -m "feat(gpx): profil rééchantillonné et waypoints projetés sur la trace"
```

---

### Task 2: Prédictions Garmin et zones depuis les métriques

**Files:**
- Modify: `coach/garmin/port.py` (`Metrics`)
- Modify: `coach/garmin/client.py:205-226`
- Modify: `coach/services/context.py`
- Test: `tests/garmin/test_client.py`, `tests/services/test_*` existants

**Interfaces:**
- Produces:
  - `Metrics.pred_5k_s`, `Metrics.pred_half_s`, `Metrics.pred_marathon_s: int | None = None` (lus dans `time5K`, `timeHalfMarathon`, `timeMarathon`).
  - `zones_from_metrics(m: Metrics) -> Zones` dans `coach/services/context.py` — l'appel `compute_zones` actuel de `refresh_snapshot`, `ValueError` converti en `CoachError` avec le même message ; `refresh_snapshot` l'utilise.

- [ ] **Step 1: Test** — dans `tests/garmin/test_client.py`, à côté du test existant des métriques (fixture `race_predictions.json`) : `assert (m.pred_5k_s, m.pred_10k_s, m.pred_half_s, m.pred_marathon_s) == (1380, 2880, 6400, 13500)`.
- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/garmin/test_client.py -v` ; Expected: FAIL (`AttributeError`).
- [ ] **Step 3: Implémenter** les trois champs et `zones_from_metrics`.
- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` ; Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(garmin): prédictions 5 km, semi et marathon"`

---

### Task 3: Modèle d'effort et prédiction de temps

**Files:**
- Create: `coach/analysis/race_plan.py`
- Test: `tests/analysis/test_race_plan.py`

**Interfaces:**
- Consumes: `ProfilePoint` (tâche 1), `HrZoneName` (`coach/analysis/zones.py`).
- Produces:
  - `class RaceBasis(BaseModel)`: `captured_on: date`, `pred_5k_s`, `pred_10k_s`, `pred_half_s`, `pred_marathon_s`, `threshold_pace_s_km: int | None`, `hr: dict[HrZoneName, tuple[int, int]]`.
  - `grade_multiplier(grade: float) -> float`
  - `step_eq_km(profile: list[ProfilePoint]) -> list[float]` — distance équivalente de chaque pas (len = len(profile) − 1).
  - `predict_run_time(eq_km: float, basis: RaceBasis) -> int | None` — secondes, arrondi à la seconde.

- [ ] **Step 1: Tests**

```python
def test_grade_multiplier():
    assert grade_multiplier(0) == pytest.approx(1)
    assert grade_multiplier(0.10) == pytest.approx(1.658, abs=0.01)
    assert grade_multiplier(-0.05) == 0.8          # borne basse
    assert grade_multiplier(-0.30) == 0.8
    assert grade_multiplier(0.60) == grade_multiplier(0.45) <= 6

def test_step_eq_km_flat_and_climb():
    flat = [ProfilePoint(km=i * 0.05, ele_m=100) for i in range(21)]
    assert sum(step_eq_km(flat)) == pytest.approx(1.0)
    climb = [ProfilePoint(km=i * 0.05, ele_m=100 + 5 * i) for i in range(21)]  # +10 %
    assert sum(step_eq_km(climb)) == pytest.approx(1.658, abs=0.01)

B = dict(captured_on=date(2026, 11, 1), threshold_pace_s_km=None, hr={})

def test_predict_nearest_reference_riegel():
    b = RaceBasis(pred_5k_s=None, pred_10k_s=2880, pred_half_s=None, pred_marathon_s=None, **B)
    assert predict_run_time(10, b) == 2880
    assert predict_run_time(21.0975, b) == round(2880 * 2.10975 ** 1.06)
    b2 = b.model_copy(update={"pred_half_s": 6400})
    assert predict_run_time(20, b2) == round(6400 * (20 / 21.0975) ** 1.06)

def test_predict_ultra_switches_exponent():
    b = RaceBasis(pred_5k_s=None, pred_10k_s=None, pred_half_s=None, pred_marathon_s=13500, **B)
    assert predict_run_time(60, b) == round(13500 * (60 / 42.195) ** 1.10)

def test_predict_threshold_fallback_and_none():
    b = RaceBasis(pred_5k_s=None, pred_10k_s=None, pred_half_s=None, pred_marathon_s=None,
                  captured_on=date(2026, 11, 1), threshold_pace_s_km=300, hr={})
    assert predict_run_time(42.195, b) == round(42.195 * 300 * 1.09)
    assert predict_run_time(10, b.model_copy(update={"threshold_pace_s_km": None})) is None
```

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/analysis/test_race_plan.py -v` ; Expected: FAIL (module absent).
- [ ] **Step 3: Implémenter** — Minetti `C(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² + 19.5i + 3.6`, `m = clamp(C(i)/3.6, 0.8, 6)`, `i` borné à ±0,45. Pas : `i = Δele / (Δkm × 1000)`. Référence la plus proche en |D_eq − D_ref| parmi (5, 10, 21,0975, 42,195) non nuls ; au-delà de 42,195, `T42` = Riegel 1,06 depuis cette référence, puis `T42 × (D/42.195)^1.10`. Repli seuil : `T42 = 42.195 × seuil × 1.09`, puis Riegel 1,06 ou 1,10 selon D.
- [ ] **Step 4: Vérifier** — même commande ; Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(race-plan): coût de pente (Minetti) et prédiction Riegel"`

---

### Task 4: Découpage en segments

**Files:**
- Modify: `coach/analysis/race_plan.py`
- Test: `tests/analysis/test_race_plan.py`

**Interfaces:**
- Produces:
  - `SegmentKind = Literal["montée", "plat", "descente"]`
  - `class Span(BaseModel)`: `kind: SegmentKind`, `start_km`, `end_km`, `eq_km: float`, `d_plus_m`, `d_minus_m: int`.
  - `split_segments(profile: list[ProfilePoint] | None, distance_km: float) -> list[Span]` — couvre `[0, distance]` sans trou, au plus 25 éléments.

- [ ] **Step 1: Tests** — helper de test `_prof(parts: list[tuple[float, float]])` (longueur km, pente) qui construit des points tous les 0,05 km.

```python
def test_split_kinds():
    s = split_segments(_prof([(1, 0), (3, 0.10), (1, -0.30), (1, 0)]), 6)
    assert [x.kind for x in s] == ["plat", "montée", "descente", "plat"]
    assert s[1].d_plus_m == pytest.approx(300, abs=15)

def test_short_bump_absorbed():
    s = split_segments(_prof([(2, 0), (0.3, 0.10), (2, 0)]), 4.3)
    assert [x.kind for x in s] == ["plat"]

def test_at_most_25_contiguous():
    s = split_segments(_prof([(0.6, 0.08), (0.6, -0.08)] * 30), 36)
    assert len(s) <= 25
    assert s[0].start_km == 0 and s[-1].end_km == pytest.approx(36)
    assert all(a.end_km == b.start_km for a, b in zip(s, s[1:]))

def test_tiny_flat_course_single_segment():
    s = split_segments(_prof([(0.3, 0)]), 0.3)
    assert len(s) == 1 and s[0].end_km == pytest.approx(0.3)

@pytest.mark.parametrize("dist,n,first", [(10, 10, 1), (42.195, 21, 2), (100, 20, 5), (180, 18, 10)])
def test_slices_without_profile(dist, n, first):
    s = split_segments(None, dist)
    assert len(s) == n and s[0].end_km == first and s[-1].end_km == dist
    assert all(x.kind == "plat" and x.eq_km == pytest.approx(x.end_km - x.start_km) for x in s)
```

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/analysis/test_race_plan.py -v` ; Expected: FAIL.
- [ ] **Step 3: Implémenter** — algorithme fixé :
  1. Pente du pas j = `(ele[min(j+2, n)] − ele[max(j−2, 0)]) / (Δkm × 1000)` sur ces mêmes bornes (≈ 200 m) ; classement selon ±3 %.
  2. Fusion des pas consécutifs de même type.
  3. Tant qu'un segment fait < 0,5 km et qu'il y en a plus d'un : le plus court est fusionné dans son voisin le plus long ; type = dominant en distance ; puis refusion des voisins de même type.
  4. Tant qu'il y en a > 25 : le plus court est fusionné avec son voisin le plus court, même règle de type et de refusion.
  5. Sans profil : taille = la première de (1, 2, 5, 10) donnant ≤ 25 tranches, sinon `distance / 25` ; un reste < taille / 2 est ajouté à la dernière tranche ; `eq_km` = longueur, D+/D- = 0.
- [ ] **Step 4: Vérifier** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(race-plan): découpage en montées, plats et descentes"`

---

### Task 5: Plan de course complet

**Files:**
- Modify: `coach/analysis/race_plan.py`
- Test: `tests/analysis/test_race_plan.py`

**Interfaces:**
- Consumes: tâches 3 et 4.
- Produces:
  - `class AidStation(BaseModel)`: `km: float = Field(gt=0)`, `name: str = Field(min_length=1, max_length=60)`, `kind: Literal["eau", "complet"] = "complet"`, `cutoff: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")`, `stop_min: float = Field(3, ge=0, le=120)`.
  - `class RaceSettings(BaseModel)`: `target_time_s: int | None = Field(None, gt=0)`, `start_time: str = Field("08:00", pattern=même)`, `carbs_g_h: int = Field(60, ge=0, le=150)`, `water_ml_h: int = Field(500, ge=0, le=2000)`, `carry_ml: int = Field(1000, gt=0, le=5000)`, `aid_stations: list[AidStation] = []`.
  - `class Segment(Span)`: `index: int`, `avg_grade_pct: float`, `time_s`, `pace_s_km`, `elapsed_s: int | None` (cumul à la fin du segment, arrêts franchis inclus), `clock: str | None` (`HH:MM`), `target_kind: Literal["pace", "hr"]`, `target_low`, `target_high: int | None` (s/km ou bpm), `target_zone: HrZoneName | None`.
  - `class Passage(BaseModel)`: `elapsed_s: int`, `clock: str`, `margin_min: int | None`, `status: Literal["ok", "serré", "hors délai"] | None`.
  - `class AidPassage(BaseModel)`: `station: AidStation`, `predicted: Passage | None`, `target: Passage | None`.
  - `class NutritionLeg(BaseModel)`: `from_name`, `to_name: str`, `from_km`, `to_km: float`, `duration_s`, `carbs_g`, `water_ml: int`, `over_capacity: bool`.
  - `class RacePlan(BaseModel)`: `distance_km`, `eq_km: float`, `stops_s: int`, `predicted_time_s`, `target_time_s`, `reference_time_s: int | None`, `segments: list[Segment]`, `aid_passages: list[AidPassage]`, `nutrition: list[NutritionLeg]`, `warnings: list[str]`.
  - `race_hr_zone(total_s: int) -> HrZoneName`
  - `build_race_plan(*, distance_km: float, trail: bool, profile: list[ProfilePoint] | None, basis: RaceBasis, settings: RaceSettings, today: date) -> RacePlan` — lève `ValueError("Le temps visé doit dépasser la durée des arrêts aux ravitos")`.
  - Constantes de message : `NO_TIME = "Pas de prédiction possible : saisis un temps visé pour obtenir le découpage"`, `STALE = "Données de référence du {:%d/%m/%Y} : actualise-les avant la course"`, `LATE = "Barrière hors délai au ravito « {} » avec le temps prédit"`.

Règles (spec §4.3, 4.5, 5) : arrêts comptés seulement si `trail` ; temps de course de référence = (visé − arrêts) ou prédit ; temps de segment = temps de course × `eq_km` / `eq_km` total ; un ravito ajoute son arrêt au cumul des segments qui se terminent après son km ; arrivée au ravito = cumul au début du segment + interpolation linéaire en distance (arrêt du ravito lui-même exclu) ; `clock` = (départ + écoulé) modulo 24 h ; marge = barrière − (départ + écoulé), en minutes arrondies, sans modulo ; `predicted`/`target` de `AidPassage` calculés quand le temps correspondant existe ; nutrition et ravitos seulement si `trail` et temps de référence connu ; cible route `pace ± 5` ; cible trail = bornes bpm de `race_hr_zone(référence)` (zone inférieure en descente, Z1 reste Z1) ; sans temps de référence, champs de temps et cibles à `None` et `NO_TIME` en avertissement.

- [ ] **Step 1: Tests**

```python
BASIS = RaceBasis(captured_on=date(2026, 11, 1), pred_5k_s=None, pred_10k_s=2880, pred_half_s=None,
                  pred_marathon_s=None, threshold_pace_s_km=None,
                  hr={"Z1": (100, 120), "Z2": (120, 140), "Z3": (140, 160), "Z4": (160, 175), "Z5": (175, 190)})
TODAY = date(2026, 11, 2)

def plan(**kw):
    args = dict(distance_km=10, trail=False, profile=None, basis=BASIS, settings=RaceSettings(), today=TODAY)
    return build_race_plan(**{**args, **kw})

def test_flat_route_prediction_and_pace_targets():
    p = plan()
    assert p.predicted_time_s == p.reference_time_s == 2880 and len(p.segments) == 10
    s = p.segments[0]
    assert (s.time_s, s.pace_s_km, s.target_kind, s.target_low, s.target_high) == (288, 288, "pace", 283, 293)
    assert p.segments[-1].clock == "08:48" and p.aid_passages == [] and p.nutrition == []

def test_target_time_rescales():
    p = plan(settings=RaceSettings(target_time_s=2700))
    assert p.predicted_time_s == 2880 and p.reference_time_s == 2700 and p.segments[0].time_s == 270

def test_climb_slower_than_flat():
    p = plan(trail=True, distance_km=6, profile=_prof([(1, 0), (3, 0.10), (1, -0.30), (1, 0)]))
    flat, up = p.segments[0], p.segments[1]
    assert up.pace_s_km > flat.pace_s_km and up.target_kind == "hr"

STATION = AidStation(km=5, name="Col", kind="complet", cutoff="08:50", stop_min=3)

def test_aid_passage_margin_and_nutrition():
    p = plan(trail=True, settings=RaceSettings(aid_stations=[STATION]))
    assert p.stops_s == 180 and p.reference_time_s == 3060
    a = p.aid_passages[0].predicted
    assert (a.elapsed_s, a.clock, a.margin_min, a.status) == (1440, "08:24", 26, "serré")
    assert [(n.from_name, n.to_name, n.duration_s, n.carbs_g, n.water_ml) for n in p.nutrition] == [
        ("Départ", "Col", 1440, 24, 200), ("Col", "Arrivée", 1440, 24, 200)]

def test_late_cutoff_warns_and_capacity_alert():
    st = STATION.model_copy(update={"cutoff": "08:20"})
    p = plan(trail=True, settings=RaceSettings(aid_stations=[st], carry_ml=100))
    assert p.aid_passages[0].predicted.status == "hors délai"
    assert LATE.format("Col") in p.warnings and all(n.over_capacity for n in p.nutrition)

def test_target_passage_computed_alongside_predicted():
    p = plan(trail=True, settings=RaceSettings(aid_stations=[STATION], target_time_s=3600))
    assert p.aid_passages[0].target.elapsed_s == 1710 and p.aid_passages[0].predicted.elapsed_s == 1440

def test_target_not_above_stops_rejected():
    with pytest.raises(ValueError, match="arrêts"):
        plan(trail=True, settings=RaceSettings(aid_stations=[STATION], target_time_s=180))

def test_no_reference_time():
    b = BASIS.model_copy(update={"pred_10k_s": None})
    p = plan(basis=b)
    assert p.predicted_time_s is None and p.segments[0].time_s is None and NO_TIME in p.warnings

def test_stale_basis_warns():
    assert STALE.format(date(2026, 11, 1)) in plan(today=date(2026, 12, 5)).warnings

def test_clock_wraps_after_midnight():
    assert plan(settings=RaceSettings(start_time="23:30")).segments[-1].clock == "00:18"

@pytest.mark.parametrize("t,z", [(5000, "Z4"), (10000, "Z3"), (14400, "Z3"), (20000, "Z2")])
def test_race_hr_zone(t, z):
    assert race_hr_zone(t) == z
```

- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/analysis/test_race_plan.py -v` ; Expected: FAIL.
- [ ] **Step 3: Implémenter** `build_race_plan` et `race_hr_zone` selon les règles ci-dessus.
- [ ] **Step 4: Vérifier** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(race-plan): temps de passage, barrières et nutrition"`

---

### Task 6: Table `RaceStrategy` et service

**Files:**
- Modify: `coach/plan/models.py`, `coach/plan/repo.py` (import de la table pour `create_all`)
- Create: `coach/services/race_strategy.py`
- Test: `tests/services/test_race_strategy.py`

**Interfaces:**
- Consumes: `profile`, `waypoints` (tâche 1), `zones_from_metrics` (tâche 2), `build_race_plan` et modèles (tâche 5), `GoalError` (`coach/services/plans.py`).
- Produces:
  - `class RaceStrategy(SQLModel, table=True)` : colonnes de la spec §3.2 ; `settings_json: str` (un `RaceSettings` sérialisé, ravitos compris) au lieu de colonnes séparées ; `basis_json: str`.
  - `class RaceView(BaseModel)` : `goal_id: int`, `goal_type: Literal["route", "trail"]`, `race_date: date`, `settings: RaceSettings`, `basis_date: date`, `profile: list[tuple[float, float]] | None` (≤ 500 points, sous-échantillonné régulièrement, pour le graphique), `plan: RacePlan`, `workout_id: int | None`, `export_error: str | None`.
  - `get_race_view(repo, garmin, goal_id) -> RaceView` — crée la stratégie à la première lecture (base capturée via `garmin.metrics()` + `zones_from_metrics`, ravitos pré-remplis depuis `waypoints` si trail, `kind="complet"`, `stop_min=3`).
  - `save_settings(repo, garmin, goal_id, settings: RaceSettings) -> RaceView` — trie les ravitos par km ; refuse `km ≥ distance du plan` et le temps visé ≤ arrêts par `CoachError` (message de `build_race_plan`).
  - `refresh_basis(repo, garmin, goal_id) -> RaceView`, `reimport_stations(repo, garmin, goal_id) -> RaceView`.
  - `race_plan_for(repo, goal, today) -> RacePlan | None` — `None` sans stratégie ; utilisé par la tâche 9.
  - Distance du plan = dernier km du profil s'il existe, sinon `goal.distance_km`. `gpx_path` absent du disque → profil `None` + avertissement `"Fichier GPX introuvable : découpage sans profil"` ; GPX sans altitude → avertissement `_NO_ELE` de `gpx.py`. `garmin.today()` sert de `today`.

- [ ] **Step 1: Tests** — objectif créé via `create_goal` avec `FakeGarminClient(metrics=Metrics(hr_max=190, hr_rest=50, pred_10k_s=2880))` et `coach_home` ; GPX `trail_wpt.gpx`.
  - `test_first_read_creates_with_waypoints` : `view.settings.aid_stations[0].name == "Ravito Col"`, `view.basis_date == garmin.today()`, `"metrics"` lu une seule fois sur deux lectures (compter via un `FakeGarminClient` dont `metrics` est enveloppé).
  - `test_route_goal_has_no_stations` : objectif route avec le même GPX → `aid_stations == []`.
  - `test_save_then_read` : `save_settings(... RaceSettings(target_time_s=3600, aid_stations=[...]))` puis `get_race_view(...).settings.target_time_s == 3600` ; ravitos renvoyés triés par km.
  - `test_station_beyond_gpx_distance_rejected` : goal `distance_km=9` mais GPX de 10 km → ravito à 9,5 accepté, à 10,5 refusé (`CoachError`).
  - `test_target_below_stops_rejected` (`CoachError`, message « arrêts »).
  - `test_refresh_updates_basis` : nouvelles métriques sur le fake → `plan.predicted_time_s` change.
  - `test_reimport_replaces_stations`.
  - `test_missing_gpx_file_warns` : fichier supprimé → `plan.warnings` contient le message, `profile is None`.
  - `test_archived_goal_rejected` (`GoalError`).
- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/services/test_race_strategy.py -v` ; Expected: FAIL.
- [ ] **Step 3: Implémenter.**
- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` ; Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(race-strategy): table, création et réglages de la stratégie"`

---

### Task 7: Export vers la montre

**Files:**
- Modify: `coach/export/garmin_workout.py`, `coach/services/race_strategy.py`
- Test: `tests/export/test_garmin_workout.py`, `tests/services/test_race_strategy.py`

**Interfaces:**
- Consumes: `RacePlan`, `Segment` (tâche 5), service (tâche 6).
- Produces:
  - `race_to_workout_json(plan: RacePlan, *, name: str) -> dict` — une étape `interval` par segment, fin `distance` = longueur en mètres ; cible `pace.zone` (m/s, `targetValueOne = 1000 / target_high`, `targetValueTwo = 1000 / target_low`) ou `heart.rate.zone` (bpm) ; `description` = `"{Kind} +{d_plus} m – viser {mm} min"` (`"Montée +450 m – viser 52 min"` ; `+D` omis si 0). Lève `ValueError` si `reference_time_s is None`.
  - `export_race(repo, garmin, goal_id) -> RaceView` — nom `"Jour J – {distance:g} km"`, programmé à `goal.race_date` ; envoi + programmation d'abord ; puis suppression de l'ancien (`unschedule` puis `delete_workout`) ; échec de suppression → ids dans `pending_old_*`, retentés au début de l'export suivant ; échec d'envoi → `export_error` enregistré, ancien conservé, exception relancée. Sans temps de référence → `CoachError("Pas de temps de référence : saisis un temps visé")`.

- [ ] **Step 1: Tests**
  - `test_race_workout_steps` : plan de la tâche 5 (route 10 km) → 10 étapes, `endConditionValue == 1000`, `targetValueOne == pytest.approx(1000 / 293)` ; plan trail → `heart.rate.zone` et `description` commençant par `"Montée +"`.
  - `test_export_schedules_on_race_day` : `garmin.schedules` contient `(wid, race_date)`, `view.workout_id == wid`.
  - `test_reexport_replaces_old` : deux exports → un seul workout restant.
  - `test_reexport_old_already_deleted` : `fail_on={"delete_workout"}` au 2ᵉ export → succès, `pending_old_workout_id` renseigné ; 3ᵉ export sans échec → nettoyé.
  - `test_export_failure_keeps_old` : `fail_on={"upload_workout"}` → `GarminUnavailable`, ancien conservé, `export_error` renseigné.
- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/export tests/services/test_race_strategy.py -v` ; Expected: FAIL.
- [ ] **Step 3: Implémenter** en réutilisant les constantes `_TARGET_*`, `_END_DISTANCE`, `_STEP_TYPES`, `_SPORT_RUNNING`.
- [ ] **Step 4: Vérifier** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(race-strategy): export du plan de course sur la montre"`

---

### Task 8: Routes API

**Files:**
- Modify: `coach/api/app.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: service (tâches 6 et 7).
- Produces : `GET /api/goals/{id}/race-plan`, `PUT` (corps `RaceSettings`), `POST …/refresh`, `POST …/reimport`, `POST …/export` ; toutes renvoient `RaceView.model_dump(mode="json")`. Les erreurs passent par `_register_errors` existant (`CoachError` → 422 `invalid`, pydantic → 422 par champ).

- [ ] **Step 1: Tests** — `test_race_plan_routes` (création d'objectif trail avec `climb.gpx` via `GOAL_FORM`, puis GET → `plan.segments` non vide ; PUT avec `cutoff: "8h"` → 422 avec `loc` contenant `cutoff` ; PUT valide → `settings.target_time_s` renvoyé ; POST export → `workout_id` non nul) et `test_race_plan_archived_goal_422`.
- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/api/test_app.py -k race_plan -v` ; Expected: FAIL (404).
- [ ] **Step 3: Implémenter** les cinq routes à côté de `/goals/{goal_id}/accept`.
- [ ] **Step 4: Vérifier** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(api): routes du plan de course"`

---

### Task 9: Ligne « Stratégie jour J » pour Claude

**Files:**
- Modify: `coach/llm/prompts.py`, `coach/services/plans.py:94-99`, `coach/services/sync.py:114`
- Test: `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes: `race_plan_for` (tâche 6), `RacePlan`.
- Produces:
  - `race_text(plan: RacePlan) -> str | None` — `None` sans temps de référence ; format exact :
    `"Stratégie jour J (indicative) : temps prévu 5 h 12, visé 5 h 00 ; montées clés km 12 (+450 m) et km 31 (+600 m). N'en tenir compte que pour orienter légèrement le contenu de l'affûtage, sans modifier la structure ni le volume du plan."` — « visé » omis sans temps visé, « temps prévu » omis sans prédiction ; montées clés = 3 plus gros D+ des segments `montée`, triées par km, partie omise s'il n'y en a pas ; km arrondi à l'unité ; durées `"{h} h {mm:02d}"`.
  - `build_generation_prompt(..., race_text: str | None = None)` et `build_adjustment_prompt(..., race_text: str | None = None)` ajoutent la ligne avant le schéma JSON.

- [ ] **Step 1: Tests** — `test_race_text_format` (plan construit à la main, attendre la chaîne exacte ci-dessus), `test_race_text_without_target` (pas de « visé »), `test_prompts_include_race_text` (présente quand passée, absente sinon, pour les deux builders).
- [ ] **Step 2: Vérifier l'échec** — Run: `uv run pytest tests/llm/test_prompts.py -v` ; Expected: FAIL.
- [ ] **Step 3: Implémenter** et passer `race_text=race_text(p) if (p := race_plan_for(repo, goal, today)) else None` dans `generate_plan` et `sync`.
- [ ] **Step 4: Vérifier** — Run: `uv run pytest -q` ; Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(llm): résumé de la stratégie du jour J dans les prompts"`

---

### Task 10: Page « Jour J » — en-tête, segments, réglages, export

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/App.svelte`, `web/src/components/Sidebar.svelte`, `web/src/components/Icon.svelte` (icône `race`)
- Create: `web/src/routes/Race.svelte`, `web/src/lib/race.ts`
- Test: `web/src/lib/race.test.ts`, `web/src/routes/Race.test.ts`

**Interfaces:**
- Consumes: JSON de `RaceView` (tâche 8).
- Produces:
  - Types TS `RaceView`, `RaceSettings`, `AidStation`, `RacePlan`, `RaceSegment`, `AidPassage`, `Passage`, `NutritionLeg` (mêmes champs que les modèles Python).
  - `api.racePlan(goalId)`, `api.saveRacePlan(goalId, settings)` (PUT), `api.refreshRacePlan(goalId)`, `api.reimportRacePlan(goalId)`, `api.exportRacePlan(goalId)` ; ajouter `put` à côté de `get`/`post`.
  - `web/src/lib/race.ts` : `fmtDuration(s: number): string` (`"5 h 12"`, `"48 min"` sous l'heure), `targetLabel(seg: RaceSegment): string` (`"4:43–4:53 /km"` ou `"Z3 · 140–160 bpm"`), `isDirty(a: RaceSettings, b: RaceSettings): boolean`.
  - Route `"race"` ajoutée à `ROUTES` ; entrée « Jour J » dans la barre latérale, après « Programme », seulement si `status.goal` existe ; `Race.svelte` reçoit `goal: Goal`.

- [ ] **Step 1: Tests**
  - `race.test.ts` : `fmtDuration(18720) === "5 h 12"`, `fmtDuration(2880) === "48 min"` ; `targetLabel` pour une cible allure (283/293) et FC ; `isDirty` vrai après changement d'un ravito.
  - `Race.test.ts` (fetch mocké comme dans `Today.test.ts`) : objectif route → temps prédit affiché, tableau des segments avec 10 lignes, pas de section « Ravitaillements » ; modifier le temps visé → libellé « Modifications non enregistrées » visible ; clic « Enregistrer » → requête `PUT` ; clic « Envoyer à la montre » → requête `POST …/export`.
- [ ] **Step 2: Vérifier l'échec** — Run: `npm test` (dans `web/`) ; Expected: FAIL.
- [ ] **Step 3: Implémenter** l'en-tête (temps prédit, date de base + « Actualiser », temps visé via `parseClock`, heure de départ, allure moyenne, D+ en trail, avertissements), le tableau des segments (colonnes spec §6), « Enregistrer », « Envoyer à la montre » et son état. Erreurs via `ErrorBanner` comme les autres routes.
- [ ] **Step 4: Vérifier** — Run: `npm test` puis `npm run build` ; Expected: PASS, build sans erreur.
- [ ] **Step 5: Commit** — `git commit -m "feat(web): page Jour J (prédiction, segments, export montre)"`

---

### Task 11: Page « Jour J » — profil, ravitos et nutrition (trail)

**Files:**
- Modify: `web/src/routes/Race.svelte`, `web/src/lib/stats/echarts.ts` (composants `MarkLine`/`MarkArea` si absents)
- Create: `web/src/components/race/ElevationProfile.svelte`, `web/src/components/race/AidStations.svelte`
- Test: `web/src/routes/Race.test.ts`

**Interfaces:**
- Consumes: types et API de la tâche 10, `EChart.svelte`, `themeColors()`.
- Produces:
  - `ElevationProfile` (props `profile: [number, number][]`, `segments: RaceSegment[]`, `stations: AidStation[]`) : ligne d'altitude, zones colorées par type de segment (`markArea`), repères verticaux nommés aux ravitos (`markLine`) ; absent si `profile` est `null`.
  - `AidStations` (props `stations`, `passages`, `onchange`, `onreimport`) : tableau modifiable (km, nom, type, barrière, arrêt), colonnes calculées (heure prévue, marge, statut coloré `ok`/`serré`/`hors délai`, colonne « visé » si temps visé), ajout et suppression de ligne, bouton « Réimporter depuis le GPX ».
  - Section « Nutrition » : une ligne par tronçon (de → à, durée, glucides, eau, alerte de contenance) ; réglages g/h, ml/h et contenance.

- [ ] **Step 1: Tests** — objectif trail : section « Ravitaillements » avec la ligne du ravito et le statut « serré » ; ajout d'une ligne → « Modifications non enregistrées » ; clic « Réimporter depuis le GPX » → `POST …/reimport` ; section « Nutrition » avec deux tronçons ; graphique présent (`aria-label` du `EChart`) quand `profile` non nul.
- [ ] **Step 2: Vérifier l'échec** — Run: `npm test` ; Expected: FAIL.
- [ ] **Step 3: Implémenter.**
- [ ] **Step 4: Vérifier** — Run: `npm test` puis `npm run build` ; Expected: PASS.
- [ ] **Step 5: Vérifier dans l'appli** — lancer l'application (skill `run`), créer un objectif trail avec `tests/fixtures/gpx/trail_wpt.gpx`, ouvrir `#/race` : profil, segments, ravito « Ravito Col », nutrition ; capture d'écran en thème clair et sombre.
- [ ] **Step 6: Commit** — `git commit -m "feat(web): profil, ravitaillements et nutrition sur la page Jour J"`
