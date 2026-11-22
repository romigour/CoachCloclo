# Mise à jour de l'entraînement à la demande après un changement d'objectif

## Intention

Aujourd'hui, avec un plan validé, chaque ajout, modification ou retrait d'objectif qui touche le cycle
(cas `adjust` et `shrink` de `classify_change`) appelle Claude aussitôt, dans la requête. Ajouter trois
objectifs d'affilée déclenche trois appels longs, alors que l'athlète n'a pas fini sa saisie. On veut
enregistrer les changements tout de suite et laisser l'athlète lancer **une seule** mise à jour quand il
a terminé.

## Objectifs

- Un changement d'objectif n'appelle plus Claude ; il est enregistré immédiatement.
- Un bandeau « Tes objectifs ont changé — Mettre à jour l'entraînement » reste affiché sur **Objectifs**
  et **Ma semaine** tant que la mise à jour n'a pas été lancée, y compris après fermeture de l'appli.
- Le bouton envoie à Claude, en une fois, la liste de tous les changements en attente.

## Hors périmètre

- Le premier objectif (création du cycle) et « Préparer le cycle suivant » génèrent toujours le plan
  aussitôt.
- Les cas `draft` et `regenerate` gardent leur bandeau « Générer » actuel.
- Les modifications des réglages du plan (`PATCH /cycle`) et les imprévus ne changent pas.

## À éviter

- Qu'une synchro Garmin lance Claude toute seule à cause d'un changement d'objectif en attente.
- Deux appels pour les mêmes changements (le bouton puis une proposition de synchro, ou l'inverse).
- Perdre un objectif parce que Claude échoue : désormais, l'objectif est enregistré quoi qu'il arrive.

## Approches envisagées

1. **Retenue** : deux colonnes sur `cycle`, `adjust_due` (booléen) et `adjust_notes_json` (liste des
   changements en attente). Il faut une petite migration via `_add_columns`.
2. Réutiliser `proposal_due` de l'état de synchro : écartée, la synchro suivante lancerait Claude toute
   seule et il n'y a aucun endroit où garder les changements.
3. Déduire l'écart en comparant les objectifs au plan : écartée, on ne saurait plus dire à Claude ce qui
   a changé, et la comparaison serait fragile.

## Conception

**Backend (`coach/services/goals.py`, `_reshape`)**
- Cas `adjust` : enregistrer l'objectif et la nouvelle fin du cycle, ajouter la note du changement à
  `adjust_notes_json`, passer `adjust_due` à vrai et périmer la proposition en attente (`stale_pending`).
  Plus d'appel à `refresh_snapshot` ni à `ask_adjustment`.
- Cas `shrink` : pareil, et en plus les séances au-delà de la nouvelle fin sont retirées tout de suite
  (`_removed_after`, `_remove_sessions`, `sync_marked`), sans Claude.
- `ChangeResult` gagne `adjust_due: bool` ; `proposal_id` reste nul pour les changements d'objectif.
- Cas `regenerate`, `draft` et `close` : remettre `adjust_due` à faux et vider les notes (la génération
  ou la clôture couvre tout).
- L'estimation du temps d'un nouvel objectif sans temps visé passe par l'ajustement : `ask_adjustment`
  estime déjà les objectifs `claude` sans temps (plus besoin de `NEW_GOAL_ID` sur ce chemin).

**Consommation des notes**
- `request_adjustment` (bouton, imprévus) et `_propose` (synchro) joignent les notes en attente à
  leur `change_note`, puis remettent `adjust_due` à faux et vident les notes dans la même transaction
  que la proposition. En cas d'échec de Claude, rien n'est effacé.
- `generate` (plans) remet aussi l'indicateur à zéro.
- La synchro ne déclenche **pas** de proposition du seul fait d'`adjust_due`.

**API** : `adjust_due` est exposé dans `_cycle_dict` (statut et plan), dans `ChangeResult` et dans le
type `Cycle` du front. Le bouton réutilise `POST /cycle/adjust`.

**Front**
- Un composant `AdjustBanner` (texte et bouton « Mettre à jour l'entraînement », message d'attente
  « Claude ajuste ton plan… ») est affiché sur `Goal.svelte` et `Week.svelte` quand
  `cycle.adjust_due && cycle.plan_accepted`. Au succès, on va sur `#/proposal`.
- Les messages « Claude peut ajuster ton plan » des actions d'objectif sont retirés ; après un
  changement, la page recharge le cycle et montre le bandeau.
- Le mode mobile (lecture seule, Turso) n'affiche pas le bouton ; la colonne est lue sans être utilisée.

## Laissé au constructeur

- Le libellé exact et le style du bandeau, en s'alignant sur les bandeaux existants.
- La mise à jour des tests existants qui supposent un appel à Claude (`tests/services/test_goals.py`,
  `Goal.test.ts`, etc.).
