# Zones FC calculées par l'app (FC de réserve) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Les zones FC sont toujours calculées par l'app avec la FC de réserve (Karvonen), la FC repos étant la moyenne 7 jours de Garmin.

**Architecture:** `compute_zones` perd sa branche « zones Garmin » et ne garde que Karvonen. Le client Garmin lit `lastSevenDaysAvgRestingHeartRate` (repli : `restingHeartRate`) et ne remonte plus les seuils de zones. Tout le reste (web, export montre, analyse des tours) lit les zones de l'instantané, rafraîchi à chaque synchro par `refresh_snapshot`.

**Tech Stack:** Python 3, pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-zones-fc-reserve-design.md`

## Global Constraints

- Zones : Z1 = 50–60 %, Z2 = 60–70 %, Z3 = 70–80 %, Z4 = 80–90 %, Z5 = 90–100 % de (FC max − FC repos), + FC repos, arrondis avec `round` (formule Karvonen déjà présente dans `coach/analysis/zones.py`).
- `Zones.source` contient `"karvonen"` (plus jamais `"garmin_hr_zones"`).
- FC max inchangée : `maxHeartRateUsed` des réglages de zones Garmin, sinon `maxHeartRate` du jour.
- Messages d'erreur existants conservés : « FC max inconnue », « FC repos inconnue ».
- Lancer les tests avec `pytest` depuis la racine du worktree.

## Review Focus

1. Moyenne 7 jours absente (`null`) mais FC repos du jour présente → `hr_rest` = valeur du jour (test Task 2).
2. Moyenne 7 jours de forme inattendue (chaîne, liste) → ignorée, repli sur la valeur du jour, pas d'exception (test Task 2).
3. Réglages Garmin en méthode « % FC max » avec seuils de zones présents → les seuils sont ignorés, zones Karvonen (test Task 1 : plus de paramètre ; test Task 2 : `Metrics` n'a plus `hr_zones`).
4. FC repos totalement absente → `ValueError("FC repos inconnue")`, transformée en `CoachError` « synchronise ta montre » par `zones_from_metrics` (test existant `test_missing_hr_rest_raises` à ajouter en Task 1).
5. Workouts déjà envoyés sur la montre avant le changement : ils gardent les anciens bpm jusqu'à leur ré-export. Aucun code ; à signaler à l'utilisateur à la fin.

---

### Task 1: `compute_zones` toujours en Karvonen

**Files:**
- Modify: `coach/analysis/zones.py` (signature de `compute_zones`, suppression de la branche Garmin)
- Modify: `coach/services/context.py:19-25` (ne plus passer `garmin_hr_zones`)
- Test: `tests/analysis/test_zones.py`
- Modify (appels à mettre à jour, retirer l'argument `garmin_hr_zones=...`) : `tests/api/test_app.py:421`, `tests/export/test_garmin_workout.py:12-18`, `tests/llm/test_prompts.py:15,18`, `tests/mobile_fixtures.py:104`, `tests/services/test_adjust.py:21`, `tests/services/test_garmin_export.py:25,329`, `tests/services/test_laps.py:158`

**Interfaces:**
- Produces: `compute_zones(*, threshold_pace_s_km: int | None, pred_10k_s: int | None, hr_max: int | None, hr_rest: int | None) -> Zones`

- [ ] **Step 1: Réécrire les tests FC de `tests/analysis/test_zones.py`**

Supprimer `garmin_hr_zones=` de tous les appels. Remplacer les assertions FC de `test_pace_zones_from_threshold` et supprimer `test_garmin_zones_without_hr_max_raises`. Ajouter :

```python
def test_hr_zones_are_karvonen():
    z = compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=50)
    assert z.hr == {"Z1": (120, 134), "Z2": (134, 148), "Z3": (148, 162), "Z4": (162, 176), "Z5": (176, 190)}
    assert z.source == ["lactate_threshold", "karvonen"]


def test_realistic_running_z1():
    # cas réel : FC max 182, repos 49 → Z1 plus à 91–109
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=None, hr_max=182, hr_rest=49)
    assert z.hr["Z1"] == (116, 129) and z.hr["Z2"] == (129, 142)


def test_missing_hr_rest_raises():
    with pytest.raises(ValueError, match="FC repos inconnue"):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=None)
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/analysis/test_zones.py -v`
Expected: FAIL (`TypeError: missing ... 'garmin_hr_zones'`)

- [ ] **Step 3: Retirer le paramètre `garmin_hr_zones` et la branche Garmin de `compute_zones`**

Garder l'ordre des contrôles : « FC max inconnue » avant « FC repos inconnue ». Mettre à jour la docstring (« repli sur la prédiction 10 km ; FC par Karvonen »). Dans `coach/services/context.py`, retirer `garmin_hr_zones=m.hr_zones`. Mettre à jour les appels de tests listés dans **Files** ; dans `tests/export/test_garmin_workout.py`, `ZONES` passe en Karvonen et les tests qui comparent à `ZONES.hr[...]` restent valides.

- [ ] **Step 4: Lancer toute la suite**

Run: `pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/analysis/zones.py coach/services/context.py tests
git commit -m "feat(zones): zones FC toujours calculées par FC de réserve"
```

### Task 2: FC repos moyenne 7 jours, plus de seuils Garmin

**Files:**
- Modify: `coach/garmin/client.py:291-314` (`metrics`)
- Modify: `coach/garmin/port.py:35` (supprimer `hr_zones` de `Metrics`)
- Test: `tests/garmin/test_client.py`

**Interfaces:**
- Consumes: `compute_zones` sans `garmin_hr_zones` (Task 1) — plus aucun lecteur de `Metrics.hr_zones`.
- Produces: `Metrics.hr_rest` = `lastSevenDaysAvgRestingHeartRate`, sinon `restingHeartRate`.

- [ ] **Step 1: Adapter les tests de `tests/garmin/test_client.py`**

- `FIXTURE_EXPECTED_REST = 49` (la fixture `heart_rates.json` a `lastSevenDaysAvgRestingHeartRate: 49`, `restingHeartRate: 48`).
- `test_metrics_parsing_from_fixtures` : remplacer `assert m.hr_zones == [...]` par `assert not hasattr(m, "hr_zones")`.
- `test_metrics_tolerates_odd_shapes` : remplacer `m.hr_zones is None` par `m.hr_rest is None`.
- Ajouter :

```python
def test_hr_rest_falls_back_to_daily_value():
    lib = full_lib()
    lib.responses["get_heart_rates"] = {"restingHeartRate": 48, "lastSevenDaysAvgRestingHeartRate": None}
    assert GarminClient(lib).metrics().hr_rest == 48


def test_hr_rest_ignores_odd_seven_day_average():
    lib = full_lib()
    lib.responses["get_heart_rates"] = {"restingHeartRate": 48, "lastSevenDaysAvgRestingHeartRate": "x"}
    assert GarminClient(lib).metrics().hr_rest == 48
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/garmin/test_client.py -v`
Expected: FAIL (`hr_rest == 48 != 49`, `hasattr` vrai)

- [ ] **Step 3: Implémenter dans `GarminClient.metrics`**

`hr_rest=_int(hr.get("lastSevenDaysAvgRestingHeartRate")) or _int(hr.get("restingHeartRate"))`, avec un commentaire « moyenne 7 jours : zones stables d'un jour à l'autre ». Supprimer `floors` et `hr_zones=` ; garder `_running_zones` (sert encore à `maxHeartRateUsed`). Supprimer le champ `hr_zones` de `Metrics` dans `coach/garmin/port.py`.

- [ ] **Step 4: Lancer toute la suite**

Run: `pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach/garmin/client.py coach/garmin/port.py tests/garmin/test_client.py
git commit -m "feat(garmin): FC repos moyenne 7 jours, seuils de zones Garmin ignorés"
```
