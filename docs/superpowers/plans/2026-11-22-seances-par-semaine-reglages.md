# Séances par semaine dans les réglages du plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Changer le nombre de séances par semaine depuis « Réglages du plan », ce qui régénère la suite du plan dès la semaine en cours.

**Architecture:** `update_plan_settings` gagne une branche : si `sessions_per_week` change, les réglages sont enregistrés avec `needs_generation = True` puis `generate_plan` (existant) recalcule la suite ; sinon, ajustement inchangé. L'interface ajoute le choix 2–7 au dialogue et, après régénération, reste sur la page Objectifs (brouillon à valider).

**Tech Stack:** Python / FastAPI / SQLModel / pytest ; Svelte 5 / TypeScript / vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-11-22-seances-par-semaine-reglages-design.md`

## Global Constraints

- Bornes : `sessions_per_week` de 2 à 7 (`Field(None, ge=2, le=7)`), comme `GoalInput` / `NextCycleInput`.
- Effet dès la semaine courante : uniquement via `generate_plan` (séances non `todo` gardées et comptées).
- Nombre inchangé ou absent : comportement actuel strictement identique (proposition, « rien n'est enregistré si Claude échoue »).
- Échec de Claude pendant la régénération : réglages enregistrés, `needs_generation` reste `True`.
- Textes (français, exacts) :
  - avertissement : « Changer le nombre de séances recalcule la suite du plan à partir de cette semaine ; tu devras le valider à nouveau. »
  - attente : « Claude recalcule ton plan… (cela peut prendre une minute) »
  - légende du choix : « Séances par semaine »

## Review Focus

1. Nombre modifié **et** autres réglages dans la même requête → tout est enregistré, aucune proposition créée (test Task 1).
2. Nombre augmenté sans assez de jours possibles déjà cochés (cycle à 3 jours, passage à 4) → `GoalError` « au moins 4 jours possibles », Claude non appelé (test Task 1).
3. Échec de Claude → réglages gardés, plan « à recalculer », séances inchangées ; côté interface, fermer le dialogue recharge la page pour afficher le bandeau **Générer** (tests Task 1 et Task 2).
4. Propositions en attente au moment de la régénération → passées à `stale` (déjà fait par `generate_plan` via `stale_pending`) ; vérifié dans le test de régénération (Task 1).
5. Changer le nombre puis revenir à la valeur d'origine dans le dialogue → pas d'avertissement, bouton désactivé si rien d'autre n'a changé (test Task 2).

---

### Task 1: Serveur — régénération quand le nombre change

**Files:**
- Modify: `coach/services/plans.py` (`PlanSettingsUpdate`, `update_plan_settings`)
- Modify: `coach/api/app.py:725-728` (`patch_cycle`)
- Test: `tests/services/test_plans.py`, `tests/api/test_app.py`

**Interfaces:**
- Produces: `PlanSettingsUpdate.sessions_per_week: int | None = Field(None, ge=2, le=7)` ;
  `update_plan_settings(repo, garmin, llm, data) -> tuple[Cycle, int | None]` (id de proposition, `None` après régénération) ;
  `PATCH /api/cycle` → `{"cycle": ..., "proposal_id": int | None, "regenerated": bool}`.
- Consumes: `generate_plan(repo, garmin, llm)` (lit le cycle actif en base), `check_availability`, helper de test `_plan_from(first_week, per_week)` (`tests/services/test_plans.py:130`), fixture `_accepted_goal` (14 semaines, 3 séances, semaines 13–14 avec une séance exportée, aujourd'hui = semaine 1 avec `monday_garmin`).

- [ ] **Step 1: Écrire les tests de service qui échouent** (`tests/services/test_plans.py`)

```python
# plan valide à 4 séances : semaine 13 = 3 + 1 exportée, semaine 14 = 2 + 1 exportée + la course
_PLAN_4 = lambda: _plan_from(1, {**{w: 4 for w in range(1, 13)}, 13: 3, 14: 2})

def test_update_plan_settings_sessions_per_week_regenerates(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    with repo.transaction() as db:
        db.add(Proposal(analysis="x", changes_json="[]"))  # proposition en attente
    llm = FakeLLMProvider([_PLAN_4()])
    cycle, pid = update_plan_settings(
        repo, monday_garmin, llm, PlanSettingsUpdate(sessions_per_week=4, include_bike=True)
    )
    assert pid is None
    c = repo.active_cycle()
    assert (c.sessions_per_week, c.include_bike) == (4, True)
    assert not c.plan_accepted and not c.needs_generation
    assert cycle.sessions_per_week == 4
    assert "au plus 4 séances" in llm.calls[0]          # prompt de génération, pas d'ajustement
    assert all(status == "stale" for _, status in _proposals(repo))
    assert len([s for s in repo.sessions(c.id) if s.week_index == 1]) == 4

def test_update_plan_settings_sessions_per_week_keeps_settings_when_claude_fails(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    before = [(s.id, s.status) for s in repo.sessions(_cid(repo))]
    with pytest.raises(LLMInvalidResponse):
        update_plan_settings(repo, monday_garmin, FakeLLMProvider(["{}", "{}"]),
                             PlanSettingsUpdate(sessions_per_week=4))
    c = repo.active_cycle()
    assert c.sessions_per_week == 4 and c.needs_generation
    assert [(s.id, s.status) for s in repo.sessions(c.id)] == before

def test_update_plan_settings_sessions_per_week_rejections(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin, available_days=["mardi", "jeudi", "samedi"])
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="au moins 4 jours possibles"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(sessions_per_week=4))
    with pytest.raises(GoalError, match="Aucune modification"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(sessions_per_week=3))
    assert llm.calls == [] and repo.active_cycle().sessions_per_week == 3
```

Si le plan `_PLAN_4` est refusé par une règle existante (semaine allégée, course), ajuster les nombres par semaine du test, pas la validation.

- [ ] **Step 2: Lancer et constater l'échec**

Run: `pytest tests/services/test_plans.py -k sessions_per_week -v`
Expected: FAIL (`sessions_per_week` inconnu de `PlanSettingsUpdate` → champ ignoré / « Aucune modification »).

- [ ] **Step 3: Implémenter dans `coach/services/plans.py`**

- `PlanSettingsUpdate.sessions_per_week: int | None = Field(None, ge=2, le=7)` (importer `Field` de pydantic).
- Dans `update_plan_settings` : calculer `sessions_per_week` (nouvelle valeur si fournie et différente, sinon `cycle.sessions_per_week`) ; `check_availability(available_days, long_run_day, sessions_per_week)` ; « Aucune modification » si rien n'a changé.
- Nombre changé → transaction : recharger le cycle actif (`GoalError(_NO_PLAN)` s'il a disparu), appliquer `update` + `sessions_per_week` + `needs_generation = True` ; puis `generate_plan(repo, garmin, llm)` ; renvoyer `(repo.active_cycle(), None)`. Pas d'appel à `ask_adjustment`. Extraire cette branche dans une fonction privée `_regenerate_with(repo, garmin, llm, cycle_id: int, update: dict) -> Cycle`.
- Mettre à jour la docstring (les deux chemins) et l'annotation de retour `tuple[Cycle, int | None]`.

- [ ] **Step 4: Lancer les tests de service**

Run: `pytest tests/services/test_plans.py -v`
Expected: PASS (nouveaux et existants).

- [ ] **Step 5: Test API qui échoue** (`tests/api/test_app.py`)

```python
def test_patch_cycle_sessions_per_week_regenerates(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3), valid_plan_json(14, 4)]))
    _accepted_goal(client)
    r = client.patch("/api/cycle", json={"sessions_per_week": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["regenerated"] is True and body["proposal_id"] is None
    assert body["cycle"]["sessions_per_week"] == 4 and body["cycle"]["plan_accepted"] is False
    assert client.patch("/api/cycle", json={"sessions_per_week": 8}).status_code == 422
```

Et dans `test_patch_cycle_settings_asks_adjustment` : `assert body["regenerated"] is False`.
(Le plan généré par l'API n'a pas de séance exportée : `valid_plan_json(14, 4)` passe ; sinon ajuster comme au Step 1.)

- [ ] **Step 6: Implémenter `patch_cycle`** — renvoyer `{"cycle": _cycle_dict(cycle), "proposal_id": proposal_id, "regenerated": proposal_id is None}`.

- [ ] **Step 7: Lancer toute la suite Python**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add coach/services/plans.py coach/api/app.py tests/services/test_plans.py tests/api/test_app.py
git commit -m "feat(plan): changer le nombre de séances par semaine régénère la suite du plan"
```

---

### Task 2: Interface — choix dans le dialogue et retour sur Objectifs

**Files:**
- Modify: `web/src/lib/api.ts:98-99,597` (`PlanSettingsInput`, `updatePlanSettings`)
- Modify: `web/src/components/PlanSettingsDialog.svelte`
- Modify: `web/src/routes/Goal.svelte` (`settingsSaved`, `onclose` du dialogue)
- Test: `web/src/components/PlanSettingsDialog.test.ts`, `web/src/routes/Goal.test.ts`, `web/src/lib/api.test.ts` si le type y est vérifié

**Interfaces:**
- Consumes: réponse `PATCH /api/cycle` de Task 1.
- Produces: `PlanSettingsInput.sessions_per_week?: number` ; `updatePlanSettings` → `{ cycle: Cycle; proposal_id: number | null; regenerated: boolean }` ;
  `PlanSettingsDialog` prop `onsaved?: (proposalId: number | null) => void` (`null` = plan régénéré).

- [ ] **Step 1: Tests du dialogue qui échouent** (`PlanSettingsDialog.test.ts`, cycle de test à 4 séances)

```ts
test("changer le nombre de séances avertit, l'envoie et passe null à onsaved après régénération", async () => {
  const f = mock(200, { cycle: { ...cycle, sessions_per_week: 5 }, proposal_id: null, regenerated: true });
  const onsaved = vi.fn();
  open({ onsaved });
  const warning = "Changer le nombre de séances recalcule la suite du plan à partir de cette semaine ; tu devras le valider à nouveau.";
  expect(screen.queryByText(warning)).toBeNull();
  await fireEvent.click(screen.getByRole("radio", { name: "5" }));
  expect(screen.getByText(warning)).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(null));
  expect(JSON.parse(patchCall(f)[1].body as string)).toEqual({ sessions_per_week: 5 });
});

test("revenir au nombre de départ retire l'avertissement et désactive Enregistrer", async () => {
  open();
  await fireEvent.click(screen.getByRole("radio", { name: "5" }));
  await fireEvent.click(screen.getByRole("radio", { name: "4" }));
  expect(screen.queryByText(/recalcule la suite du plan/)).toBeNull();
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
});

test("le nombre choisi fixe le minimum de jours", async () => {
  open();
  for (const d of ["Lundi", "Mardi"]) await fireEvent.click(screen.getByRole("checkbox", { name: d })); // 5 jours
  await fireEvent.click(screen.getByRole("radio", { name: "6" }));
  expect(screen.getByText("Coche au moins 6 jours")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
});
```

Le radio de départ (4) est coché : `expect(screen.getByRole("radio", { name: "4" })).toBeChecked()` dans le premier test.

- [ ] **Step 2: Lancer et constater l'échec**

Run: `cd web && npx vitest run src/components/PlanSettingsDialog.test.ts`
Expected: FAIL (aucun radio « 5 »).

- [ ] **Step 3: Implémenter**

- `api.ts` : champ et type de réponse ci-dessus.
- `PlanSettingsDialog.svelte` : `initialPerWeek` (instantané) et `perWeek = $state(...)` ; `perWeekChanged` dans `canSave` ; `availabilityValid(days, perWeek)` ; fieldset « Séances par semaine » en `.segmented` 2–7, copié de `GoalForm.svelte:144-155` (`name="settings-per-week"`), placé au-dessus d'`AvailabilityFields` ; avertissement (`<p class="hint">`) quand `perWeekChanged` ; `body.sessions_per_week` si changé ; texte d'attente « Claude recalcule ton plan… (cela peut prendre une minute) » si `perWeekChanged`, sinon le texte actuel ; `onsaved?.(r.proposal_id)`.

- [ ] **Step 4: Lancer les tests du dialogue**

Run: `cd web && npx vitest run src/components/PlanSettingsDialog.test.ts`
Expected: PASS (nouveaux et existants).

- [ ] **Step 5: Test de la page Objectifs qui échoue** (`Goal.test.ts`, à côté de « the plan settings button… »)

```ts
test("after a regeneration from the plan settings, the goals page reloads and shows the draft", async () => {
  location.hash = "#/goal";
  let regenerated = false;
  const cycle = mkCycle({ plan_accepted: true });
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      regenerated = true;
      return new Response(JSON.stringify({ cycle: { ...cycle, plan_accepted: false }, proposal_id: null, regenerated: true }), { status: 200 });
    }
    const c = regenerated ? { ...cycle, plan_accepted: false, sessions_per_week: 4 } : cycle;
    return new Response(JSON.stringify(mkPlan(mkGoal(), c)), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal, { onchanged: vi.fn() });
  await fireEvent.click(await screen.findByRole("button", { name: "Réglages du plan" }));
  const dialog = within(screen.getByRole("dialog", { name: "Réglages du plan" }));
  await fireEvent.click(dialog.getByRole("radio", { name: "4" }));
  await fireEvent.click(dialog.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByRole("button", { name: "Valider le plan" })).toBeVisible();
  expect(location.hash).toBe("#/goal");
  expect(screen.queryByRole("dialog")).toBeNull();
});
```

Ajuster `mkCycle`/`mkPlan` à leurs signatures réelles (le plan doit avoir des semaines avec séances pour que le brouillon s'affiche) ; le cycle de départ doit avoir `sessions_per_week` ≠ 4.

- [ ] **Step 6: Implémenter dans `Goal.svelte`**

- `settingsSaved(proposalId: number | null)` : fermer le dialogue, `onchanged?.()` ; si `proposalId != null` → `location.hash = "#/proposal"` (inchangé) ; sinon `await load()` (erreur → `error`).
- `onclose` du dialogue : fermer **et** `load().catch(() => {})` — après un échec de régénération, la page affiche le bandeau « plan à recalculer ».

- [ ] **Step 7: Lancer toute la suite web et le typage**

Run: `cd web && npx vitest run && npm run build`
Expected: tests PASS, build sans erreur.

- [ ] **Step 8: Commit**

```bash
git add web/src
git commit -m "feat(web): nombre de séances par semaine dans les réglages du plan"
```
