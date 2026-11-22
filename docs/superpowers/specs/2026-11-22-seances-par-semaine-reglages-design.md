# Nombre de séances par semaine dans les réglages du plan

## Pourquoi

Dans **Réglages du plan** (page Objectifs), on peut changer les jours possibles, la sortie longue et le vélo d'un
plan validé, mais pas le nombre de séances par semaine : il faut recréer l'objectif. On veut pouvoir le changer
directement, avec effet **dès la semaine en cours**. (Le guide, `docs/guide/index.html`, le présente déjà comme
un réglage du plan.)

## Objectifs / hors champ

- Objectif : choisir de 2 à 7 séances par semaine dans `PlanSettingsDialog`, comme à la création.
- Hors champ : le réglage du cycle suivant (déjà possible), les semaines passées (jamais modifiées).
- Anti-objectif : perdre des séances faites, manquées ou exportées.

## Approches

- **A. Proposition d'ajustement** (circuit des autres réglages) : Claude ajoute ou retire des séances semaine par
  semaine. Écartée : proposition très longue (3 → 5 séances sur 10 semaines ≈ 20 ajouts), plan rapiécé plutôt que
  repensé, et validation à corriger (elle compte aujourd'hui les semaines passées).
- **B. Régénérer la suite du plan** — **choisie**. Le nouveau nombre est enregistré puis `generate_plan` recalcule
  le plan à partir de la semaine courante : séances non `todo` gardées et comptées dans leur semaine, `todo`
  remplacées. Plan cohérent avec la nouvelle structure, mécanisme existant et testé. Contrepartie acceptée : les
  `todo` ajustées sont remplacées et le plan repasse en brouillon à valider.

## Conception

**Serveur** (`coach/services/plans.py`, `coach/api/app.py`)
- `PlanSettingsUpdate.sessions_per_week: int | None = Field(None, ge=2, le=7)`.
- `update_plan_settings` : `check_availability` utilise le nombre après modification.
  - Nombre inchangé (ou absent) : comportement actuel (ajustement, proposition).
  - Nombre modifié : tous les champs modifiés (jours, sortie longue, vélo, nombre) sont enregistrés sur le cycle
    avec `needs_generation = True`, puis `generate_plan` est appelé. Pas d'ajustement ni de proposition.
    *(Mon choix)* : si Claude échoue, les réglages restent enregistrés et le plan reste « à recalculer » — la page
    Objectifs affiche déjà le bandeau avec le bouton **Générer**. Les autres réglages, eux, gardent le « rien
    n'est enregistré si Claude échoue ».
- `update_plan_settings` renvoie `proposal_id: int | None` (None après régénération) ; `PATCH /api/cycle` renvoie
  `{"cycle", "proposal_id", "regenerated": bool}`.

**Interface** (`web/src`)
- `PlanSettingsDialog` : choix 2 à 7 en boutons radio, comme `GoalForm` ; `availabilityValid` suit le nombre choisi.
  Si le nombre change, avertissement sous le choix : « Changer le nombre de séances recalcule la suite du plan à
  partir de cette semaine ; tu devras le valider à nouveau. » Message d'attente adapté (« Claude recalcule ton
  plan… »).
- `PlanSettingsInput` / `updatePlanSettings` : champ `sessions_per_week` et réponse `regenerated`.
- `Goal.svelte` : après régénération, rester sur la page Objectifs (rechargée → « Brouillon du plan » avec
  **Valider le plan**) au lieu d'aller sur `#/proposal`.

**Tests** : service (régénération déclenchée, champs enregistrés, `needs_generation` gardé si Claude échoue,
disponibilités vérifiées avec le nouveau nombre, chemin ajustement inchangé), API, dialogue (envoi du champ,
avertissement, navigation selon `regenerated`).

## Laissé au constructeur

Découpage du code (fonction privée pour la branche régénération), libellés exacts, emplacement du choix dans le
dialogue (au-dessus des jours, comme à la création).
