# FC repos fiable et renvoi des séances à la montre — plan de mise en œuvre

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** calculer la FC repos sur les seules nuits où la montre était portée (avec une saisie manuelle prioritaire), et renvoyer à la montre les séances à venir quand les zones FC bougent.

**Architecture :** un calcul pur (`coach/analysis/rest_hr.py`) choisit la FC repos parmi saisie / moyenne des nuits / dernière moyenne / valeur Garmin. Un service (`coach/services/rest_hr.py`) tient le cache des nuits et la saisie en `AppState`. `refresh_snapshot` s'en sert et enregistre la provenance. Un second service (`coach/services/rezone.py`) compare, pour chaque séance exportée à venir, les zones FC utilisées à l'envoi avec les zones courantes, et la remplace via `mark_for_cleanup` + `sync_marked`.

**Tech Stack :** Python 3 / FastAPI / SQLModel / pytest ; garminconnect ; Svelte 5 + Vitest.

**Spec :** `docs/superpowers/specs/2026-11-23-fc-repos-fiable-design.md`

## Global Constraints

- Fenêtre des nuits : **14 jours** (aujourd'hui compris) ; minimum **3 nuits** portées.
- Nuit portée : Garmin a une durée de sommeil > 0 **et** une FC repos pour ce jour.
- Priorité : `manual` > `nights` > `last_good` (dernier instantané de provenance `nights` uniquement) > `garmin` (comportement actuel : moyenne 7 j, puis jour, puis dernier instantané).
- Saisie manuelle : entier **30 à 100** bpm, ou vide ; stockée en base (`AppState`), jamais dans `settings.json`.
- Renvoi : séances `exported` avec `scheduled_date > aujourd'hui`, plus celles d'**aujourd'hui seulement si aucune activité n'est enregistrée aujourd'hui** ; jamais de séance passée, `done`, `missed` ou `sync_error`.
- Seuil de renvoi : au moins une borne de zone FC a bougé de **2 bpm ou plus** **et** le workout généré diffère. Séance sans zones retenues (exportée avant ce changement) : renvoyée une fois si son workout a une cible FC.
- Les stratégies de course ne sont jamais renvoyées.
- Une erreur Garmin pendant la lecture d'une nuit saute ce jour ; pendant un renvoi, laisse la séance en `sync_error` ; dans les deux cas la synchro réussit.
- Schéma : `SCHEMA_VERSION` passe à **3** (`coach/plan/repo.py`) et `KNOWN_SCHEMA` à **3** (`web/src/lib/turso/db.ts`).
- Texte utilisateur en français, avec accents.

## Review Focus

1. **Montre jamais portée la nuit, première synchro** : aucune nuit, aucun instantané `nights` → valeur Garmin actuelle, zones présentes, aucune erreur. Test : `test_refresh_snapshot_without_nights_falls_back_to_garmin` (Tâche 3).
2. **Vider la saisie juste après l'avoir utilisée** : le dernier instantané est `manual` ; le repli ne doit pas le reprendre. Test : `test_last_good_ignores_manual_snapshots` (Tâche 2) et `test_clear_manual_returns_to_auto` (Tâche 5).
3. **Saisie enregistrée avant toute synchro** (pas d'instantané) : la valeur est gardée, la réponse le dit, rien n'est renvoyé, pas d'erreur 500. Test : `test_put_rest_hr_without_snapshot` (Tâche 5).
4. **Séance du jour déjà courue mais pas rattachée** : jamais renvoyée. Test : `test_today_session_not_resent_when_activity_today` (Tâche 4).
5. **Garmin indisponible pendant le renvoi** : la synchro renvoie un résultat, la séance passe en `sync_error` avec ses anciens ids gardés pour nettoyage. Test : `test_resend_failure_leaves_sync_error` (Tâche 4).

---

### Tâche 1 : lecture d'une nuit côté Garmin

**Files :**
- Modify : `coach/garmin/port.py` (modèle `NightRest`, méthode du `Protocol`, fake)
- Modify : `coach/garmin/client.py` (méthode `night_rest`)
- Test : `tests/garmin/test_client.py`

**Interfaces :**
- Produces : `class NightRest(BaseModel): hr_rest: int | None = None; slept: bool = False` dans `coach/garmin/port.py` ; `GarminPort.night_rest(self, day: date) -> NightRest` ; `FakeGarminClient(..., nights: dict[date, NightRest] | None = None)` qui renvoie `nights.get(day, NightRest())` et lève `GarminUnavailable` si `"night_rest" in fail_on`.

- [ ] **Step 1 : tests qui échouent**

```python
def test_night_rest_worn_night():
    lib = FakeLib({"get_heart_rates": {"restingHeartRate": 46},
                   "get_sleep_data": {"dailySleepDTO": {"sleepTimeSeconds": 27000}}})
    assert GarminClient(lib).night_rest(date(2026, 11, 20)) == NightRest(hr_rest=46, slept=True)
    assert ("get_heart_rates", ("2026-11-20",), {}) in lib.seen

def test_night_rest_no_sleep():
    lib = FakeLib({"get_heart_rates": {"restingHeartRate": 58},
                   "get_sleep_data": {"dailySleepDTO": {"sleepTimeSeconds": None}}})
    assert GarminClient(lib).night_rest(date(2026, 11, 20)) == NightRest(hr_rest=58, slept=False)

def test_night_rest_missing_data():
    lib = FakeLib({"get_heart_rates": None, "get_sleep_data": None})
    assert GarminClient(lib).night_rest(date(2026, 11, 20)) == NightRest()
```

- [ ] **Step 2 :** `uv run pytest tests/garmin/test_client.py -k night_rest -v` → FAIL (`night_rest` absent).
- [ ] **Step 3 : implémenter `GarminClient.night_rest(day: date) -> NightRest`** avec `self._optional` sur `get_heart_rates(day.isoformat())` et `get_sleep_data(day.isoformat())` ; `slept = (_num(dailySleepDTO.sleepTimeSeconds) or 0) > 0`. Les autres erreurs Garmin remontent (l'appelant les gère). Ajouter le modèle, la méthode au `Protocol` et le fake (avec `night_calls: list[date]`, jours lus). `LockedGarmin` délègue déjà les lectures via `__getattr__`.
- [ ] **Step 4 :** relancer → PASS ; `uv run pytest tests/garmin tests/storage -q` → PASS.
- [ ] **Step 5 : commit** `feat(garmin): lecture de la FC repos et du sommeil d'une nuit`

---

### Tâche 2 : choix de la FC repos (calcul pur)

**Files :**
- Create : `coach/analysis/rest_hr.py`
- Modify : `coach/analysis/zones.py` (extraire `hr_zones`)
- Test : `tests/analysis/test_rest_hr.py`, `tests/analysis/test_zones.py`

**Interfaces :**
- Produces :
  - `WINDOW_DAYS = 14`, `MIN_NIGHTS = 3`
  - `class NightRecord(BaseModel): day: date; hr_rest: int | None; slept: bool`
  - `class RestHr(BaseModel): value: int | None; source: Literal["manual", "nights", "last_good", "garmin"]; nights: int | None = None`
  - `nights_average(records: list[NightRecord], today: date) -> tuple[int, int] | None` : (moyenne arrondie, nombre de nuits) sur `today - 13 … today`, nuits `slept` avec `hr_rest`, `None` sous `MIN_NIGHTS`.
  - `choose_rest_hr(*, manual: int | None, nights: tuple[int, int] | None, last_nights_value: int | None, garmin_value: int | None) -> RestHr`
  - Dans `zones.py` : `hr_zones(hr_max: int, hr_rest: int) -> dict[HrZoneName, tuple[int, int]]`, utilisé par `compute_zones` (comportement inchangé).

- [ ] **Step 1 : tests qui échouent**

```python
T = date(2026, 11, 23)
def n(days_ago, hr, slept=True): return NightRecord(day=T - timedelta(days=days_ago), hr_rest=hr, slept=slept)

def test_average_of_worn_nights_only():
    assert nights_average([n(0, 46), n(1, 48), n(2, 47), n(3, 60, slept=False)], T) == (47, 3)

def test_below_min_nights():
    assert nights_average([n(0, 46), n(1, 48)], T) is None

def test_window_is_14_days():
    assert nights_average([n(0, 46), n(1, 48), n(14, 40)], T) is None   # J-14 hors fenêtre
    assert nights_average([n(0, 46), n(1, 48), n(13, 40)], T) == (45, 3)

def test_night_without_hr_ignored():
    assert nights_average([n(0, 46), n(1, None), n(2, 48)], T) is None

def test_priority():
    assert choose_rest_hr(manual=44, nights=(47, 9), last_nights_value=48, garmin_value=55) == RestHr(value=44, source="manual")
    assert choose_rest_hr(manual=None, nights=(47, 9), last_nights_value=48, garmin_value=55) == RestHr(value=47, source="nights", nights=9)
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=48, garmin_value=55) == RestHr(value=48, source="last_good")
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=None, garmin_value=55) == RestHr(value=55, source="garmin")
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=None, garmin_value=None) == RestHr(value=None, source="garmin")
```

Dans `test_zones.py` : `test_hr_zones_matches_compute_zones` (`hr_zones(182, 49)["Z2"] == (129, 142)`).

- [ ] **Step 2 :** `uv run pytest tests/analysis -q` → FAIL (module absent).
- [ ] **Step 3 :** implémenter `coach/analysis/rest_hr.py` et `hr_zones` (signatures ci-dessus).
- [ ] **Step 4 :** relancer → PASS.
- [ ] **Step 5 : commit** `feat(analysis): choix de la FC repos sur les nuits portées`

---

### Tâche 3 : schéma, cache des nuits, saisie, instantané

**Files :**
- Modify : `coach/plan/models.py` (`AthleteSnapshot.hr_rest_source: str | None = None`, `AthleteSnapshot.hr_rest_nights: int | None = None`, `Session.export_hr_zones_json: str | None = None`)
- Modify : `coach/plan/repo.py` (`_add_columns` pour ces 3 colonnes, `SCHEMA_VERSION = 3  # 3 : provenance de la FC repos, zones FC à l'envoi`, `latest_nights_snapshot()`, `has_activity_on(day)`)
- Modify : `web/src/lib/turso/db.ts` (`KNOWN_SCHEMA = 3` et son commentaire)
- Create : `coach/services/rest_hr.py`
- Modify : `coach/services/context.py` (`refresh_snapshot`)
- Test : `tests/services/test_rest_hr.py`, `tests/plan/` (migration), tests existants de `refresh_snapshot` (`tests/services/test_plans.py`, `test_sync.py`)

**Interfaces :**
- Consumes : `NightRest`, `GarminPort.night_rest` (Tâche 1) ; `NightRecord`, `RestHr`, `nights_average`, `choose_rest_hr`, `WINDOW_DAYS` (Tâche 2).
- Produces (dans `coach/services/rest_hr.py`) :
  - `NIGHTS_KEY = "rest_nights"` (AppState : `{"YYYY-MM-DD": {"hr_rest": int | None, "slept": bool}}`), `MANUAL_KEY = "rest_hr_manual"` (AppState : `{"value": int | None}`)
  - `load_manual(repo: Repo) -> int | None`, `save_manual(repo: Repo, value: int | None) -> None`
  - `cached_nights(repo: Repo) -> list[NightRecord]`
  - `refresh_nights(repo: Repo, garmin: GarminPort) -> list[NightRecord]` : lit les jours de la fenêtre absents du cache, plus aujourd'hui et hier toujours ; un jour en `GarminUnavailable`/`GarminRateLimited` est sauté (non mis en cache) ; `GarminAuthRequired` remonte ; le cache ne garde que la fenêtre.
  - `resolve_rest_hr(repo: Repo, nights: list[NightRecord], today: date, garmin_value: int | None) -> RestHr`
  - Repo : `latest_nights_snapshot() -> AthleteSnapshot | None` (dernier instantané `hr_rest_source == "nights"`), `has_activity_on(day: date) -> bool`.
- `refresh_snapshot` garde sa signature ; il remplace son repli actuel par : `nights = refresh_nights(...)`, `rest = resolve_rest_hr(repo, nights, garmin.today(), m.hr_rest)` ; si `rest.value is None`, repli sur `repo.latest_snapshot().hr_rest` (comportement actuel, source `garmin`) ; enregistre `hr_rest`, `hr_rest_source`, `hr_rest_nights`.

- [ ] **Step 1 : tests qui échouent** (`FakeGarminClient(today=date(2026, 11, 23), nights=..., metrics=Metrics(hr_max=182, hr_rest=55, ...))`)

```python
def test_refresh_snapshot_uses_worn_nights(repo):
    snap, zones = refresh_snapshot(repo, fake(nights={T: NightRest(hr_rest=46, slept=True), T-1: NightRest(hr_rest=48, slept=True),
                                                      T-2: NightRest(hr_rest=47, slept=True), T-3: NightRest(hr_rest=62)}))
    assert (snap.hr_rest, snap.hr_rest_source, snap.hr_rest_nights) == (47, "nights", 3)
    assert zones.hr["Z2"] == hr_zones(182, 47)["Z2"]

def test_manual_wins(repo):
    save_manual(repo, 44)
    snap, _ = refresh_snapshot(repo, fake(nights=three_worn_nights))
    assert (snap.hr_rest, snap.hr_rest_source) == (44, "manual")

def test_refresh_snapshot_without_nights_falls_back_to_garmin(repo):
    snap, zones = refresh_snapshot(repo, fake(nights={}))
    assert (snap.hr_rest, snap.hr_rest_source) == (55, "garmin") and zones.hr

def test_last_good_after_nights_snapshot(repo):
    refresh_snapshot(repo, fake(nights=three_worn_nights))         # 47, nights
    repo.set_state(NIGHTS_KEY, {})                                  # plus de nuits en cache
    snap, _ = refresh_snapshot(repo, fake(nights={}))
    assert (snap.hr_rest, snap.hr_rest_source) == (47, "last_good")

def test_last_good_ignores_manual_snapshots(repo):
    save_manual(repo, 44); refresh_snapshot(repo, fake(nights={}))
    save_manual(repo, None)
    snap, _ = refresh_snapshot(repo, fake(nights={}))
    assert (snap.hr_rest, snap.hr_rest_source) == (55, "garmin")

def test_nights_cached_then_only_today_and_yesterday_reread(repo):
    g = fake(nights=three_worn_nights); refresh_nights(repo, g)
    g.night_calls.clear(); refresh_nights(repo, g)
    assert sorted(g.night_calls) == [T - timedelta(days=1), T]

def test_night_error_skips_day(repo):
    g = fake(nights=three_worn_nights, fail_on={"night_rest"})
    assert refresh_nights(repo, g) == [] and cached_nights(repo) == []
```

Test de migration : une base sans les 3 colonnes les reçoit, `schema_version == 3`.

- [ ] **Step 2 :** `uv run pytest tests/services/test_rest_hr.py tests/plan -q` → FAIL.
- [ ] **Step 3 :** implémenter modèles, migration, repo, service et `refresh_snapshot`.
- [ ] **Step 4 :** `uv run pytest -q` → PASS (adapter les tests existants qui vérifient le repli actuel de `refresh_snapshot`) ; `cd web && npm test -- turso` → PASS.
- [ ] **Step 5 : commit** `feat: FC repos sur les nuits portées, saisie manuelle et provenance`

---

### Tâche 4 : renvoi des séances quand les zones FC changent

**Files :**
- Create : `coach/services/rezone.py`
- Modify : `coach/services/garmin_export.py` (remplir `export_hr_zones_json` dans `export_session` et dans `_sync` à chaque upload)
- Modify : `coach/services/sync.py` (appel après `retry_pending_cleanup` ; `SyncResult.resent: int = 0`, `SyncResult.hr_rest: int | None = None`)
- Test : `tests/services/test_rezone.py`, `tests/services/test_garmin_export.py`, `tests/services/test_sync.py`

**Interfaces :**
- Consumes : `mark_for_cleanup`, `sync_marked`, `session_to_workout_json` (existants) ; `Repo.has_activity_on` (Tâche 3).
- Produces :
  - `RESEND_MIN_BPM = 2`
  - `needs_resend(session: Session, zones: Zones) -> bool` : `False` si le workout (`session_to_workout_json(session.to_spec(), zones, name=...)`) est identique avec `Zones(pace=zones.pace, hr=<zones retenues>, source=zones.source)` ; sinon `True` si `export_hr_zones_json` est `None` ou si un écart de borne ≥ `RESEND_MIN_BPM`. Une séance sans zones retenues est comparée à un workout sans cible FC : renvoyée seulement si le sien a une cible FC.
  - `class Rezone(BaseModel): resent: int; failed: list[int]`
  - `resend_for_zones(repo: Repo, garmin: GarminPort, zones: Zones, today: date) -> Rezone` : candidates = `exported` du cycle actif avec `scheduled_date > today`, ou `== today` si `not repo.has_activity_on(today)` ; filtre `needs_resend` ; une transaction `mark_for_cleanup(s, removal=False)` ; puis `sync_marked(repo, garmin, ids, zones)` ; `resent = len(ids) - len(failed)`.

- [ ] **Step 1 : tests qui échouent** (séance HR « EF 40 min Z2 » et séance allure, cycle actif, `today = 2026-11-23`)

```python
def test_export_stores_hr_zones(...):  # test_garmin_export.py
    export_session(repo, g, sid, T + 1)
    assert json.loads(repo.session(sid).export_hr_zones_json) == zones.model_dump()["hr"] (listes)

def test_resent_when_zone_moves_2_bpm(...):
    r = resend_for_zones(repo, g, zones_rest(47), T)   # exportée avec zones_rest(55)
    s = repo.session(sid)
    assert r == Rezone(resent=1, failed=[]) and s.status == "exported" and s.garmin_workout_id != old_workout
    assert old_workout not in g.workouts and json.loads(s.export_hr_zones_json)["Z2"] == list(hr_zones(182, 47)["Z2"])

def test_not_resent_below_threshold(...):      # 55 -> 54 : écart < 2 bpm
def test_pace_session_never_resent(...):
def test_past_and_done_sessions_untouched(...):
def test_today_session_resent_without_activity_today(...):
def test_today_session_not_resent_when_activity_today(...):   # Activity(date=T) en base
def test_legacy_export_without_zones_resent_once(...):        # export_hr_zones_json = None, cible FC
def test_resend_failure_leaves_sync_error(...):
    g.fail_on = {"upload_workout"}
    r = resend_for_zones(...)
    s = repo.session(sid)
    assert r.failed == [sid] and s.status == "sync_error" and s.pending_old_workout_id == old_workout

def test_sync_reports_resent(...):   # test_sync.py
    result = sync(repo, g, llm, now=...)
    assert (result.resent, result.hr_rest) == (1, 47)
```

- [ ] **Step 2 :** `uv run pytest tests/services/test_rezone.py tests/services/test_garmin_export.py tests/services/test_sync.py -q` → FAIL.
- [ ] **Step 3 :** implémenter `rezone.py`, l'enregistrement des zones à l'envoi et l'appel dans `sync` (après `store_summaries`, pour que l'activité du jour soit connue, et après `retry_pending_cleanup`) ; `hr_rest` du résultat = celui de l'instantané.
- [ ] **Step 4 :** `uv run pytest -q` → PASS.
- [ ] **Step 5 : commit** `feat: renvoi à la montre des séances quand les zones FC changent`

---

### Tâche 5 : API de la FC repos

**Files :**
- Modify : `coach/services/rest_hr.py` (`rest_hr_view`, `apply_manual`)
- Modify : `coach/api/app.py` (`GET /api/rest-hr`, `PUT /api/rest-hr`)
- Test : `tests/services/test_rest_hr.py`, `tests/api/test_app.py`

**Interfaces :**
- Consumes : Tâches 2 à 4.
- Produces :
  - `rest_hr_view(repo: Repo, today: date) -> dict` : `{"value", "source", "nights", "manual", "auto_value", "auto_nights"}` — `value/source/nights` du dernier instantané (`None` sans instantané) ; `auto_*` = `nights_average(cached_nights(repo), today)` (sans appel Garmin).
  - `apply_manual(repo: Repo, garmin: GarminPort, value: int | None) -> dict` : `save_manual` ; si un instantané existe, nouvel instantané daté `garmin.today()` qui reprend le dernier (`vo2max`, `hr_max`, `threshold_*`), FC repos = `resolve_rest_hr(repo, cached_nights(repo), today, <hr_rest Garmin inconnu → dernier instantané>)`, zones = anciennes zones avec `hr = hr_zones(hr_max, value)` ; puis `resend_for_zones`. Renvoie la vue + `"resent": int`, `"failed": list[int]`, `"applied": bool` (`False` sans instantané).
  - `PUT /api/rest-hr` corps `{"manual": int | None}` (`Field(None, ge=30, le=100)`), sous `garmin_lock(repo, holder, SYNC_TTL)` comme `/sync`.

- [ ] **Step 1 : tests qui échouent**

```python
def test_put_rest_hr_applies_and_resends(client, ...):
    r = client.put("/api/rest-hr", json={"manual": 44})
    assert r.status_code == 200 and r.json()["value"] == 44 and r.json()["source"] == "manual" and r.json()["resent"] == 1
    assert client.get("/api/zones").json()["hr"]["Z2"] == list(hr_zones(182, 44)["Z2"])

def test_put_rest_hr_out_of_range(client):
    assert client.put("/api/rest-hr", json={"manual": 29}).status_code == 422
    assert client.put("/api/rest-hr", json={"manual": 101}).status_code == 422

def test_put_rest_hr_without_snapshot(client):
    r = client.put("/api/rest-hr", json={"manual": 44})
    assert r.status_code == 200 and r.json()["applied"] is False and r.json()["manual"] == 44

def test_clear_manual_returns_to_auto(client, ...):  # nuits en cache : 47 sur 3 nuits
    client.put("/api/rest-hr", json={"manual": 44})
    r = client.put("/api/rest-hr", json={"manual": None})
    assert (r.json()["value"], r.json()["source"], r.json()["nights"]) == (47, "nights", 3)

def test_get_rest_hr_shows_auto_value_while_manual(client, ...):
    body = client.get("/api/rest-hr").json()
    assert (body["manual"], body["auto_value"], body["auto_nights"]) == (44, 47, 3)
```

- [ ] **Step 2 :** `uv run pytest tests/api/test_app.py -k rest_hr -q` → FAIL.
- [ ] **Step 3 :** implémenter.
- [ ] **Step 4 :** `uv run pytest -q` → PASS.
- [ ] **Step 5 : commit** `feat(api): lecture et saisie de la FC repos`

---

### Tâche 6 : interface web

**Files :**
- Modify : `web/src/lib/api.ts` (type `RestHrView`, `api.restHr()`, `api.saveRestHr(manual: number | null)`, type de retour de `api.sync` avec `resent` et `hr_rest`)
- Create : `web/src/components/RestHrSettings.svelte` + `RestHrSettings.test.ts`
- Modify : `web/src/routes/Setup.svelte` (dans la section « Données », avant `<StorageSettings />`)
- Modify : `web/src/App.svelte` (message après synchro)
- Test : `web/src/App.test.ts`

**Interfaces :**
- Consumes : `GET/PUT /api/rest-hr`, `POST /api/sync` (Tâches 4 et 5).
- Produces : `RestHrView = { value: number | null; source: "manual" | "nights" | "last_good" | "garmin" | null; nights: number | null; manual: number | null; auto_value: number | null; auto_nights: number | null }`.

Libellés (copie fixée) :
- Titre de ligne : « FC repos ».
- Provenance : `nights` → « {value} bpm, moyenne de {nights} nuits avec la montre » ; `manual` → « {value} bpm, saisie à la main » ; `last_good` → « {value} bpm, dernière moyenne des nuits (pas assez de nuits récentes) » ; `garmin` → « {value} bpm, valeur Garmin (porte ta montre la nuit pour plus de précision) ».
- Sous le champ, quand `manual` est rempli et `auto_value` connu : « Calcul automatique : {auto_value} bpm ({auto_nights} nuits) ».
- Champ numérique 30–100, vide = automatique ; bouton « Enregistrer ».
- Après enregistrement avec `resent > 0` : « {resent} séance(s) mise(s) à jour sur ta montre » ; `applied === false` : « Enregistrée : elle s'appliquera à la prochaine synchro ».
- Après synchro (App) avec `resent > 0` : message non bloquant « {resent} séance(s) mise(s) à jour sur ta montre (FC repos {hr_rest}) », effacé à la synchro suivante.

- [ ] **Step 1 : tests qui échouent** (`RestHrSettings.test.ts`) : affiche la provenance `nights` ; affiche la ligne « Calcul automatique » quand `manual` est rempli ; envoie `saveRestHr(44)` puis `saveRestHr(null)` quand le champ est vidé ; refuse 29 (bouton désactivé) ; affiche le message de renvoi. `App.test.ts` : message après synchro quand `resent: 2`, absent quand `resent: 0`. Composant absent en mode `READONLY`.
- [ ] **Step 2 :** `cd web && npm test -- RestHrSettings App` → FAIL.
- [ ] **Step 3 :** implémenter, sur le modèle de `DiagnosticSettings.svelte`.
- [ ] **Step 4 :** `cd web && npm test && npm run build` → PASS.
- [ ] **Step 5 : commit** `feat(web): réglage et affichage de la FC repos`

---

### Tâche 7 : guide et vérification d'ensemble

**Files :**
- Modify : `docs/guide/index.html` (si les zones FC ou la FC repos y sont décrites : nuits portées, saisie manuelle, renvoi automatique)

- [ ] **Step 1 :** `grep -n "FC repos\|zones" docs/guide/index.html` ; mettre à jour les passages concernés.
- [ ] **Step 2 :** `uv run pytest -q` et `cd web && npm test && npm run build` → tout PASS.
- [ ] **Step 3 : commit** `docs(guide): FC repos sur les nuits portées`
