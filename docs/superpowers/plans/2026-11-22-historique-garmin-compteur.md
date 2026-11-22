# Compteur « Historique Garmin » — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Réglages > Données affiche le total réel d'activités en base et ce qu'a apporté le dernier import, au lieu du seul nombre d'ajouts (0 après une réimportation sans nouveauté).

**Architecture:** `/api/status` expose en plus `history.total` (compté en base) et `history.finished_at` (chaîne ISO telle que stockée). La lecture seule Turso (téléphone) produit le même contrat, ce que vérifient les fixtures partagées. Côté web, des fonctions de libellé pures alimentent `Setup.svelte`.

**Tech Stack:** Python / FastAPI / SQLModel (pytest), Svelte 5 + TypeScript (vitest).

**Spec:** `docs/superpowers/specs/2026-11-22-historique-garmin-compteur-design.md`

## Global Constraints

- Ne pas modifier la logique d'import (`coach/services/history.py` : pagination, verrou, reprise) ni le sens de `imported` (= ajouts du dernier import).
- `finished_at` est renvoyé exactement comme il est stocké (`HistoryState.model_dump(mode="json")["finished_at"]`), ou `null`.
- Le contrat de `Status.history` est identique côté serveur et côté lecture Turso (test `reads.test.ts` « status » + `tests/api/test_mobile_fixtures.py`).
- Textes en français, accords singulier/pluriel corrects (0 et 1 au singulier).

## Review Focus

- Réimportation sans nouveauté : `imported` = 0, mais `total` = nombre en base → le libellé montre le total (Task 1 : `test_status_history_total_after_empty_reimport`).
- Import jamais terminé (`finished_at` absent, état `idle` par défaut) → seulement « N activités », sans seconde partie (Task 2 : test `lastImport` renvoie `null`).
- Base cloud indisponible (branche dégradée de `/status` et `turso.status()` dégradé) → `total: 0`, `finished_at: null`, pas de plantage (Task 1 : test dégradé mis à jour).
- `appstate.history` ancien, sans `finished_at`, ou avec un `finished_at` non chaîne → lecture Turso renvoie `finished_at: null` (Task 1 : test `reads.test.ts`).
- 1 activité / 1 nouvelle → singulier (Task 2 : tests de libellés).

---

### Task 1: Contrat `history.total` + `history.finished_at` (serveur et lecture Turso)

**Files:**
- Modify: `coach/plan/repo.py` (à côté de `has_activities`, ~l. 313)
- Modify: `coach/api/app.py:584` (branche dégradée) et `coach/api/app.py:605-609`
- Modify: `web/src/lib/api.ts:199-203` (`HistoryState`)
- Modify: `web/src/lib/turso/reads.ts:99-123` (`idle`, `loadHistory`) et `status()` (~l. 148)
- Modify: `web/src/lib/turso/index.ts:55` (statut dégradé)
- Modify: `tests/mobile_fixtures.py:195` puis régénérer `web/src/lib/turso/__fixtures__/*`
- Modify (fixtures de tests web au nouveau type) : `web/src/App.test.ts`, `web/src/readonly.test.ts`, `web/src/lib/turso/index.test.ts:89`
- Test: `tests/plan/test_repo.py`, `tests/api/test_app.py`, `web/src/lib/turso/reads.test.ts`

**Interfaces:**
- Produces: `Repo.count_activities(self) -> int`
- Produces: `Status.history` = `{ status, imported: number, error: string | null, total: number, finished_at: string | null }` ; type TS `HistoryState` gagne `total: number; finished_at: string | null;`

- [ ] **Step 1: Écrire les tests Python qui échouent**

Dans `tests/plan/test_repo.py` :

```python
def test_count_activities(repo):
    assert repo.count_activities() == 0
    repo.add(Activity(garmin_activity_id=1, date=date(2026, 1, 1), type_key="running"))
    repo.add(Activity(garmin_activity_id=2, date=date(2026, 1, 2), type_key="running"))
    assert repo.count_activities() == 2
```

Dans `tests/api/test_app.py`, mettre à jour `test_status_has_activities_and_history` (l. 920) :
- premier appel : `body["history"] == {"status": "done", "imported": 0, "error": None, "total": 0, "finished_at": None}` (garder l'état initial que la fixture produit déjà) ;
- après `_add_activity` + `save_state(... error ...)` : `{"status": "error", "imported": 5, "error": "boum", "total": 1, "finished_at": None}`.

Ajouter :

```python
def test_status_history_total_after_empty_reimport(make_client, repo):
    client = make_client()
    _add_activity(repo, 1, "2026-01-01")
    _add_activity(repo, 2, "2026-01-02")
    save_state(repo, HistoryState(status="done", imported=0,
                                  finished_at=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)))
    h = client.get("/api/status").json()["history"]
    assert h["imported"] == 0
    assert h["total"] == 2
    assert h["finished_at"] == repo.get_state("history")["finished_at"]
```

Repérer le test de la branche dégradée de `/api/status` (base cloud indisponible, `storage` non nul ; `grep -n '"storage"' tests/api/test_app.py`) et y vérifier `history == {"status": "idle", "imported": 0, "error": None, "total": 0, "finished_at": None}`. S'il n'en existe pas, ne pas en créer : la parité TS (Step 6) couvre le dégradé côté téléphone.

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run pytest tests/plan/test_repo.py::test_count_activities tests/api/test_app.py -k "history or count_activities" -q`
Expected: FAIL (`AttributeError: count_activities`, puis clés `total` / `finished_at` absentes).

- [ ] **Step 3: Implémenter côté serveur**

- `Repo.count_activities() -> int` : `select(func.count()).select_from(Activity)` (même style d'ouverture de session que `has_activities`).
- `/status` normal : ajouter `"total": repo.count_activities()` et `"finished_at": history.model_dump(mode="json")["finished_at"]`.
- `/status` dégradé : ajouter `"total": 0, "finished_at": None`.

- [ ] **Step 4: Vérifier le succès Python**

Run: `uv run pytest tests/plan/test_repo.py tests/api/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Fixtures partagées**

Dans `tests/mobile_fixtures.py:195`, ajouter `"finished_at": "2026-11-10T08:00:00Z"` à l'état `history` de la fixture « active » (la fixture « between » reste sans `finished_at` et couvre l'absence). Puis :

Run: `uv run python -m tests.mobile_fixtures` puis `uv run pytest tests/api/test_mobile_fixtures.py -q`
Expected: PASS ; `expected.json` contient `"total"` et `"finished_at"` dans `status.history`.

- [ ] **Step 6: Test Turso qui échoue**

Run: `cd web; npx vitest run src/lib/turso/reads.test.ts`
Expected: FAIL sur « status » (clés `total` / `finished_at` manquantes).

Ajouter dans `reads.test.ts` un test : avec `loadFixtureDb("active")`, exécuter `UPDATE appstate SET value_json = '{"status":"done","imported":1,"error":null,"finished_at":12}' WHERE key = 'history'` (via l'API du `Db` utilisée dans `testing.ts`), puis `status(db, "2026-11-14")` → `history.finished_at === null` et `history.imported === 1`.

- [ ] **Step 7: Implémenter côté web**

- `HistoryState` : `total: number; finished_at: string | null;`.
- `reads.ts` : `idle()` renvoie `total: 0, finished_at: null` ; `loadHistory` lit `finished_at` (chaîne → gardée, absent/autre type → `null`, **sans** invalider le reste de l'état) ; `status()` remplit `total` par `SELECT COUNT(*) AS n FROM activity` (fusionné dans l'objet `history`).
- `index.ts:55` : `total: 0, finished_at: null`.
- Fixtures TS (`App.test.ts`, `readonly.test.ts`, `index.test.ts:89`) : ajouter `total` / `finished_at` aux objets `history` pour coller au type.

- [ ] **Step 8: Vérifier le succès web**

Run: `cd web; npx vitest run`
Expected: PASS (toute la suite).

- [ ] **Step 9: Commit**

```bash
git add coach/plan/repo.py coach/api/app.py tests/ web/src/lib web/src/App.test.ts web/src/readonly.test.ts
git commit -m "feat(api): statut de l'historique avec total en base et date du dernier import"
```

---

### Task 2: Libellés et affichage dans Réglages > Données

**Files:**
- Create: `web/src/lib/history.ts`
- Create: `web/src/lib/history.test.ts`
- Modify: `web/src/routes/Setup.svelte:254-263`

**Interfaces:**
- Consumes: `HistoryState` (Task 1), `formatDate(iso: string): string` de `web/src/lib/dates.ts` (« 20 novembre 2026 », attend `AAAA-MM-JJ`)
- Produces:
  - `activityCount(n: number): string` — « 0 activité », « 1 activité », « 777 activités »
  - `newCount(n: number): string` — « 0 nouvelle », « 1 nouvelle », « 3 nouvelles »
  - `lastImport(h: HistoryState): string | null` — `null` si `finished_at` nul, sinon `` `dernier import le ${formatDate(finished_at.slice(0, 10))}, ${newCount(h.imported)}` ``

- [ ] **Step 1: Écrire les tests qui échouent** (`web/src/lib/history.test.ts`)

```ts
expect(activityCount(0)).toBe("0 activité");
expect(activityCount(1)).toBe("1 activité");
expect(activityCount(777)).toBe("777 activités");
expect(newCount(1)).toBe("1 nouvelle");
expect(newCount(3)).toBe("3 nouvelles");
const base = { status: "done", imported: 0, error: null, total: 777 } as const;
expect(lastImport({ ...base, finished_at: null })).toBeNull();
expect(lastImport({ ...base, finished_at: "2026-11-20T10:00:00Z" }))
  .toBe("dernier import le 20 novembre 2026, 0 nouvelle");
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd web; npx vitest run src/lib/history.test.ts`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter `web/src/lib/history.ts`** (les trois fonctions ci-dessus)

- [ ] **Step 4: Vérifier le succès**

Run: `cd web; npx vitest run src/lib/history.test.ts`
Expected: PASS.

- [ ] **Step 5: Brancher `Setup.svelte`**

- `running` : `Import en cours… ({newCount(status.history.imported)})`.
- `error` : inchangé.
- sinon : `<p>{activityCount(status.history.total)}</p>` puis, si `lastImport(status.history)` n'est pas nul, un second `<p class="meta">` avec ce texte.

- [ ] **Step 6: Suite complète + contrôle visuel**

Run: `cd web; npx vitest run` → PASS ; `uv run pytest -q` → PASS.
Puis recharger l'appli (après rebuild du front si nécessaire) et vérifier dans Réglages > Données : « 777 activités » et la ligne du dernier import.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/history.ts web/src/lib/history.test.ts web/src/routes/Setup.svelte
git commit -m "fix(web): Historique Garmin affiche le total d'activités et le dernier import"
```
