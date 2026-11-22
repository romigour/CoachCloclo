# Détacher une activité — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** la carte d'une séance retrouve toujours son activité rattachée (même datée d'une autre semaine) et propose un bouton « Détacher » visible.

**Architecture :** `GET /api/activities?week=N` ajoute aux activités datées de la semaine celles rattachées à une séance de la semaine N du cycle actif. Côté web, la « Dernière activité » de `Week.svelte` filtre sur les dates de la semaine, et `SessionCard.svelte` remplace « Aucune » (caché dans « Corriger ») par un bouton « Détacher » à côté de « Corriger ». Le détachement réutilise `POST /api/activities/{id}/match` avec `session_id: null`, inchangé.

**Tech Stack :** FastAPI + SQLModel (pytest), Svelte 5 (vitest + Testing Library).

**Spec :** `docs/superpowers/specs/2026-11-22-detacher-activite-design.md`

## Global Constraints

- Libellé du bouton : exactement `Détacher`. Le bouton `Aucune` disparaît.
- Pas de confirmation au détachement.
- Aucun changement de `POST /activities/{id}/match`, ni du format des séances.
- Mobile en lecture seule (`READONLY`) : pas de bouton Détacher.

## Review Focus

- Activité rattachée **et** datée dans la semaine : elle ne doit apparaître qu'une fois dans `/activities?week=N` (test Task 1).
- Activité rattachée à une séance d'un **autre cycle** avec le même `week_index` : ne doit pas apparaître (test Task 1).
- Ordre : la réponse reste triée par date puis id, l'activité de la semaine précédente en tête (test Task 1).
- Semaine en cours dont la seule activité connue est la sortie de la semaine précédente rattachée : « Aucune activité cette semaine. » (test Task 2).
- Séance « réalisée » sans activité retrouvée (`matched` nul) : pas de bouton Détacher, « Corriger » reste (test Task 3).

---

### Task 1 : l'API semaine renvoie les activités rattachées à ses séances

**Files :**
- Modify : `coach/api/app.py:869-877` (`get_activities`)
- Test : `tests/api/test_app.py` (à côté de `test_activities_of_plan_week`, ligne 624)

**Interfaces :**
- Produces : `GET /api/activities?week=N` → liste de lignes `_activity_row`, triée par `(date, id)`, sans doublon, = activités datées lundi..dimanche de la semaine N ∪ activités dont `session_id` désigne une `Session` avec `cycle_id == cycle actif` et `week_index == N`.

- [ ] **Step 1 : écrire le test qui échoue** `test_activities_of_plan_week_include_matched_from_other_weeks`

Reprendre la mise en place de `test_activities_of_plan_week` (goal créé, `monday` = `plan_start`). Prendre une séance de la semaine 1 (`client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]`). Ajouter :
- `before` : `Activity(garmin_activity_id=21, date=monday - timedelta(days=1), type_key="running", session_id=<séance S1>)`
- `inside` : `Activity(garmin_activity_id=22, date=monday + timedelta(days=2), type_key="running", session_id=<séance S1>)`
- `other_cycle` : une `Session` ajoutée via `repo.add` avec `cycle_id=<id actif> + 999`, `week_index=1` (champs requis : `order`, `suggested_day`, `type`, `target_kind`, `title`, `description`, `steps_json="[]"`), et `Activity(garmin_activity_id=23, date=monday - timedelta(days=3), type_key="running", session_id=<cette séance>)`.

Assertions :
```python
ids = [r["id"] for r in client.get("/api/activities?week=1").json()]
assert ids == [before.id, inside.id]          # pas de doublon, triées, autre cycle exclu
assert [r["id"] for r in client.get("/api/activities?week=2").json()] == []
```

- [ ] **Step 2 : lancer le test, il échoue**

Run : `uv run pytest tests/api/test_app.py -k activities_of_plan_week -v`
Attendu : le nouveau test FAIL (`before.id` absent), `test_activities_of_plan_week` PASS.

- [ ] **Step 3 : implémenter dans `get_activities`**

Récupérer les ids des séances `repo.sessions(cycle.id, week)` (`coach/plan/repo.py:255`) ; ajouter à la liste datée les activités dont `session_id` est dans ces ids, en dédoublonnant par `id` puis en triant par `(date, id)`. Si aucune méthode du repo ne lit les activités par `session_id` en lot, ajouter `ActivityRepo.activities_of_sessions(ids: list[int]) -> list[Activity]` dans `coach/plan/repo.py`, sur le modèle de `activity_of_session` (ligne 330).

- [ ] **Step 4 : lancer les tests, ils passent**

Run : `uv run pytest tests/api/test_app.py -k activities -v`
Attendu : PASS.

- [ ] **Step 5 : commit**

```bash
git add coach/api/app.py coach/plan/repo.py tests/api/test_app.py
git commit -m "feat(api): la semaine renvoie aussi les activités rattachées à ses séances"
```

### Task 2 : « Dernière activité » ne garde que les activités datées de la semaine

**Files :**
- Modify : `web/src/routes/Week.svelte:75-77` (`lastActivity`)
- Test : `web/src/routes/Week.test.ts`

**Interfaces :**
- Consumes : Task 1 — `/api/activities?week=N` peut contenir des activités datées hors de la semaine.

- [ ] **Step 1 : écrire le test qui échoue** `la dernière activité ignore une sortie d'une autre semaine rattachée à une séance`

Stub `fetch` comme `mock()` mais `/api/activities` renvoie `[{ id: 9, date: "2026-10-25", type_key: "running", duration_s: 2580, distance_m: 10000, d_plus_m: 0, avg_hr: 162, session_id: 1, match_source: "auto" }]`. `render(Week, { today: "2026-10-30" })`.
```ts
const card = await screen.findByRole("region", { name: "Dernière activité" });
expect(await within(card).findByText("Aucune activité cette semaine.")).toBeVisible();
```

- [ ] **Step 2 : lancer le test, il échoue**

Run : `cd web; npx vitest run src/routes/Week.test.ts`
Attendu : le nouveau test FAIL (l'activité du 25/10 est affichée).

- [ ] **Step 3 : filtrer `lastActivity`**

Ne retenir que les activités avec `week.week_monday <= a.date <= dimanche` (dimanche = lundi + 6 jours, comparaison de chaînes ISO ; réutiliser un utilitaire de date de `web/src/lib` s'il en existe un pour ajouter des jours).

- [ ] **Step 4 : lancer les tests, ils passent**

Run : `cd web; npx vitest run src/routes/Week.test.ts`
Attendu : PASS.

- [ ] **Step 5 : commit**

```bash
git add web/src/routes/Week.svelte web/src/routes/Week.test.ts
git commit -m "fix(web): la dernière activité ne prend que les sorties de la semaine"
```

### Task 3 : bouton « Détacher » visible à la place de « Aucune »

**Files :**
- Modify : `web/src/components/SessionCard.svelte:177-190` (ligne activité + Corriger) et `:246-248` (bouton Aucune supprimé)
- Test : `web/src/components/SessionCard.test.ts`

**Interfaces :**
- Consumes : `rematch(activityId: number, sessionId: number | null)` existant dans `SessionCard.svelte` (ligne 120).

- [ ] **Step 1 : réécrire les tests**

Remplacer `test("Aucune unmatches the current activity", …)` par :
```ts
test("Détacher unmatches the current activity without opening Corriger", async () => {
  const calls = stubApi();
  const onchanged = vi.fn();
  render(SessionCard, { session, weekMonday: "2026-11-09", onchanged, activities: [act(1, "2026-11-10", 7)] });
  await fireEvent.click(screen.getByRole("button", { name: "Détacher" }));
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  expect(calls).toHaveLength(1);
  expect(calls[0].url).toBe("/api/activities/1/match");
  expect(JSON.parse(calls[0].body!)).toEqual({ session_id: null });
});

test("Corriger no longer offers Aucune", async () => {
  stubApi();
  render(SessionCard, { session, weekMonday: "2026-11-09", activities: [act(1, "2026-11-10", 7)] });
  await fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  await screen.findByRole("button", { name: /mar\. 10\/11/ });
  expect(screen.queryByRole("button", { name: "Aucune" })).toBeNull();
});

test("no Détacher without a found activity, nor read-only", async () => {
  stubApi();
  const { unmount } = render(SessionCard, { session, weekMonday: "2026-11-09" }); // réalisée, activité introuvable
  expect(screen.getByRole("button", { name: "Corriger" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Détacher" })).toBeNull();
  unmount();
  render(SessionCard, { session, weekMonday: "2026-11-09", activities: [act(1, "2026-11-10", 7)], readonly: true });
  expect(screen.queryByRole("button", { name: "Détacher" })).toBeNull();
});
```
Dans `an unmatched session can be linked by hand…` (ligne 62), remplacer la vérification `"Aucune"` par `"Détacher"`.

- [ ] **Step 2 : lancer les tests, ils échouent**

Run : `cd web; npx vitest run src/components/SessionCard.test.ts`
Attendu : FAIL sur les tests Détacher et « Corriger no longer offers Aucune ».

- [ ] **Step 3 : modifier `SessionCard.svelte`**

Dans la ligne `row spread` (non `READONLY`, non `readonly`), regrouper les boutons dans un `<span class="row tight">` : si `matched`, `<button class="small" onclick={() => rematch(matched.id, null)} disabled={busy}>Détacher</button>`, puis le bouton Corriger/Rattacher existant. Supprimer le bloc `{#if matched}…Aucune…{/if}` de la liste de correction.

- [ ] **Step 4 : lancer toute la suite web**

Run : `cd web; npm test`
Attendu : PASS.

- [ ] **Step 5 : commit**

```bash
git add web/src/components/SessionCard.svelte web/src/components/SessionCard.test.ts
git commit -m "feat(web): bouton Détacher visible à la place de Aucune"
```

### Vérification finale

- [ ] `uv run pytest` et `cd web; npm test` : tout passe.
