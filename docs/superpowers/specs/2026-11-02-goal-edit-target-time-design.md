# Temps visé de l'objectif et modification d'un objectif en cours

Date : 2026-11-02
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

Deux évolutions liées de l'objectif de course :

1. **Temps visé à la création.** L'athlète choisit entre laisser Claude estimer un temps
   réaliste ou fixer lui-même le temps souhaité. Ce temps oriente le plan d'entraînement
   (allures, volume) et devient le temps visé de la stratégie du jour J.
2. **Modifier un objectif en cours.** Sur l'objectif actif au plan validé, l'athlète peut
   changer la date de course et le temps visé ; Claude propose alors un ajustement des
   séances à venir, à valider comme après une synchronisation.

Pour changer autre chose (type, distance, D+, GPX, séances par semaine), on crée un nouvel
objectif, ce qui archive l'actuel comme aujourd'hui.

### Critères de succès

- À la création, le choix « Laisser Claude estimer » produit un brouillon qui affiche le temps
  estimé ; le choix « Je fixe mon temps » produit un plan construit pour ce temps.
- La page Jour J affiche le temps visé de l'objectif en lecture seule et cale le découpage
  dessus ; elle ne permet plus de le saisir.
- Modifier la date ou le temps d'un objectif en cours aboutit à une proposition d'ajustement
  en attente ; refuser la proposition laisse l'objectif modifié et les séances inchangées
  (hors retraits automatiques décrits en 4.3).
- Si Claude échoue pendant une modification, rien n'est enregistré.
- Les objectifs et stratégies existants restent utilisables sans action de l'athlète.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Rôle du temps | Oriente le plan **et** sert de temps visé à la stratégie du jour J |
| Estimation par Claude | Dans le même appel que la génération du plan (champ `estimated_time_s`) |
| Champs modifiables | Date de course et temps visé uniquement |
| Effet d'une modification | Proposition d'ajustement par Claude, à valider |
| Source du temps visé | L'objectif ; la page Jour J l'affiche en lecture seule |
| Atomicité | Objectif, retraits de séances et proposition enregistrés ensemble, après la réponse de Claude |

## 3. Modèle et migration

### 3.1 `Goal`

Deux colonnes :

```python
target_time_s: int | None = None
target_source: str | None = None  # "user" | "claude"
```

- Création en mode « temps fixé » : `target_time_s` renseigné, `target_source = "user"`.
- Création en mode Claude : `target_time_s = None`, `target_source = "claude"` jusqu'à la
  première génération, qui renseigne `target_time_s`.
- Objectifs antérieurs : les deux colonnes à `None`.
- Une modification du temps passe `target_source` à `"user"`.

### 3.2 `RaceSettings`

`target_time_s` est retiré de `RaceSettings`. Le modèle ignore les clés inconnues, si bien que
les `settings_json` existants qui contiennent encore `target_time_s` restent lisibles.

### 3.3 Migration

`create_all` ne modifie pas une table existante. `make_engine` gagne une étape idempotente,
exécutée après `create_all` :

1. Si `goal.target_time_s` ou `goal.target_source` manquent (`PRAGMA table_info(goal)`), les
   ajouter par `ALTER TABLE goal ADD COLUMN`.
2. À l'ajout des colonnes seulement : pour chaque `racestrategy` dont `settings_json` contient
   un `target_time_s` non nul, le recopier sur l'objectif lié avec `target_source = "user"`.

Une base neuve passe par `create_all` et n'exécute aucune de ces étapes.

## 4. Fonctionnement

### 4.1 Création de l'objectif

**API.** `POST /goals` accepte un champ de formulaire facultatif `target_time` au format `h:mm`.
Présent : mode « temps fixé ». Absent : mode Claude. `GoalInput` gagne
`target_time_s: int | None` ; le parsing `h:mm` et le contrôle de vraisemblance (allure moyenne
pas plus rapide que 2:30/km, cf. `_TOO_FAST` de `race_strategy`) sont factorisés pour servir à
la création, à la modification et à l'affichage.

**Prompt de génération.** `_goal_text` ajoute le temps visé quand il est connu :
« Temps visé : 1 h 50 ». Puis `build_generation_prompt` ajoute selon le mode :

- temps fixé : « Construis le plan pour atteindre ce temps visé (allures cibles, volume). » ;
- mode Claude : « Estime d'abord un temps réaliste pour cette course à partir des zones, de
  l'historique, de la distance et du D+, renseigne-le dans `estimated_time_s` (en secondes),
  puis construis le plan pour ce temps. »

**Schéma.** `PlanResponse` gagne `estimated_time_s: int | None = None`. `validate_plan` reçoit
`estimate_required: bool` et renvoie une erreur si l'estimation manque ou n'est pas strictement
positive en mode Claude ; `ask_structured` relance alors comme pour les autres erreurs métier.
En mode « temps fixé », le champ est ignoré.

**Enregistrement.** `generate_plan` écrit `estimated_time_s` sur l'objectif, dans la même
transaction que les séances, quand `target_source == "claude"`. Une régénération en mode Claude
ré-estime donc le temps.

### 4.2 Brouillon et objectif actif

- Le brouillon affiche le temps à côté de la distance et de la date :
  « Temps estimé par Claude : 1 h 52 » ou « Temps visé : 1 h 50 ».
- `_goal_dict` expose `target_time_s` et `target_source`.

### 4.3 Modification d'un objectif en cours

**API.** `PATCH /goals/{goal_id}`, corps JSON `{ "race_date"?: date, "target_time"?: "h:mm" }`.
Réponse : `{ "goal": …, "proposal_id": int }`.

**Validation** (`GoalError`, réponse 422) :

- l'objectif est actif et `plan_accepted` ;
- au moins un champ fourni, et au moins une valeur différente de l'existant ;
- `race_date` strictement après aujourd'hui ;
- `target_time` au bon format et vraisemblable pour la distance de l'objectif.

**Service `update_goal(repo, garmin, llm, goal_id, data)`** :

1. Construire en mémoire une copie de l'objectif avec les nouvelles valeurs
   (`target_source = "user"` si le temps change).
2. Calculer le nouveau nombre de semaines `n = calendar.n_weeks(goal.plan_start, race_date)`.
3. Déterminer les séances à retirer : séances `todo` ou `exported` dont `week_index > n` ou dont
   `scheduled_date > race_date`. Elles sont exclues des séances à venir transmises à Claude.
4. Demander l'ajustement à Claude (voir 4.4) avec l'objectif modifié.
5. En une transaction : enregistrer l'objectif ; supprimer les séances `todo` retirées ;
   marquer les séances `exported` retirées pour nettoyage Garmin (`_mark_for_cleanup(…,
   removal=True)` de `garmin_export`) ; passer l'éventuelle proposition `pending` en `stale` et
   enregistrer la nouvelle.

Si l'étape 4 échoue (erreur LLM, réponse invalide après relances), l'exception remonte et rien
n'est enregistré.

Une date repoussée laisse les nouvelles semaines vides ; c'est à Claude de les remplir par des
`add`.

### 4.4 Proposition d'ajustement partagée

La partie de `sync._propose` qui construit le prompt, appelle `ask_structured` avec
`validate_adjustment` et enregistre la `Proposal` est extraite dans un nouveau module
`coach/services/adjust.py`, en deux fonctions : `ask_adjustment(...)` (prompt, appel à Claude,
validation, retourne l'`AdjustmentResponse`) et `save_proposal(db, adj)` (passe la proposition
`pending` en `stale` et enregistre la nouvelle dans la transaction fournie). Ensemble, elles :

- reçoit l'objectif (éventuellement modifié et non enregistré), les séances réalisées et
  manquées (vides pour une modification), les séances à venir, et une note de contexte
  facultative ;
- sépare l'appel à Claude de l'écriture de la `Proposal`, pour que `update_goal` enregistre
  tout dans sa propre transaction.

`build_adjustment_prompt` gagne `change_note: str | None`, placé juste après le texte de
l'objectif, par exemple : « L'athlète a modifié son objectif : course déplacée du 12/04/2027
au 26/04/2027 ; temps visé 1 h 55 au lieu de 1 h 50. Adapte les séances à venir en
conséquence. »

`validate_adjustment` gagne `n_weeks: int` et refuse toute séance (`add` ou `modify`) dont
`week_index > n_weeks`. La synchronisation passe le nombre de semaines courant.

### 4.5 Stratégie du jour J

- `_compute` passe `goal.target_time_s` à `build_race_plan` (qui le reçoit en paramètre au lieu
  de le lire dans `RaceSettings`). Sans temps sur l'objectif, la prédiction reste la référence.
- Le contrôle `_TOO_FAST` sur le temps visé quitte `save_settings` : il est fait à la création et
  à la modification de l'objectif.
- `_fingerprint` inclut `goal.race_date` et `goal.target_time_s` : après une modification de
  l'objectif, un export Jour J déjà fait apparaît à réexporter.
- `_view` expose le temps visé et sa source.

### 4.6 Interface

**Page Objectif, création.** Bloc « Temps visé » avec deux radios : « Laisser Claude estimer »
(défaut) et « Je fixe mon temps » ; le second affiche un champ `h:mm` validé côté client avec
les fonctions de `lib/race.ts`.

**Page Objectif, objectif actif.** Carte de l'objectif (distance, type, date, temps visé et
source) avec un bouton « Modifier ». Il ouvre une boîte de dialogue avec la date et le temps
visé, et la phrase : « Pour changer la distance ou le type de course, crée un nouvel
objectif. » À la validation : message « Claude ajuste ton plan… », puis redirection vers la
proposition en attente. En cas d'erreur, la boîte reste ouverte avec le message.

**Page Jour J.** Le champ « Temps visé » est remplacé par une ligne en lecture seule :
« Temps visé : 1 h 52 · estimé par Claude » (ou « fixé par toi »), avec un lien « Modifier
l'objectif » vers la page Objectif. Sans temps sur l'objectif : « Pas de temps visé, référence :
prédiction ».

## 5. Erreurs

| Cas | Comportement |
|---|---|
| Date passée, temps invraisemblable, format invalide | 422, message en français |
| Objectif archivé, introuvable ou plan non validé | 422 (`GoalError`) |
| Aucune modification | 422 « Aucune modification » |
| Estimation manquante en mode Claude | Relance de `ask_structured`, puis erreur LLM si persistante |
| Échec de Claude pendant une modification | Erreur affichée, aucune donnée modifiée |

## 6. Tests

TDD sur chaque couche.

- **Migration** : base à l'ancien schéma avec une stratégie ayant un temps visé, colonnes
  ajoutées et temps recopié ; seconde ouverture sans effet.
- **`create_goal` / `generate_plan`** : mode temps fixé ; mode Claude avec enregistrement de
  l'estimation ; régénération qui ré-estime.
- **`validate_plan`** : estimation exigée en mode Claude, ignorée sinon.
- **`validate_adjustment`** : refus d'une semaine au-delà de `n_weeks`.
- **`update_goal`** : temps seul ; date avancée (séances `todo` supprimées, `exported` marquées
  pour nettoyage) ; date repoussée ; aucune modification ; objectif non validé ; échec de
  Claude sans effet en base ; ancienne proposition passée `stale`.
- **Prompts** : temps visé dans `_goal_text`, consigne d'estimation, note de modification.
- **Stratégie du jour J** : temps lu sur l'objectif ; empreinte modifiée après changement de
  date ou de temps ; ancien `settings_json` avec `target_time_s` lisible.
- **API** : `POST /goals` avec et sans `target_time`, `PATCH /goals/{id}`.
- **Front (Vitest)** : choix estimation / temps fixé dans `Goal.test.ts`, boîte de dialogue de
  modification, affichage en lecture seule sur la page Jour J.

## 7. Hors périmètre

- Modifier le type, la distance, le D+, le GPX ou le nombre de séances par semaine.
- Redemander une estimation à Claude sur un objectif en cours.
- Supprimer un objectif sans en créer un nouveau.
