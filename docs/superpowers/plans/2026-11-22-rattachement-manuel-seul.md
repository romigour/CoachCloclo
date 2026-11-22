# Rattachement manuel uniquement — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La synchro ne rattache plus jamais d'activité ; les séances rattachées à la main sont transmises à Claude comme réalisées à la synchro suivante.

**Architecture:** `SyncState` (état clé `sync` en base) gagne `pending_done: list[int]`. Le rattachement manuel (`POST /activities/{id}/match`) y ajoute ou en retire des ids de séance ; `sync()` ne fait plus de rattachement, et passe ces séances à `ask_adjustment(done=…)` puis vide la liste.

**Tech Stack:** Python 3.13, FastAPI, SQLModel, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-rattachement-manuel-seul-design.md`

## Global Constraints

- Lancer les tests avec `uv run pytest` (ou `.venv/Scripts/python -m pytest` si `uv` est absent du PATH).
- Commentaires, docstrings et messages de commit en français, style du dépôt (`fix(sync): …`), terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Les rattachements passés (`match_source = "auto"`) ne sont ni modifiés ni migrés.
- Le mobile (`web/src/lib/turso`) n'est pas touché.

## Review Focus

- Rattacher puis détacher la même séance avant la synchro : elle ne doit pas partir chez Claude comme réalisée (Task 2, `test_manual_detach_removes_pending_done`).
- Rattacher une activité à une séance déjà « manquée » : la séance passe « réalisée » et part chez Claude (Task 2, `test_manual_match_of_missed_session_is_pending`).
- Déplacer une activité de la séance A vers la séance B : A sort de la liste, B y entre (Task 2, `test_manual_rematch_moves_pending_done`).
- Séance de `pending_done` supprimée ou repassée non réalisée entre-temps : la synchro l'ignore sans planter (Task 1, `test_sync_ignores_stale_pending_done`).
- Ancien état `sync` en base sans `pending_done` : se charge avec une liste vide (Task 1, `test_load_sync_state_without_pending_done`).

---

### Task 1: La synchro ne rattache plus et transmet `pending_done` à Claude

**Files:**
- Modify: `coach/services/sync.py`
- Test: `tests/services/test_sync.py`

**Interfaces:**
- Produces:
  - `SyncState.pending_done: list[int] = []`
  - `SyncResult` perd le champ `matched` (reste `new_activities`, `missed`, `proposal_id`).
  - `add_pending_done(repo: Repo, session_id: int) -> None` — ajoute sans doublon.
  - `remove_pending_done(repo: Repo, session_id: int) -> None` — retire si présent.

- [ ] **Step 1: Réécrire les tests de synchro**

Dans `tests/services/test_sync.py`, ajouter un helper qui simule un rattachement manuel :

```python
def _attach(repo, session_id, garmin_id=1):
    """Rattachement manuel tel que le fait l'API : activité reliée, séance réalisée, en attente d'analyse."""
    act = repo.activity_by_garmin_id(garmin_id)
    with repo.transaction() as db:
        a = db.get(Activity, act.id); a.session_id = session_id; a.match_source = "manual"; db.add(a)
        s = db.get(Session, session_id); s.status = "done"; db.add(s)
    add_pending_done(repo, session_id)
```

Nouveaux tests (assertions exactes) :

```python
def test_sync_never_attaches(repo, coach_home, fake_garmin, accepted_plan):
    r = sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.new_activities == 1 and r.proposal_id is None
    assert repo.activity_by_garmin_id(1).session_id is None
    assert not any(s.status == "done" for s in repo.sessions(accepted_plan.id))

def test_sync_sends_manually_attached_session_to_claude(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json(analysis="Tout va bien"), adjustment_json()])
    sync(repo, fake_garmin, llm, now=NOW)
    sid = repo.sessions(accepted_plan.id)[0].id
    _attach(repo, sid)
    r = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r.proposal_id == repo.pending_proposal().id
    assert len(llm.calls) == 1  # premier sync : rien à analyser
    assert load_sync_state(repo).pending_done == []

def test_sync_ignores_stale_pending_done(repo, coach_home, fake_garmin, accepted_plan):
    sid = repo.sessions(accepted_plan.id)[0].id
    add_pending_done(repo, sid)  # séance jamais passée « réalisée »
    add_pending_done(repo, 99999)  # séance inexistante
    sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert load_sync_state(repo).pending_done == []

def test_load_sync_state_without_pending_done(repo, coach_home):
    repo.set_state("sync", {"last_sync_at": None, "proposal_due": False})
    assert load_sync_state(repo).pending_done == []

def test_pending_done_kept_during_open_injury(repo, coach_home, fake_garmin, accepted_plan):
    # même mise en place d'arrêt que test_sync_skips_proposal_during_open_injury
    ...
    _attach(repo, sid)
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is None and load_sync_state(repo).pending_done == [sid]

def test_pending_done_cleared_when_cycle_closes(repo, coach_home, fake_garmin):
    # même mise en place que test_sync_closes_cycle_after_principal, avec une séance rattachée à la main
    ...
    assert load_sync_state(repo).pending_done == []
```

Les tests existants qui comptaient sur le rattachement automatique pour déclencher une proposition (`test_sync_matches_and_creates_proposal`, `test_new_proposal_makes_previous_stale`, `test_llm_failure_keeps_matching`, `test_llm_failure_keeps_previous_pending`, `test_no_proposal_before_plan_accepted`, `test_sync_fetches_laps_of_matched_activities`, `test_sync_survives_laps_error_and_retries_next_time`, `test_proposal_prompt_contains_step_detail`, `test_sync_skips_proposal_during_open_injury`, `test_deleting_open_injury_resumes_sync_proposals`, `test_race_day_activity_still_matched_before_close`, et ceux qui lisent `r.matched`) : remplacer le déclencheur par `_attach(...)` après le premier import, et retirer toute assertion sur `matched`. `test_race_day_activity_still_matched_before_close` devient : une séance du jour de course rattachée à la main est transmise avant la clôture. `test_llm_failure_keeps_matching` devient : en cas d'échec de Claude, `pending_done` est conservé. Dans `tests/api/test_app.py` (vers la ligne 420), la réponse attendue de `/api/sync` devient `{"new_activities": 0, "missed": 0, "proposal_id": None}`.

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run pytest tests/services/test_sync.py -q`
Expected: FAIL (`add_pending_done` introuvable, `pending_done` absent).

- [ ] **Step 3: Implémenter dans `coach/services/sync.py`**

- `SyncState.pending_done: list[int] = []`, `add_pending_done` / `remove_pending_done` (charger, modifier, `save_sync_state`).
- `sync()` : supprimer l'appel à `match_activities` et la boucle d'écriture des paires ; `missed_ids = mark_missed(sessions, cycle, today)` sur toutes les séances, écriture des « manquées » inchangée ; garder `fetch_missing_laps`.
- `done_ids` = ids de `settings.pending_done` dont la séance existe dans le cycle actif, a le statut `done` et une activité rattachée (`a.session_id == sid` parmi `repo.activities_since(...)` ou une requête directe) ; les autres ids sont abandonnés.
- `proposal_due = cycle is not None and (proposal_due or bool(done_ids or missed_ids))`.
- `_propose(..., done_ids, missed_ids, today)` : construit `done` en paires (séance, activité rattachée) ; après `save_proposal`, `pending_done = []`.
- Cycle clos (`close_passed` vrai) : `pending_done = []`. Arrêt en cours : `pending_done` conservé. Échec de Claude (exception) : rien n'est vidé (l'état est sauvegardé avant l'appel, comme aujourd'hui).
- Mettre la docstring du module et de `sync()` à jour (« Importe, marque les séances manquées… »).

- [ ] **Step 4: Vérifier le succès**

Run: `uv run pytest tests/services/test_sync.py tests/api/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/services/sync.py tests/services/test_sync.py tests/api/test_app.py
git commit -m "fix(sync): plus de rattachement automatique, les séances rattachées à la main partent chez Claude"
```

### Task 2: Le rattachement manuel alimente `pending_done`

**Files:**
- Modify: `coach/api/app.py:889-932` (`post_match`)
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: `add_pending_done(repo, session_id)`, `remove_pending_done(repo, session_id)`, `load_sync_state(repo)` de Task 1.

- [ ] **Step 1: Écrire les tests**

```python
def test_manual_match_marks_pending_done(make_client, repo):
    # mise en place comme test_manual_match
    client.post(f"/api/activities/{act.id}/match", json={"session_id": sid})
    assert load_sync_state(repo).pending_done == [sid]
    client.post(f"/api/activities/{act.id}/match", json={"session_id": sid})  # pas de doublon
    assert load_sync_state(repo).pending_done == [sid]

def test_manual_detach_removes_pending_done(make_client, repo):
    client.post(f"/api/activities/{act.id}/match", json={"session_id": sid})
    client.post(f"/api/activities/{act.id}/match", json={"session_id": None})
    assert load_sync_state(repo).pending_done == []

def test_manual_rematch_moves_pending_done(make_client, repo):
    client.post(f"/api/activities/{act.id}/match", json={"session_id": first})
    client.post(f"/api/activities/{act.id}/match", json={"session_id": second})
    assert load_sync_state(repo).pending_done == [second]

def test_manual_match_of_missed_session_is_pending(make_client, repo):
    # séance mise en status "missed" avant le rattachement
    client.post(f"/api/activities/{act.id}/match", json={"session_id": sid})
    assert repo.session(sid).status == "done" and load_sync_state(repo).pending_done == [sid]

def test_manual_match_on_sync_error_not_pending(make_client, repo):
    # séance en "sync_error" : reste en sync_error (règle existante), pas en attente d'analyse
    assert load_sync_state(repo).pending_done == []
```

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run pytest tests/api/test_app.py -k "pending" -q`
Expected: FAIL.

- [ ] **Step 3: Implémenter dans `post_match`**

Après la transaction : si la séance cible est passée `done`, `add_pending_done(repo, new.id)` ; si l'ancienne séance a été remise en `exported`/`todo` (plus d'activité), `remove_pending_done(repo, old_id)`. Mémoriser ces deux décisions dans des variables locales pendant la transaction.

- [ ] **Step 4: Vérifier le succès**

Run: `uv run pytest tests/api/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/api/app.py tests/api/test_app.py
git commit -m "feat(api): un rattachement manuel met la séance en attente d'analyse"
```

### Task 3: Suppression du code de rattachement automatique et guide

**Files:**
- Modify: `coach/analysis/compliance.py`
- Modify: `tests/analysis/test_compliance.py`
- Modify: `docs/guide/index.html:231,329`
- Modify: `README.md` (seulement s'il décrit un rattachement automatique)

- [ ] **Step 1: Supprimer le code mort**

Dans `compliance.py` : supprimer `match_activities`, `_expected_min`, `estimate_duration_min`, `_PACE_S_PER_KM`, `_DURATION_TOLERANCE`, et l'import de `RepeatSpec` s'il devient inutile. Garder `activity_types_for`, `mark_missed`, `_scheduled`, `_awaiting_cleanup`, `hard_session_warnings`. Docstring du module : « Séances manquées, avertissement 48 h, types d'activité par sport. » Dans `test_compliance.py` : supprimer les tests de `match_activities` et `estimate_duration_min` ; garder ceux de `mark_missed`, des avertissements et de `activity_types_for`. `test_sync_error_awaiting_cleanup_neither_matched_nor_missed` ne garde que l'assertion sur `mark_missed`.

- [ ] **Step 2: Mettre le guide à jour**

- Ligne 231 : « Les séances partent sur la montre, tu rattaches tes sorties et Claude les analyse. »
- Ligne 329 : « Rattache ta sortie à la séance prévue, <span>et Claude analyse ce que tu as fait à la synchro suivante.</span> »
- `grep -n -i "rattach" README.md` : corriger toute phrase qui annonce un rattachement automatique.

- [ ] **Step 3: Lancer toute la suite**

Run: `uv run pytest -q` puis `grep -rn "match_activities\|estimate_duration_min" coach tests`
Expected: tous les tests passent ; le grep ne renvoie rien.

- [ ] **Step 4: Commit**

```bash
git add coach/analysis/compliance.py tests/analysis/test_compliance.py docs/guide/index.html README.md
git commit -m "refactor(compliance): suppression du rattachement automatique ; guide à jour"
```
