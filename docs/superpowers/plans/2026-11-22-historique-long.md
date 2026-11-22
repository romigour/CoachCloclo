# Historique long dans les prompts — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter aux prompts de génération et d'ajustement un bloc « historique long » (volume mensuel sur 12 mois, compétitions passées, records Garmin) lu dans la base.

**Architecture:** Un module pur `coach/analysis/long_history.py` agrège les données ; `coach/llm/prompts.py` met en texte un `LongHistory` reçu en paramètre ; `coach/services/context.py` le construit depuis le `Repo` et `plans.py` / `adjust.py` le passent aux deux prompts. Les 8 semaines détaillées (`recent_history`, `_history_text`) ne changent pas.

**Tech Stack:** Python 3, SQLModel, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-historique-long-design.md`

## Global Constraints

- Aucun appel Garmin supplémentaire : tout vient du `Repo`.
- `prompts.py` n'accède jamais à la base ; il reçoit un `LongHistory | None`.
- Base sans activité (`repo.has_activities()` faux) : bloc omis, prompt identique à aujourd'hui.
- Course à pied = familles `run` et `trail` de `coach.stats.normalize.sport_family` ; tout le reste = « autres sports ».
- Plafonds : 12 mois (mois en cours compris), 15 compétitions.
- Records retenus : `5k`, `10k`, `half`, `marathon`, `longest_run` (valeur ≤ 0 ignorée). Unités : secondes pour les temps, mètres pour `longest_run`.
- Textes en français. Les lignes de mois ne commencent jamais par `- 2026-` (les tests existants comptent les lignes d'activités ainsi) : on écrit le mois en toutes lettres.

## Review Focus

1. Activité sans `distance_m` ou sans `duration_s` : comptée comme sortie, valeurs manquantes traitées comme 0, sans planter (test dans la tâche 1).
2. Compétition dont l'activité n'a ni temps officiel ni distance : temps = durée de l'activité, distance omise ; activité introuvable : compétition ignorée (tâche 1).
3. Changement d'année : au 15 janvier, la fenêtre va de février de l'année précédente à janvier (tâche 1).
4. Activités hors fenêtre (plus de 12 mois ou datées après aujourd'hui) ignorées (tâche 1).
5. Base vide (import de l'historique pas encore fait) : aucun bloc « Historique long », génération inchangée (tâche 3).

---

### Task 1: Agrégation pure de l'historique long

**Files:**
- Create: `coach/analysis/long_history.py`
- Test: `tests/analysis/test_long_history.py`

**Interfaces:**
- Produces :
  - `@dataclass(frozen=True) class MonthVolume: month: dt.date` (1er du mois), `runs: int`, `run_km: float`, `run_s: float`, `d_plus_m: float`, `longest_km: float`, `other_s: float`
  - `@dataclass(frozen=True) class PastRace: date: dt.date, name: str | None, distance_km: float | None, d_plus_m: float | None, time_s: float | None, overall_rank: int | None, overall_total: int | None`
  - `@dataclass(frozen=True) class LongHistory: months: list[MonthVolume], races: list[PastRace], records: list[PersonalRecord]`
  - `MONTHS = 12`, `MAX_RACES = 15`, `RECORD_KINDS = ("5k", "10k", "half", "marathon", "longest_run")`
  - `monthly_volume(activities: list[Activity], today: dt.date, months: int = MONTHS) -> list[MonthVolume]` : exactement `months` entrées, la plus récente d'abord (mois de `today` en premier), mois vides compris.
  - `past_races(races: list[Race], activities: dict[int, Activity], limit: int = MAX_RACES) -> list[PastRace]` : clé du dict = `Activity.id` ; `excluded` ignorées ; plus récentes d'abord ; `time_s` = `official_time_s` sinon `duration_s`.
  - `kept_records(records: list[PersonalRecord]) -> list[PersonalRecord]` : dans l'ordre de `RECORD_KINDS`, valeur > 0.

- [ ] **Step 1: Écrire les tests** (factory `tests.plan.factories.make_activity`)

```python
TODAY = date(2026, 11, 22)

def test_monthly_volume_twelve_months_most_recent_first():
    m = monthly_volume([], TODAY)
    assert [x.month for x in m][:2] == [date(2026, 11, 1), date(2026, 10, 1)]
    assert len(m) == 12 and m[-1].month == date(2025, 12, 1)
    assert all(x.runs == 0 and x.other_s == 0 for x in m)

def test_monthly_volume_sums_running_and_other_sports():
    acts = [
        make_activity(garmin_activity_id=1, date=date(2026, 11, 3), type_key="running", duration_s=3600, distance_m=10000, d_plus_m=100),
        make_activity(garmin_activity_id=2, date=date(2026, 11, 9), type_key="trail_running", duration_s=7200, distance_m=20000, d_plus_m=900),
        make_activity(garmin_activity_id=3, date=date(2026, 11, 10), type_key="cycling", duration_s=5400, distance_m=40000),
    ]
    nov = monthly_volume(acts, TODAY)[0]
    assert (nov.runs, nov.run_km, nov.run_s, nov.d_plus_m, nov.longest_km, nov.other_s) == (2, 30.0, 10800, 1000, 20.0, 5400)

def test_monthly_volume_missing_values_count_as_zero():
    nov = monthly_volume([make_activity(date=date(2026, 11, 3), distance_m=None, duration_s=None)], TODAY)[0]
    assert (nov.runs, nov.run_km, nov.run_s) == (1, 0.0, 0)

def test_monthly_volume_ignores_out_of_window():
    acts = [make_activity(garmin_activity_id=1, date=date(2025, 11, 30)),
            make_activity(garmin_activity_id=2, date=date(2026, 11, 23))]
    assert all(x.runs == 0 for x in monthly_volume(acts, TODAY))

def test_monthly_volume_crosses_year():
    m = monthly_volume([], date(2027, 1, 15))
    assert m[0].month == date(2027, 1, 1) and m[1].month == date(2026, 12, 1) and m[-1].month == date(2026, 2, 1)

def test_past_races_order_limit_and_fallbacks():
    # 20 courses non exclues + 1 exclue + 1 sans activité ; la plus récente a un temps officiel
    ...
    assert len(out) == 15 and out[0].date > out[1].date
    assert out[0].time_s == official            # temps officiel prioritaire
    assert <course sans temps officiel>.time_s == activité.duration_s
    assert <course dont l'activité n'a pas de distance>.distance_km is None
    # l'exclue et celle sans activité n'apparaissent pas

def test_kept_records_order_and_filter():
    recs = [PersonalRecord(kind=k, value=v) for k, v in
            [("longest_run", 32400), ("1k", 200), ("10k", 2535), ("5k", 0), ("marathon", 11000)]]
    assert [r.kind for r in kept_records(recs)] == ["10k", "marathon", "longest_run"]
```

`test_past_races_order_limit_and_fallbacks` : construire les `Race(activity_id=..., ...)` et le dict `{id: Activity}` à la main (ids fixés), avec les assertions ci-dessus.

- [ ] **Step 2: Lancer** `pytest tests/analysis/test_long_history.py -v` → échec à l'import.
- [ ] **Step 3: Implémenter** `coach/analysis/long_history.py` selon les interfaces (familles via `coach.stats.normalize.sport_family`, fenêtre = du 1er du mois de `today` moins 11 mois jusqu'à `today` inclus).
- [ ] **Step 4: Relancer** → PASS.
- [ ] **Step 5: Commit** `feat(analysis): agrégation de l'historique long (mois, courses, records)`

---

### Task 2: Bloc texte dans les deux prompts

**Files:**
- Modify: `coach/llm/prompts.py` (nouvelles fonctions près de `_history_text` ; paramètres de `build_generation_prompt` et `build_adjustment_prompt`)
- Test: `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes : `LongHistory`, `MonthVolume`, `PastRace` (tâche 1).
- Produces : paramètre mot-clé `long_history: LongHistory | None = None` sur `build_generation_prompt` et `build_adjustment_prompt` ; le bloc est inséré juste après `_history_text(history)` dans les deux.
  - `_long_history_text(lh: LongHistory | None) -> str | None` : `None` si `lh` est `None` ou si les trois parties sont omises.
  - `_fmt_time(s: float) -> str` : `"1:35:12"` si ≥ 3600 s, sinon `"42:15"`.

Texte exact (une partie vide est omise ; la partie mois est omise si tous les mois sont vides) :

```
Historique long (pour situer le niveau de fond et la capacité de charge ; la forme actuelle reste donnée par l'historique récent) :
Volume mensuel de course à pied (12 derniers mois, plus récent d'abord) :
- novembre 2026 : 2 sorties, 30 km, 3 h 00, D+ 1000 m, plus longue 20.0 km | autres sports 1 h 30
- octobre 2026 : aucune course
Compétitions passées (plus récentes d'abord) :
- 2026-10-12 : Trail des Crêtes, 32.0 km, D+ 1450 m, 4:12:05, classement 85/420
Records personnels :
- 10 km : 42:15 (2025-04-06)
- Plus longue sortie : 32.4 km (2025-10-19)
```

Règles : « 1 sortie » au singulier, « N sorties » sinon ; km du mois arrondi à l'entier ; durées du mois avec `fmt_duration` ; `| autres sports …` seulement si `other_s > 0` (aussi après « aucune course ») ; dans une course, chaque champ absent est omis (nom, distance, D+, temps, classement si `overall_rank` ou `overall_total` manque) ; date de record omise (avec ses parenthèses) si `None`. Libellés : `5 km`, `10 km`, `Semi`, `Marathon`, `Plus longue sortie`. Mois via `_MONTHS`.

- [ ] **Step 1: Écrire les tests**
  - `test_long_history_block_format` : un `LongHistory` reprenant les valeurs de l'exemple ci-dessus → chacune des lignes de l'exemple est dans `build_generation_prompt(..., long_history=lh)`.
  - `test_long_history_block_omits_empty_parts` : mois tous vides, une course sans nom ni classement ni D+ (`distance_km=10.0`, `time_s=2400`) et aucun record → contient `"- 2026-05-01 : 10.0 km, 40:00"`, ne contient ni `"Volume mensuel"` ni `"Records personnels"`.
  - `test_long_history_absent_by_default` : sans le paramètre, `"Historique long"` n'apparaît dans aucun des deux prompts.
  - `test_adjustment_prompt_includes_long_history` : `build_adjustment_prompt(..., long_history=lh)` contient `"Historique long"`, placé après `"Historique récent"`.
  - `test_fmt_time` : `_fmt_time(2535) == "42:15"`, `_fmt_time(5712) == "1:35:12"`.
- [ ] **Step 2: Lancer** `pytest tests/llm/test_prompts.py -v` → les nouveaux tests échouent.
- [ ] **Step 3: Implémenter** `_fmt_time`, `_long_history_text` et les deux paramètres.
- [ ] **Step 4: Relancer** `pytest tests/llm -v` → PASS (anciens tests compris).
- [ ] **Step 5: Commit** `feat(llm): historique long dans les prompts de génération et d'ajustement`

---

### Task 3: Construction depuis la base et branchement

**Files:**
- Modify: `coach/services/context.py` (nouvelle fonction après `recent_history`)
- Modify: `coach/services/plans.py:96-100`, `coach/services/adjust.py:81-83`
- Test: `tests/services/test_plans.py`, `tests/services/test_adjust.py`

**Interfaces:**
- Consumes : `monthly_volume`, `past_races`, `kept_records`, `LongHistory` (tâche 1) ; paramètre `long_history=` (tâche 2).
- Produces : `long_history(repo: Repo, today: date) -> LongHistory | None` : `None` si `not repo.has_activities()` ; sinon `LongHistory(monthly_volume(repo.activities_since(<1er du mois de today moins 11 mois>), today), past_races(repo.races(), {a.id: a for a in repo.all_activities()}), kept_records(repo.records()))`.
  `generate_plan` et l'ajustement passent `long_history=long_history(repo, today)` (avec le `today = garmin.today()` déjà présent).

- [ ] **Step 1: Écrire les tests**
  - `test_generation_prompt_has_long_history` (test_plans) : après `_goal(repo, fake_garmin)`, enregistrer une activité en base (`repo.add(make_activity(date=date(2026, 10, 5)))`) puis `generate_plan` → `"- octobre 2026 : 1 sortie,"` est dans `llm.calls[0]`.
  - `test_generation_prompt_unchanged_without_stored_activities` (test_plans) : base sans activité → `"Historique long" not in llm.calls[0]`.
  - `test_adjustment_prompt_has_long_history` (test_adjust) : même idée sur le prompt d'ajustement, en suivant la mise en place des tests existants du fichier.
- [ ] **Step 2: Lancer** `pytest tests/services/test_plans.py tests/services/test_adjust.py -v` → les nouveaux tests échouent.
- [ ] **Step 3: Implémenter** `long_history` et les deux branchements.
- [ ] **Step 4: Lancer toute la suite** `pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(services): historique long lu en base pour les prompts`
