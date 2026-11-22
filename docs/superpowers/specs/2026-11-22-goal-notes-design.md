# Précisions sur un objectif — design

## Intention

Pouvoir ajouter à un objectif un court texte libre (« Précisions ») que Claude prend en compte pour construire
et faire évoluer le plan : type de terrain, escaliers, neige, envie de viser un record, etc. Le texte est
volontairement limité pour forcer la concision et garder un prompt léger.

## Objectifs / non-objectifs

- **Objectif** : un champ texte par objectif, saisi à la création, modifiable ensuite, transmis à Claude à la
  génération du plan et à chaque mise à jour hebdomadaire.
- **Objectif** : modifier les précisions une fois le plan lancé met à jour les semaines à venir, comme un
  changement de temps visé.
- **Non-objectif** : interpréter ou structurer le texte (pas d'extraction de « terrain », « D+ »…) ; Claude le
  lit tel quel.
- **Anti-objectif** : un texte long qui gonfle le prompt ; un texte reformulé qui ne dit plus ce que l'athlète a
  écrit.

## Contraintes

- Limite : **280 caractères**, contrôlée dans le formulaire (compteur visible, saisie bloquée au-delà) **et**
  côté serveur (refus au-delà).
- Plusieurs objectifs par cycle : les précisions restent rattachées à leur course dans le prompt.

## Approches envisagées

1. **Champ sur l'objectif, même circuit que le temps visé** — *retenue*. Saisie à la création, modification dans
   la fenêtre « Modifier l'objectif », note transmise à Claude et mise à jour du plan via le mécanisme existant
   (`update_goal` → `_reshape`).
2. Précisions dans les réglages du plan (un texte par cycle) — écartée : les informations concernent une course
   précise, et un cycle peut en compter plusieurs.
3. Reformulation du texte par Claude avant enregistrement — écartée : appel supplémentaire, risque de déformer
   le texte ; la limite de caractères suffit.

## Design

**Données** — `Goal.notes: str | None` (colonne `VARCHAR` ajoutée par `_add_columns` dans `_migrate`). Texte
nettoyé à l'enregistrement (espaces de début/fin retirés) ; vide → `None`.

**Service** (`coach/services/goals.py`)
- `GoalInput.notes: str | None` et `GoalUpdate.notes: str | None` (`None` = inchangé dans `GoalUpdate`, `""` =
  effacer). Au-delà de 280 caractères (après nettoyage) : `GoalError` « Précisions trop longues (280 caractères
  maximum) ». Constante `NOTES_MAX = 280`.
- `update_goal` : si les précisions changent, note pour Claude
  `précisions « <nouveau> » au lieu de « <ancien> »` (ou `, aucune auparavant` / `précisions retirées`), et le
  changement suit la classification existante (`adjust` si le plan est accepté, `draft` sinon).

**API** — champ `notes` en `Form()` sur `POST /goals`, dans le corps de `PATCH /goals/{id}`, et renvoyé par
`_goal_dict`.

**Prompt** (`coach/llm/prompts.py`) — quand un objectif a des précisions, une phrase
`Précisions de l'athlète : « … ».` est ajoutée :
- après le texte de `_single_goal_text` (objectif unique) ;
- en fin de ligne de `_goal_line` pour les objectifs du cycle (plusieurs objectifs).
Les retours à la ligne du texte sont remplacés par des espaces pour ne pas casser la mise en forme.
Utilisé à la génération et à la mise à jour hebdomadaire (les deux passent par `_goals_text`).

**Web**
- `GoalForm.svelte` : zone de texte « Précisions » (facultative), `maxlength=280`, compteur `n / 280`, exemple en
  placeholder (« Trail enneigé, 400 marches à la fin, je vise un record »).
- `GoalEditDialog.svelte` : même zone, préremplie ; envoyée seulement si elle a changé.
- Page de l'objectif (`Goal.svelte`) : les précisions sont affichées quand il y en a.

## Laissé au constructeur (mes choix, à corriger si besoin)

- Les objectifs « à l'horizon » (après le cycle, `_horizon_line`) n'affichent pas leurs précisions : ils ne sont
  là que pour situer le cycle, leurs précisions serviront quand leur propre cycle sera généré.
- Pas de contrôle sur le contenu du texte au-delà de la longueur.
- Mise à jour du guide utilisateur si une capture ou une section décrit le formulaire d'objectif.
