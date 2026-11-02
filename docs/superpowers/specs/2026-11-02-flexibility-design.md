# Souplesse du plan : disponibilités, imprévus et vélo

Date : 2026-11-02
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

Rendre le plan d'entraînement adaptable à la vie réelle de l'athlète, en trois volets :

1. **Disponibilités permanentes.** L'athlète indique les jours où il peut s'entraîner et,
   s'il le souhaite, le jour de sa sortie longue. Le plan ne place aucune séance ailleurs.
2. **Imprévus.** L'athlète déclare une indisponibilité (vacances, déplacement), une blessure
   ou une maladie (avec ou sans date de reprise), une semaine allégée, ou une fatigue / séance
   ratée. Claude propose aussitôt un ajustement, à valider comme après une synchronisation.
3. **Vélo.** À la création de l'objectif, une case « Inclure du vélo » autorise Claude à
   remplacer des séances faciles par du vélo d'endurance douce, exporté sur Garmin comme
   workout vélo et rattaché aux activités vélo.

### Critères de succès

- Un plan généré ou ajusté ne contient jamais de séance sur un jour non coché, ni pendant une
  indisponibilité ou un arrêt déclarés ; la sortie longue tombe sur le jour choisi quand il est
  libre.
- Déclarer un imprévu aboutit à une proposition d'ajustement en attente ; refuser la
  proposition laisse le plan inchangé, l'imprévu restant enregistré.
- Pendant un arrêt sans date de reprise, la synchronisation ne propose plus d'ajustement ;
  « Signaler la reprise » produit une proposition de reprise progressive.
- Avec « Inclure du vélo », les séances vélo sont uniquement de l'EF ou de la récup en FC
  Z1–Z2 ; exportées, elles apparaissent sur la montre comme workout vélo et se rattachent à
  l'activité vélo du jour.
- Les objectifs existants restent utilisables sans action de l'athlète (7 jours possibles,
  pas de jour de sortie longue, pas de vélo).

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Disponibilités réglables | Jours possibles et jour de sortie longue (pas de durée max par jour ni de jours déconseillés) |
| Portée des disponibilités | Par objectif, à la création et dans « Modifier l'objectif » |
| Types d'imprévus | Indisponibilité, blessure/maladie, semaine allégée, fatigue/séance ratée |
| Effet d'un imprévu | Proposition d'ajustement par Claude, à valider (jamais d'application directe) |
| Date de reprise d'un arrêt | Facultative ; « Signaler la reprise » la renseigne plus tard |
| Respect des contraintes | Envoyées à Claude dans le prompt **et** vérifiées par Python, une nouvelle tentative avec les erreurs |
| Vélo : demande | Simple case à cocher ; Claude décide combien (au plus une par semaine) et lesquelles |
| Vélo : contenu | Endurance douce seulement : type `EF` ou `récup`, cible FC, zones Z1–Z2 |
| Zones vélo | Zones de FC course, pas de zones vélo séparées |
| Export vers un jour non possible | Autorisé, avec avertissement non bloquant |
| Livraison | Trois lots utilisables séparément : disponibilités, imprévus, vélo |

## 3. Modèle de données

### 3.1 Objectif (`Goal`)

Nouveaux champs :

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `available_days_json` | liste de `Weekday` (JSON) | les 7 jours | Jours où une séance peut être placée |
| `long_run_day` | `Weekday` ou `None` | `None` | Jour imposé de la sortie longue |
| `include_bike` | booléen | `False` | Autorise les séances vélo |

Validation à la création et à la modification (erreur 422 avec message en français) :
- au moins un jour possible, et au moins autant de jours possibles que `sessions_per_week` ;
- `long_run_day`, s'il est renseigné, fait partie des jours possibles.

### 3.2 Imprévu (`Event`, nouvelle table)

| Champ | Type | Rôle |
|---|---|---|
| `id` | int | |
| `goal_id` | int, indexé | Objectif concerné |
| `created_at` | datetime UTC | |
| `kind` | `unavailable` \| `injury` \| `light_week` \| `fatigue` | |
| `start_date` | date | Début (inclus) |
| `end_date` | date ou `None` | Fin (incluse) ; `None` seulement pour `injury` |
| `max_sessions` | int ou `None` | `light_week` seulement, ≥ 0 |
| `days_json` | liste de `Weekday` ou `None` | `light_week` seulement : jours possibles cette semaine-là |
| `session_id` | int ou `None` | `fatigue` seulement : séance ratée |
| `note` | texte ou `None` | Précisions libres transmises à Claude |

Règles par type :

| Type | `start_date` | `end_date` | Autres |
|---|---|---|---|
| `unavailable` | obligatoire | obligatoire, ≥ début | — |
| `injury` | obligatoire | facultative, ≥ début | — |
| `light_week` | lundi d'une semaine du plan | dimanche de la même semaine | `max_sessions` obligatoire ; `days_json` facultatif, inclus dans les jours possibles de l'objectif |
| `fatigue` | aujourd'hui | aujourd'hui | `session_id` facultatif |

Un arrêt est **ouvert** tant que `kind = injury` et `end_date is None`. Il y a au plus un arrêt
ouvert par objectif. Un imprévu se supprime ; un arrêt ouvert se clôt en renseignant
`end_date`.

### 3.3 Séance (`Session`, `SessionSpec`)

Nouveau champ `sport` : `"run"` (défaut) ou `"bike"`. `SessionSpec.sport` a la même valeur
par défaut, ce qui garde valides les réponses de Claude et les propositions existantes.

### 3.4 Migration

Ajout des colonnes et de la table dans `_migrate` (`coach/plan/repo.py`), comme pour le temps
visé. Les objectifs existants reçoivent les 7 jours, `long_run_day = None`,
`include_bike = False` ; les séances existantes `sport = "run"`.

## 4. Règles vérifiées par Python

Un nouveau module de code pur `coach/plan/constraints.py` expose :

```python
@dataclass(frozen=True)
class PlanConstraints:
    available_days: frozenset[Weekday]
    long_run_day: Weekday | None
    include_bike: bool
    events: tuple[Event, ...]  # tous les imprévus de l'objectif

def session_date(goal, spec) -> date  # lundi de la semaine + suggested_day
def constraint_errors(
    specs, constraints, goal, *, exported: Mapping[int, date] | None = None
) -> list[str]
```

`specs` est l'ensemble des séances à venir **après** application des changements (pour un plan
complet : toutes ses séances) ; `exported` associe chaque séance exportée conservée à sa
`scheduled_date`.

`validate_plan` et `validate_adjustment` (`coach/llm/schemas.py`) appellent
`constraint_errors` et ajoutent ses erreurs aux leurs : la boucle existante de
`ask_structured` relance Claude une fois avec la liste, puis échoue avec un message.

Règles, chacune avec un message d'erreur qui nomme la séance et la règle :

1. **Jours possibles.** Le `suggested_day` de chaque séance non exportée à venir (modifiée ou
   non) fait partie des jours possibles de l'objectif, ou des `days_json` de la semaine allégée
   qui couvre sa semaine. Une séance exportée garde sa date Garmin et n'est pas soumise à cette
   règle (l'avertissement d'export de 6.5 suffit).
2. **Périodes bloquées.** Une période bloquée est un `unavailable`, ou un `injury` (de
   `start_date` à `end_date`). Aucune séance proposée (ajout ou modification) ne tombe dans une
   période bloquée. Une séance **exportée** dont la `scheduled_date` tombe dans une période
   bloquée **doit** faire l'objet d'un `remove` dans l'ajustement ; le nettoyage Garmin existant
   la retire du calendrier à l'acceptation. Une séance `todo` non modifiée qui tombe dans une
   période bloquée doit elle aussi être retirée ou déplacée.
3. **Arrêt ouvert.** Pour la vérification, un arrêt ouvert bloque de `start_date` jusqu'au
   dimanche de la semaine en cours. Les semaines suivantes ne sont pas touchées tant que la
   reprise n'est pas signalée.
4. **Semaine allégée.** Le nombre de séances de la semaine (après changements, avec le
   décompte existant de `validate_adjustment`) ne dépasse pas `max_sessions`.
5. **Sortie longue.** Si `long_run_day` est renseigné, une séance `sortie_longue` tombe ce
   jour-là, sauf si ce jour est bloqué ou exclu cette semaine-là (alors n'importe quel jour
   possible convient).
6. **Vélo.** `sport = "bike"` seulement si `include_bike` ; une séance vélo est de type `EF`
   ou `récup`, `target_kind = "hr"`, et ses étapes n'utilisent que les zones FC Z1 et Z2 (ou
   aucune zone). Au plus une séance vélo par semaine.

Un `fatigue` ne bloque rien : il sert de contexte à Claude.

## 5. Prompts

`coach/llm/prompts.py` reçoit les contraintes dans les prompts de génération, de
régénération et d'ajustement :

- un bloc « Disponibilités » : jours possibles, jour de sortie longue ;
- un bloc « Imprévus » : imprévus en cours ou à venir (et les `fatigue` des 14 derniers jours),
  avec dates et notes ;
- si `include_bike` : la consigne vélo (remplacer au plus une séance `EF` ou `récup` par
  semaine par du vélo d'endurance Z1–Z2 en FC, route ou home-trainer, jamais à la place
  d'une séance clé ; durée d'environ 1,3 à 1,5 fois la durée course équivalente) ;
- le `sport` de chaque séance listée (passée ou à venir).

Une demande d'ajustement déclenchée par un imprévu passe une note décrivant l'imprévu, via le
paramètre existant `change_note` de `ask_adjustment` (renommé si besoin en `trigger_note`).
La reprise après un arrêt ajoute la consigne « reprise progressive après N jours d'arrêt :
volume et intensité réduits les premières semaines ».

## 6. Parcours et écrans

### 6.1 Création et modification de l'objectif

- `Goal.svelte`, sous « séances/semaine » : sept cases à cocher (toutes cochées par défaut),
  une liste « Jour de la sortie longue » (Aucun ou un des jours cochés), une case « Inclure du
  vélo (endurance douce, en remplacement de séances faciles) ».
- `GoalEditDialog` : mêmes champs, en plus de la date et du temps visé. La modification suit
  le circuit existant de `update_goal` (note de changement, proposition d'ajustement ; rien
  n'est enregistré si Claude échoue). Changer les jours possibles invalide les séances placées
  sur un jour retiré : la règle 1 oblige Claude à les déplacer.

### 6.2 Déclarer un imprévu

- Bouton « Signaler un imprévu » sur les pages Aujourd'hui et Plan, qui ouvre `EventDialog` :
  choix du type, puis les champs du type (voir 3.2), avec une note libre.
- `POST /api/goals/{id}/events` : valide et enregistre l'imprévu (et passe la séance d'un
  `fatigue` en `missed` si elle est `todo` ou `exported`), puis demande l'ajustement et
  enregistre la proposition (`save_proposal` passe l'ancienne en `stale`). Réponse :
  `{event_id, proposal_id | null, error | null}`. Le front ouvre la page Proposition.
- Si Claude échoue, l'imprévu reste enregistré ; la réponse porte l'erreur et le front affiche
  « Réessayer », qui appelle `POST /api/goals/{id}/adjust` (demande d'ajustement seule, avec
  les contraintes courantes).

### 6.3 Liste et suppression

- Page Plan : section « Imprévus » listant ceux en cours et à venir (type, dates, note), chacun
  avec Supprimer (`DELETE /api/events/{id}`). Après suppression, le front propose
  « Recalculer le plan ? », qui appelle `POST /api/goals/{id}/adjust`.
- `GET /api/goals/{id}/events` renvoie les imprévus de l'objectif, du plus récent au plus ancien.

### 6.4 Arrêt et reprise

- Tant qu'un arrêt est ouvert, un bandeau s'affiche sur Aujourd'hui et Plan : « Arrêt depuis
  le X — Signaler la reprise ».
- La synchronisation continue d'importer les activités et de rattacher les séances, mais
  n'appelle pas Claude pour un ajustement (`sync` ignore `_propose`).
- « Signaler la reprise » : choix de la date (aujourd'hui par défaut), puis
  `POST /api/events/{id}/resume` renseigne `end_date` (veille de la reprise) et demande un
  ajustement avec la consigne de reprise progressive.

### 6.5 Export vers Garmin

`GET /api/sessions/{id}/export-check` ajoute des avertissements non bloquants, à côté de celui
des 48 h : « Jour hors de tes disponibilités », « Pendant ton imprévu du X au Y ».

## 7. Vélo

- **Génération et ajustement** : consigne de la section 5, règle 6 de la section 4.
- **Export** (`coach/export/garmin_workout.py`) : `sportType`
  `{"sportTypeId": 2, "sportTypeKey": "cycling"}` pour une séance vélo, au niveau du workout et
  du segment ; cibles FC comme aujourd'hui. La stratégie du jour J n'est pas concernée.
- **Rattachement** (`coach/analysis/compliance.py`) : `CYCLING_TYPES = {"cycling",
  "road_biking", "indoor_cycling", "virtual_ride", "gravel_cycling", "mountain_biking"}`. Une
  séance vélo exportée se rattache à une activité vélo (±1 jour, ±30 % de durée) ; une séance
  course aux seules activités de course. Le rattachement manuel (`/activities/free`,
  `/activities/{id}/match`) applique la même séparation.
- **Interface** : icône vélo sur `SessionCard` ; la séance vélo affiche sa durée et n'entre
  pas dans les kilomètres de course de la semaine. La comparaison prévu / réalisé par étape
  fonctionne sans changement (FC par tour).

## 8. Gestion des erreurs

- Réponse de Claude non conforme aux contraintes : une nouvelle tentative avec la liste des
  erreurs, puis message et « Réessayer » (comportement existant de `ask_structured`).
- Imprévu invalide (dates incohérentes, deuxième arrêt ouvert, semaine hors du plan, séance
  d'un autre objectif) : 422 avec message en français, rien n'est enregistré.
- Échec de Claude après un imprévu : l'imprévu est conservé, la proposition peut être
  redemandée.
- Échec de Claude pendant une modification de l'objectif : rien n'est enregistré (comportement
  existant).

## 9. Tests

- **Code pur** (`tests/test_constraints.py`) : chaque règle de la section 4 avec un cas valide
  et un cas invalide, notamment une séance exportée dans une période bloquée sans `remove`,
  un arrêt ouvert, un jour de sortie longue bloqué, une semaine allégée avec `days_json`, une
  séance vélo hors EF/récup ou en Z3.
- **Schémas** : `SessionSpec` sans `sport` vaut `run` ; anciennes propositions relues sans
  erreur.
- **Flux** (`FakeLLMProvider`, `FakeGarminClient`) : réponse violant une règle puis réponse
  correcte ; déclaration d'un imprévu → proposition en attente ; échec de Claude → imprévu
  conservé, `adjust` réussit ensuite ; reprise → proposition ; synchro sans ajustement pendant
  un arrêt ouvert ; séance `fatigue` passée en `missed`.
- **Export et rattachement** : JSON d'un workout vélo ; une activité vélo ne se rattache pas à
  une séance course, et inversement.
- **Migration** : base de la version 0.5.0 ouverte sans perte, valeurs par défaut appliquées.
- **API** (`TestClient`) : routes `events`, `adjust`, `resume`, validations 422,
  avertissements de `export-check`.
- **Front** (Vitest) : `EventDialog` (champs par type, validation), nouveaux champs de
  `Goal.svelte` et `GoalEditDialog`, bandeau d'arrêt, icône vélo sur `SessionCard`.

## 10. Livraison

Trois lots, chacun utilisable seul, dans cet ordre :

1. **Disponibilités** : champs de l'objectif, migration, `constraints.py` (règles 1 et 5),
   prompts, formulaires, avertissement d'export.
2. **Imprévus** : table `Event`, règles 2 à 4, routes, `EventDialog`, liste, arrêt et reprise,
   suspension des ajustements de synchro.
3. **Vélo** : champ `sport`, règle 6, consigne de prompt, export, rattachement, interface.
