# Précisions sur un objectif — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un champ texte libre « Précisions » (280 caractères max) sur chaque objectif, transmis à Claude à la génération et aux mises à jour du plan ; le modifier met à jour les semaines à venir.

**Architecture:** Nouvelle colonne `Goal.notes`, nettoyée et bornée par le service objectifs ; `update_goal` produit une note d'ajustement comme pour le temps visé ; les prompts ajoutent une phrase par objectif ; le web ajoute une zone de texte au formulaire de création, à la fenêtre de modification et l'affiche dans la liste des objectifs.

**Tech Stack:** Python 3 / SQLModel / FastAPI / pytest (`uv run pytest`) ; Svelte 5 / TypeScript / vitest (`npm test` dans `web/`).

**Spec:** `docs/superpowers/specs/2026-11-22-goal-notes-design.md`

## Global Constraints

- Limite : `NOTES_MAX = 280` caractères, comptés après nettoyage (espaces de début/fin retirés).
- Message d'erreur serveur exact : `Précisions trop longues (280 caractères maximum)`.
- Texte vide (après nettoyage) → `None` en base.
- Libellé UI : « Précisions » ; placeholder : « Trail enneigé, 400 marches à la fin, je vise un record ».
- Phrase de prompt exacte : `Précisions de l'athlète : « <texte> ».` (retours à la ligne remplacés par des espaces).
- Objectifs à l'horizon (`_horizon_line`) : pas de précisions.

## Review Focus

- Précisions contenant des retours à la ligne (zone de texte multi-lignes) → une seule ligne dans le prompt, la structure « une ligne par objectif » reste intacte. Test : Task 2.
- Texte de exactement 280 caractères accepté, 281 refusé, et 290 caractères dont 10 espaces autour accepté. Test : Task 1.
- PATCH avec des précisions identiques (à l'espace près) → pas de changement, donc « Aucune modification » si rien d'autre. Test : Task 1.
- Effacer des précisions (`notes: ""`) → `None` en base et note « précisions retirées ». Test : Task 1.
- Fenêtre de modification : ne rien toucher aux précisions → le champ `notes` n'est pas envoyé. Test : Task 3.

---

### Task 1: Données, service et API

**Files:**
- Modify: `coach/plan/models.py` (classe `Goal`)
- Modify: `coach/plan/repo.py` (`_migrate`)
- Modify: `coach/services/goals.py` (`GoalInput`, `GoalUpdate`, `_new_goal`, `add_goal`, `update_goal`)
- Modify: `coach/api/app.py` (`POST /goals`, `_goal_dict`)
- Test: `tests/plan/test_repo.py`, `tests/services/test_goals.py`, `tests/api/test_app.py`

**Interfaces:**
- Produces: `Goal.notes: str | None = None` ; `NOTES_MAX = 280` et `clean_notes(text: str | None) -> str | None` dans `coach/services/goals.py` ; `GoalInput.notes: str | None = None` ; `GoalUpdate.notes: str | None = None` ; champ `"notes"` dans `_goal_dict` ; champ de formulaire `notes` sur `POST /api/goals` ; clé `notes` dans le corps de `PATCH /api/goals/{id}`.

- [ ] **Step 1: Tests qui échouent**

`tests/plan/test_repo.py` — `test_migrate_adds_goal_notes` : reprend la base 0.5.0 de `test_migrate_adds_sport_and_include_bike_to_0_5_0_db`, ouvre le repo, vérifie que l'objectif 1 a `notes is None` ; une seconde ouverture ne lève rien (idempotence).

`tests/services/test_goals.py` :
```python
def test_clean_notes():
    assert clean_notes(None) is None
    assert clean_notes("   ") is None
    assert clean_notes("  neige  ") == "neige"
    assert clean_notes("x" * 280) == "x" * 280
    assert clean_notes(" " * 5 + "x" * 280 + " " * 5) == "x" * 280
    with pytest.raises(GoalError, match=r"Précisions trop longues \(280 caractères maximum\)"):
        clean_notes("x" * 281)

def test_add_goal_keeps_notes(repo, monday_garmin):  # via add_goal avec GoalInput(..., notes="  escaliers ")
    ...  # objectif enregistré : notes == "escaliers"

def test_update_goal_notes_first_time(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    _, result = update_goal(repo, monday_garmin, goal.id, GoalUpdate(notes="Neige, je vise un record"))
    assert _goals(repo)[0].notes == "Neige, je vise un record"
    assert result == ChangeResult(proposal_id=None, needs_generation=False, adjust_due=True)
    assert repo.active_cycle().adjust_notes() == [
        "L'athlète a modifié l'objectif Trail de 42 km du 07/02/2027 (Principal) : "
        "précisions « Neige, je vise un record », aucune auparavant. " + NOTE_END
    ]

def test_update_goal_notes_replaced(...):   # note contient 'précisions « B » au lieu de « A »'
def test_update_goal_notes_cleared(...):    # GoalUpdate(notes="") → notes None, note contient "précisions retirées"
def test_update_goal_same_notes_is_no_change(...):  # notes "A" puis GoalUpdate(notes=" A ") → GoalError "Aucune modification"
def test_update_goal_notes_too_long(...):   # GoalUpdate(notes="x" * 281) → GoalError, objectif inchangé
```

`tests/api/test_app.py` :
- `test_post_goal_with_notes` : `_create_goal(make_client(), notes="Escaliers")` → 200, `goal.notes == "Escaliers"`.
- `test_post_goal_notes_too_long` : `notes="x" * 281` → 422.
- `test_patch_goal_notes` : sur `_accepted_goal`, `PATCH {"notes": "Neige"}` → 200, `goal.notes == "Neige"`, `adjust_due is True`.

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/plan/test_repo.py tests/services/test_goals.py tests/api/test_app.py -k notes -v`
Expected: FAIL (`clean_notes` introuvable, champ `notes` inconnu).

- [ ] **Step 3: Implémenter**

- `Goal.notes: str | None = None` (à côté de `priority`).
- `_migrate` : `_add_columns(conn, "goal", {"notes": "VARCHAR"})`, avec un commentaire « précisions de l'objectif ».
- `clean_notes` : `strip()`, vide → `None`, `len > NOTES_MAX` → `GoalError` (message exact des contraintes globales).
- `add_goal` : `clean_notes(data.notes)` avant toute écriture ; `_new_goal` reçoit la valeur nettoyée.
- `update_goal` : si `data.notes is not None`, nettoyer ; si différent de `goal.notes`, `update["notes"] = cleaned` et note selon le cas — nouveau sans ancien : `précisions « X », aucune auparavant` ; remplacé : `précisions « X » au lieu de « Y »` ; effacé : `précisions retirées`. Mettre à jour la docstring.
- API : `notes: Annotated[str | None, Form()] = None` sur `POST /goals`, transmis à `GoalInput` ; `"notes": goal.notes` dans `_goal_dict`. La `GoalError` devient déjà un 422 (vérifier avec le test).

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `uv run pytest tests/plan tests/services tests/api -q`
Expected: PASS, aucune régression.

- [ ] **Step 5: Commit**

```bash
git add coach/plan/models.py coach/plan/repo.py coach/services/goals.py coach/api/app.py tests/plan/test_repo.py tests/services/test_goals.py tests/api/test_app.py
git commit -m "feat(goals): précisions en texte libre sur un objectif (280 caractères)"
```

---

### Task 2: Précisions dans les prompts

**Files:**
- Modify: `coach/llm/prompts.py` (`_single_goal_text`, `_goal_line`, `_horizon_line`)
- Test: `tests/llm/test_prompts.py`

**Interfaces:**
- Consumes: `Goal.notes` (Task 1). `make_goal(notes=...)` fonctionne tel quel (la factory passe les overrides au modèle).
- Produces: `_notes_text(goal: Goal) -> str` : `""` sans précisions, sinon `" Précisions de l'athlète : « … »."` (espace initial inclus, retours à la ligne `\r\n`/`\n` remplacés par une espace).

- [ ] **Step 1: Tests qui échouent**

```python
def test_single_goal_text_includes_notes():
    from coach.llm.prompts import _goals_text
    text = _goals_text([make_goal(target_time_s=6600, target_source="user", notes="Neige\npuis escaliers")], [])
    assert text.endswith("Temps visé : 1 h 50. Précisions de l'athlète : « Neige puis escaliers ».")

def test_goal_line_includes_notes():
    from coach.llm.prompts import _goal_line
    line = _goal_line(make_goal(priority="secondaire", notes="PR visé"))
    assert line.endswith(", priorité Secondaire. Précisions de l'athlète : « PR visé ».")
    assert "\n" not in line

def test_horizon_line_has_no_notes():  # objectif à l'horizon avec notes : "Précisions" absent du prompt de génération
def test_no_notes_prompt_unchanged():  # make_goal() sans notes : "Précisions" absent des prompts de génération et d'ajustement
```
Note : la ligne d'objectif actuelle ne finit pas par un point ; avec des précisions elle devient `…, priorité Secondaire. Précisions de l'athlète : « … ».` — sans précisions, elle reste inchangée (les tests existants `test_goal_line_exact_order_*` et `test_single_principal_prompt_unchanged` doivent passer sans modification).

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/llm/test_prompts.py -k notes -v`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

`_notes_text` comme décrit ; ajouté en fin de `_single_goal_text` ; dans `_goal_line`, ajouter `"." + _notes_text(goal)` seulement quand `goal.notes` est renseigné ; `_horizon_line` appelle `_goal_line` : lui faire ignorer les précisions (paramètre `with_notes: bool = True` sur `_goal_line`, `False` depuis `_horizon_line`).

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `uv run pytest tests/llm -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coach/llm/prompts.py tests/llm/test_prompts.py
git commit -m "feat(llm): les précisions d'un objectif sont transmises à Claude"
```

---

### Task 3: Interface web

**Files:**
- Modify: `web/src/lib/api.ts` (`Goal`, `GoalInput`, `GoalUpdate`, `createGoal`)
- Modify: `web/src/components/GoalForm.svelte`, `web/src/components/GoalEditDialog.svelte`, `web/src/routes/Goal.svelte` (liste « À venir »)
- Test: `web/src/lib/api.test.ts`, `web/src/components/GoalForm.test.ts`, `web/src/components/GoalEditDialog.test.ts`, `web/src/routes/Goal.test.ts`

**Interfaces:**
- Consumes: champ `notes` de l'API (Task 1).
- Produces: `Goal.notes: string | null` ; `GoalInput.notes?: string` ; `GoalUpdate.notes?: string` ; constante `NOTES_MAX = 280` exportée depuis `web/src/lib/goals.ts`.

- [ ] **Step 1: Tests qui échouent**

- `api.test.ts` : `createGoal({..., notes: "Neige"})` met `notes=Neige` dans le FormData ; sans `notes` (ou vide), le champ est absent.
- `GoalForm.test.ts` — `test("notes field has a 280 limit and is submitted trimmed")` : zone « Précisions » (`getByLabelText("Précisions")`) avec `maxlength="280"` et le placeholder exact ; saisir « Escaliers » affiche `9 / 280` ; la soumission envoie `notes: "Escaliers"` ; laissée vide, `notes` vaut `undefined`.
- `GoalEditDialog.test.ts` — `test("notes are prefilled and sent only when changed")` : goal avec `notes: "A"` → zone préremplie ; changer la date seule → corps sans `notes` ; remplacer par « B » → corps `{ notes: "B" }` ; vider la zone → corps `{ notes: "" }` et le bouton Enregistrer est actif.
- `Goal.test.ts` : un objectif à venir avec `notes: "Neige"` affiche « Neige » dans sa carte ; sans précisions, rien.

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd web && npm test -- GoalForm GoalEditDialog Goal.test api.test`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

- `api.ts` : types ; `createGoal` fait `if (g.notes) f.set("notes", g.notes)`.
- `GoalForm.svelte` : `<textarea>` étiqueté « Précisions », `maxlength={NOTES_MAX}`, placeholder exact, compteur `{notes.length} / {NOTES_MAX}` ; placé après le temps visé ; `notes: notes.trim() || undefined` dans `input`.
- `GoalEditDialog.svelte` : même zone, valeur initiale `goal.notes ?? ""` capturée par `untrack` ; `notesChanged = notes.trim() !== initialNotes` entre dans `canSave` ; `body.notes = notes.trim()` si changé.
- `Goal.svelte` : `{#if g.notes}<span class="meta notes">{g.notes}</span>{/if}` sous le temps visé dans la liste « À venir » (le texte peut contenir des retours à la ligne : `white-space: pre-line`).

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `cd web && npm test && npm run build`
Expected: tests PASS, build sans erreur.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): zone Précisions sur un objectif"
```

---

### Task 4: Guide et vérification finale

**Files:**
- Modify: `docs/guide/index.html` (section décrivant le formulaire d'objectif, si elle existe)

- [ ] **Step 1:** Chercher la description du formulaire d'objectif dans `docs/guide/index.html` (section Objectifs, autour de la capture `goals-close.jpg`) ; y ajouter une phrase sur « Précisions » (à quoi ça sert, 280 caractères, prise en compte par Claude, modification = mise à jour du plan). Pas de nouvelle capture.
- [ ] **Step 2:** Run: `uv run pytest -q` puis `cd web && npm test && npm run build`. Expected: tout PASS.
- [ ] **Step 3: Commit**

```bash
git add docs/guide/index.html
git commit -m "docs(guide): précisions sur un objectif"
```
