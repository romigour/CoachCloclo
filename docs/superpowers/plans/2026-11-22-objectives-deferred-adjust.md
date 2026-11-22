# Mise à jour de l'entraînement à la demande — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** un changement d'objectif sur un plan validé n'appelle plus Claude. Il marque le cycle « à
mettre à jour », et un bandeau sur Objectifs et Ma semaine lance une seule demande d'ajustement
regroupant tous les changements en attente.

**Architecture :** deux colonnes sur `cycle` (`adjust_due`, `adjust_notes_json`). `_reshape` les
alimente au lieu d'appeler `ask_adjustment`. Toute demande d'ajustement (`ask_adjustment`) inclut les
notes en attente, toute proposition enregistrée (`save_proposal`) les efface, et une génération de plan
aussi. Côté front, le composant `AdjustBanner` appelle l'existant `POST /cycle/adjust`.

**Tech Stack :** Python 3 / FastAPI / SQLModel (pytest), Svelte 5 + TypeScript (vitest).

**Spec :** `docs/superpowers/specs/2026-11-22-objectives-deferred-adjust-design.md`

## Contraintes globales

- Libellé du bandeau : « Tes objectifs ont changé » et bouton « Mettre à jour l'entraînement ». Message
  d'attente : « Claude ajuste ton plan… (cela peut prendre une minute) » (texte déjà utilisé ailleurs).
- Le premier objectif, `next_cycle`, les cas `draft` et `regenerate`, les imprévus et `PATCH /cycle`
  gardent leur comportement.
- Ne jamais déclencher Claude depuis la synchro à cause du seul `adjust_due`.
- Si Claude échoue lors de la mise à jour, `adjust_due` et les notes restent intacts.
- Commentaires et messages en français, comme le reste du code.

## Points de vigilance

1. **Trois ajouts d'affilée** : trois notes dans l'ordre, aucun appel à Claude, puis un seul appel qui
   contient les trois notes (test dans la tâche 2).
2. **Échec de Claude au moment du bouton** : l'indicateur et les notes restent, le bandeau reste (test
   dans la tâche 1).
3. **Un ajout (adjust) suivi d'un changement `regenerate`** : l'indicateur est effacé, seul le bandeau
   « Générer » reste (test dans la tâche 2).
4. **Une synchro avec `adjust_due` mais sans activité nouvelle** : aucun appel à Claude, l'indicateur
   reste. Avec une proposition de synchro, les notes sont incluses puis effacées (test dans la tâche 1).
5. **Une proposition en attente au moment d'un changement d'objectif** : elle passe `stale` (test dans
   la tâche 2).

---

### Task 1: indicateur sur le cycle et sa consommation

**Fichiers :**
- Modifier : `coach/plan/models.py` (classe `Cycle`)
- Modifier : `coach/plan/repo.py` (`_migrate`)
- Modifier : `coach/services/adjust.py` (`ask_adjustment`, `save_proposal`)
- Modifier : `coach/services/plans.py` (génération, vers la ligne 135)
- Tests : `tests/plan/test_repo.py`, `tests/services/test_adjust.py`, `tests/services/test_plans.py`, `tests/services/test_sync.py`

**Interfaces produites :**
- `Cycle.adjust_due: bool = False`, `Cycle.adjust_notes_json: str = "[]"`
- `Cycle.adjust_notes(self) -> list[str]` (lecture du JSON)
- `add_adjust_note(c: Cycle, note: str) -> None` dans `coach/plan/models.py` : ajoute la note en fin de
  liste et passe `adjust_due` à vrai (sans `db.add`, c'est l'appelant qui le fait)
- `clear_adjust(c: Cycle) -> None` dans `coach/plan/models.py` : `adjust_due=False`, notes `"[]"`
- `save_proposal(db, adj)` efface l'indicateur du cycle actif (lu dans `db`) en plus de ce qu'il fait déjà

- [ ] **Étape 1 : écrire les tests qui échouent**

`tests/plan/test_repo.py::test_migration_adds_cycle_adjust_columns` : sur une base créée sans les deux
colonnes (`ALTER TABLE cycle DROP COLUMN …`, ou une table `cycle` minimale), `prepare_engine` les ajoute.
Un cycle existant lit `adjust_due is False` et `adjust_notes() == []`.

`tests/services/test_adjust.py` :
- `test_request_adjustment_includes_and_clears_pending_notes` : sur un cycle validé avec
  `add_adjust_note(c, "Note A")` puis `"Note B"`, `request_adjustment` envoie un prompt qui contient
  `"Note A"` puis `"Note B"`, dans cet ordre (`llm.calls[0]`). Ensuite `repo.active_cycle().adjust_due
  is False` et `adjust_notes() == []`.
- `test_request_adjustment_failure_keeps_pending_notes` : un `FakeLLMProvider(["{}", "{}"])` lève
  `LLMInvalidResponse`, l'indicateur reste vrai et les deux notes restent.

`tests/services/test_sync.py` :
- `test_sync_does_not_propose_for_pending_goal_change` : avec `adjust_due` vrai, sans activité nouvelle
  ni séance manquée, `llm.calls == []`, `proposal_id is None` et l'indicateur reste vrai.
- `test_sync_proposal_consumes_pending_notes` : avec une activité rattachée et une note en attente, le
  prompt contient la note et l'indicateur est effacé après la synchro.

`tests/services/test_plans.py::test_generate_clears_pending_adjust` : après `generate` sur un cycle
portant une note, `adjust_due is False` et les notes sont vides.

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `pytest tests/plan/test_repo.py tests/services/test_adjust.py tests/services/test_sync.py tests/services/test_plans.py -q`
Résultat attendu : ÉCHEC (attribut `adjust_due` absent, `add_adjust_note` introuvable).

- [ ] **Étape 3 : implémenter**

- Ajouter les deux champs, la méthode et les deux fonctions dans `coach/plan/models.py`.
- Dans `_migrate`, ajouter
  `_add_columns(conn, "cycle", {"adjust_due": "BOOLEAN NOT NULL DEFAULT 0", "adjust_notes_json": "VARCHAR NOT NULL DEFAULT '[]'"})`
  avec le commentaire « changements d'objectif en attente de mise à jour ». Pas de hausse de
  `SCHEMA_VERSION` : un ajout de colonne idempotent n'en demande pas (les migrations voisines n'en
  font pas non plus).
- `ask_adjustment` : `change_note = " ".join([*cycle.adjust_notes(), *([change_note] if change_note else [])]) or None`
  avant la construction du prompt.
- `save_proposal` : récupérer le cycle actif (`select(Cycle).where(Cycle.status == "active")`) et
  appeler `clear_adjust` s'il existe.
- Génération (`plans.py`, à côté de `c.needs_generation = False`) : `clear_adjust(c)`.

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `pytest tests/plan tests/services/test_adjust.py tests/services/test_sync.py tests/services/test_plans.py -q`
Résultat attendu : SUCCÈS.

- [ ] **Étape 5 : commit**

`git commit -m "feat(cycle): indicateur de mise à jour en attente, consommé par les ajustements"`

---

### Task 2: les changements d'objectif n'appellent plus Claude

**Fichiers :**
- Modifier : `coach/services/goals.py` (`ChangeResult`, `_reshape`, `add_goal`, `update_goal`, `remove_goal`)
- Modifier : `coach/api/app.py` (`_change_dict`, `_cycle_dict`, routes `/goals`)
- Tests : `tests/services/test_goals.py`, `tests/api/test_app.py`, et tout appelant trouvé par `grep -rn "add_goal(\|update_goal(\|remove_goal(" tests coach`

**Interfaces consommées :** `add_adjust_note`, `clear_adjust` (tâche 1).

**Interfaces produites :**
- `ChangeResult(proposal_id: int | None, needs_generation: bool, adjust_due: bool = False)`
- `add_goal(repo, garmin, data)`, `update_goal(repo, garmin, goal_id, data)`, `remove_goal(repo, garmin, goal_id)` :
  le paramètre `llm` disparaît, ainsi que dans `_reshape`.
- JSON : `_change_dict` renvoie aussi `"adjust_due"`, et `_cycle_dict` renvoie `"adjust_due": cycle.adjust_due`.

- [ ] **Étape 1 : réécrire les tests touchés et ajouter les nouveaux**

Dans `tests/services/test_goals.py`, retirer l'argument `FakeLLMProvider(...)` de tous les appels aux
trois fonctions. Supprimer `race_adjustment_json` s'il n'a plus d'utilisateur. Transformer les tests :
- `test_add_secondary_in_accepted_cycle_asks_adjustment` → `test_add_secondary_in_accepted_cycle_defers_adjustment` :
  `result == ChangeResult(proposal_id=None, needs_generation=False, adjust_due=True)`, `_proposals(repo) == []`.
  `repo.active_cycle().adjust_notes() == ["L'athlète a ajouté l'objectif Course sur route de 10 km du 20/12/2026 (Secondaire). " + NOTE_END]`.
  L'objectif est enregistré (`goals_in` contient les deux), 41 séances, `monday_garmin.calls == []`.
- `test_add_goal_close_to_principal_is_accepted` : n'affirme plus rien sur le prompt. Ajouter une
  vérification via `request_adjustment(repo, monday_garmin, llm)` : le prompt contient
  `"Course sur route de 10 km (31/01) est intégré à l'affûtage de Trail de 42 km (07/02)"`.
- `test_add_closer_principal_shrinks_cycle` : mêmes vérifications de retrait (semaines 13-14 en
  `pending_removal`, `schedules == {}`), plus `result.adjust_due is True` et `proposal_id is None`.
- `test_adjust_failure_saves_nothing` → `test_adjust_change_saved_without_claude` : les deux ajouts sont
  enregistrés (3 objectifs), l'ancienne proposition est `stale`, `adjust_notes()` a 2 entrées.
- `test_update_goal_llm_failure_changes_nothing` → supprimer : le chemin n'existe plus (le cas d'échec
  est couvert par la tâche 1).
- `test_remove_goal_in_cycle_asks_adjustment`, `test_update_goal_target_only`,
  `test_update_goal_target_without_previous`, `test_update_goal_earlier_date_removes_weeks`, etc. :
  remplacer les vérifications de `proposal_id` et du prompt par `adjust_due is True` et la note
  attendue dans `adjust_notes()` (même texte que la note actuelle).

Nouveaux tests :
- `test_three_adds_accumulate_one_adjustment` : trois `add_goal` (dates 2026-12-06, 2026-12-20,
  2027-01-10, priorité `plaisir`) → `adjust_notes()` a 3 entrées dans l'ordre et aucun appel LLM. Puis
  `request_adjustment` avec `FakeLLMProvider([<AdjustmentResponse vide>])` → `len(llm.calls) == 1`, les
  trois notes figurent dans le prompt et l'indicateur est effacé.
- `test_regenerate_after_pending_adjust_clears_flag` : un ajout `adjust`, puis un ajout lointain qui
  donne `regenerate` (objectif principal secondaire, comme `test_add_far_goal_without_principal_regenerates`)
  → `needs_generation is True`, `adjust_due is False`, `adjust_notes() == []`.
- `test_goal_change_makes_pending_proposal_stale` : une `Proposal` en attente passe `stale` après un
  ajout `adjust`.
- `test_close_clears_pending_adjust` : une note en attente, puis le retrait du dernier objectif → le
  cycle est `done`, avec `adjust_due is False`.

Dans `tests/api/test_app.py` : `POST /api/goals` sur un cycle validé renvoie `adjust_due: true` et
`proposal_id: null`, et `GET /api/status` expose `cycle.adjust_due`. Adapter les tests existants des
routes `/goals` qui injectaient une réponse LLM.

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `pytest tests/services/test_goals.py tests/api/test_app.py -q`
Résultat attendu : ÉCHEC (signature et `adjust_due`).

- [ ] **Étape 3 : implémenter**

Dans `_reshape`, pour `kind in ("adjust", "shrink")` :
- Garder le calcul de `removed_ids` (seulement si `new_end < cycle.end_date`, sinon ensemble vide) et
  `withdraw()`.
- Dans une transaction : `_active_in`, `write(db)`, `c.end_date = new_end`, `add_adjust_note(c, note)`,
  `_remove_sessions(db, removed_ids)`, puis `stale_pending(db)`.
- Après commit, `sync_marked(repo, garmin, to_clean, None)` si `to_clean` n'est pas vide.
- Renvoyer `ChangeResult(proposal_id=None, needs_generation=False, adjust_due=True)`.

Supprimer `refresh_snapshot`, `ask_adjustment`, l'id provisoire `NEW_GOAL_ID` et `_save_change` de ce
chemin. `_save_change` reste utilisé par `plans.update_plan_settings` : le garder, ou le déplacer dans
`plans.py` s'il n'a plus d'autre utilisateur. Pour `regenerate`, `draft` et `close` : `clear_adjust(c)`
dans la transaction existante. Retirer les imports devenus inutiles (`LLMProvider`, `NEW_GOAL_ID`,
`refresh_snapshot`), après vérification par grep. Dans `app.py`, les trois routes ne construisent plus
de `_LazyLLM`.

- [ ] **Étape 4 : lancer toute la suite Python**

Commande : `pytest -q`
Résultat attendu : SUCCÈS. `tests/services/test_season_scenario.py` et `test_race_strategy.py` appellent
aussi ces fonctions : les adapter de la même façon. Un scénario qui enchaînait un ajout puis une
proposition doit maintenant appeler `request_adjustment` explicitement.

- [ ] **Étape 5 : commit**

`git commit -m "feat(goals): un changement d'objectif marque le plan à mettre à jour au lieu d'appeler Claude"`

---

### Task 3: bandeau « Mettre à jour l'entraînement »

**Fichiers :**
- Créer : `web/src/components/AdjustBanner.svelte`, `web/src/components/AdjustBanner.test.ts`
- Modifier : `web/src/lib/api.ts` (type `Cycle`, type `PlanChange`)
- Modifier : `web/src/lib/turso/mappers.ts` (`cycleDict`), `web/src/lib/turso/__fixtures__/expected.json`
- Modifier : `web/src/routes/Goal.svelte`, `web/src/routes/Week.svelte`, `web/src/routes/Race.svelte`
- Tests : `web/src/routes/Goal.test.ts`, `web/src/routes/Week.test.ts`, `web/src/routes/Race.test.ts`

**Interfaces consommées :** `adjust_due` dans le cycle et dans `PlanChange` (tâche 2) ;
`api.requestAdjustment(): Promise<{ proposal_id: number }>` (déjà présent).

**Interfaces produites :**
- `Cycle.adjust_due: boolean` et `PlanChange.adjust_due?: boolean`
- `AdjustBanner` avec les props `{ cycle: Cycle | null; onproposal?: (id: number) => void }`

- [ ] **Étape 1 : écrire les tests qui échouent**

`AdjustBanner.test.ts` :
- Il affiche « Tes objectifs ont changé » et le bouton « Mettre à jour l'entraînement » quand
  `adjust_due && plan_accepted && !needs_generation`, et rien sinon (trois cas).
- Un clic appelle `POST /api/cycle/adjust`, affiche le message d'attente, puis appelle
  `onproposal(proposal_id)`.
- En cas d'erreur API, il affiche l'erreur (`ErrorBanner`) et le bouton reste disponible.
- Avec `READONLY` simulé (même méthode que les tests existants du mode mobile), il n'y a pas de bouton
  mais le texte « À faire depuis l'ordinateur ».

`Goal.test.ts` : après un ajout dont la réponse vaut `{ proposal_id: null, needs_generation: false, adjust_due: true }`,
l'URL ne change pas (`location.hash` n'est pas `#/proposal`), le statut est relu et le bandeau
s'affiche. Le message d'attente de l'ajout est « Ajout de l'objectif… », sans mention de Claude.

`Week.test.ts` : avec `plan.cycle.adjust_due = true`, le bandeau s'affiche, et le bouton mène à
`#/proposal`.

`Race.test.ts` : une modification qui renvoie `adjust_due: true` mène à `#/goal`.

- [ ] **Étape 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `cd web; npx vitest run`
Résultat attendu : ÉCHEC (composant absent).

- [ ] **Étape 3 : implémenter**

- Types : ajouter les champs dans `api.ts`. Dans `mappers.ts`, écrire `adjust_due: false` (le mobile ne
  s'en sert pas, et ne lit pas la colonne pour rester compatible avec une base distante pas encore
  migrée). Ajouter `"adjust_due": false` aux cycles de `expected.json`.
- `AdjustBanner.svelte` : une `section class="card row spread" aria-label="Plan à mettre à jour"` sur le
  modèle du bandeau « Plan à recalculer » de `Week.svelte`, avec un état `busy` et `ErrorBanner`.
- `Goal.svelte` : le placer sous le bandeau `needsGeneration`, avec `onproposal` qui appelle
  `onchanged?.()` puis `location.hash = "#/proposal"`. Retirer « (Claude peut ajuster ton plan) » des
  deux messages d'attente. `changed()` ne change pas : `proposal_id` est nul, la page recharge le cycle
  et le bandeau apparaît.
- `Week.svelte` : le placer juste après le bloc `stale`, avec `cycle={plan.cycle}` et
  `onproposal={goProposal}`.
- `Race.svelte`, dans `edited` : `else if (r.needs_generation || r.adjust_due) location.hash = "#/goal";`,
  et mettre à jour le commentaire.

- [ ] **Étape 4 : lancer les tests front et la vérification de types**

Commandes : `cd web; npx vitest run` puis `npm run check` (ou le script de vérification défini dans
`web/package.json`).
Résultat attendu : SUCCÈS, aucune erreur de type.

- [ ] **Étape 5 : commit**

`git commit -m "feat(web): bandeau « Mettre à jour l'entraînement » sur Objectifs et Ma semaine"`

---

### Task 4: documentation et vérification de bout en bout

**Fichiers :**
- Modifier : `README.md` et `docs/guide/index.html`, seulement là où ils décrivent ce qui se passe après
  l'ajout, la modification ou le retrait d'un objectif (chercher « objectif » près de « propos » /
  « ajust »). Les imprévus ne changent pas.

- [ ] **Étape 1 : mettre à jour les phrases concernées**

Écrire, en substance : le changement est enregistré tout de suite, un bandeau propose « Mettre à jour
l'entraînement » quand tu as fini, et Claude reçoit alors tous les changements d'un coup.

- [ ] **Étape 2 : vérifier dans l'appli**

Lancer l'appli (skill `run`). Sur un plan validé, ajouter deux objectifs dans le cycle : aucune attente
Claude, et le bandeau apparaît sur Objectifs puis sur Ma semaine. Recharger la page : le bandeau est
toujours là. Cliquer : une seule proposition, qui mentionne les deux objectifs.

- [ ] **Étape 3 : commit**

`git commit -m "docs: mise à jour de l'entraînement à la demande après un changement d'objectif"`
