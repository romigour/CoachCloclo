# Plusieurs objectifs avec priorité, plan par cycles

Date : 2026-11-13
Statut : design relu, en attente de validation

## 1. Intention

Aujourd'hui l'application ne connaît qu'**un objectif actif** : en créer un archive le précédent
et supprime ses séances à faire, et le plan va de `plan_start` à la date de cette unique course.

L'athlète veut construire une **saison** : plusieurs courses, chacune avec une importance. Cas
réel qui motive la fonctionnalité :

| Date | Course | Priorité voulue |
|---|---|---|
| mai | Ultra trail | Principal |
| dim. 22 mars | Semi-marathon route | Plaisir (ou déplacé : trop proche du 28) |
| sam. 28 mars | Urban trail 20 km | Secondaire |
| dim. 29 mars | 30 km (2e jour du même week-end) | Plaisir |

Les objectifs secondaires restent **de vraies courses** : il faut prévoir les séances et un
affûtage pour les réussir, **en gardant à l'esprit la suite** (l'ultra). La priorité doit donc
changer la façon dont Claude prépare les séances à venir.

### Critères de succès

- On peut avoir plusieurs objectifs à venir en même temps, chacun avec une priorité
  **Principal**, **Secondaire** ou **Plaisir**, et on peut en ajouter après un Principal, ou
  sans aucun Principal à venir.
- Deux objectifs non-Plaisir à moins de 14 jours l'un de l'autre sont refusés avec un message
  qui nomme l'objectif en conflit.
- Le plan (un cycle) va jusqu'au prochain Principal et y intègre les Secondaires et Plaisirs de
  la période : aucune séance le jour d'une course, mini-affûtage avant un Secondaire,
  récupération après, une course Plaisir prend la place d'une séance.
- Ajouter, modifier ou retirer un objectif dans un plan validé produit une **proposition
  d'ajustement** ; les séances faites ou exportées sont préservées.
- Une fois le Principal couru, l'application propose de **préparer le cycle suivant**.
- Une base existante continue de fonctionner sans action : l'objectif actif devient le
  Principal d'un cycle qui reprend son plan, ses séances et ses imprévus.

### Non-objectifs

- Pas de course « en plusieurs étapes » : un week-end défi = deux objectifs (décidé).
- Pas de plan sur toute la saison d'un coup, ni de plan glissant (approches écartées, §3).
- Pas de choix automatique de priorité par Claude ni par l'app : en cas de conflit, c'est
  l'athlète qui tranche.
- Pas de réglages d'affûtage par objectif (durée, volume) : la priorité suffit.

### Anti-objectifs

- Un plan qui sacrifie le Principal pour un Secondaire (affûtage long, coupure de la charge).
- Ajouter une course qui efface des séances faites ou déjà sur la montre.
- Un calendrier impossible envoyé à Claude (deux affûtages qui se chevauchent).

## 2. Décisions prises avec l'athlète

| Sujet | Décision |
|---|---|
| Niveaux de priorité | Principal, Secondaire, Plaisir |
| Objectifs trop proches | Blocage : deux non-Plaisir à moins de 14 jours sont refusés ; message qui propose de passer l'un en Plaisir ou de déplacer |
| Week-end sur deux jours | Deux objectifs (samedi Secondaire, dimanche Plaisir) |
| Plusieurs Principaux | Autorisés ; un Principal plus tardif n'a quasiment pas d'impact sur le précédent |
| Courses sans Principal à venir | Autorisées (Secondaire ou Plaisir seuls) |
| Construction du plan | **Plan par cycles** (approche A) |

## 3. Approches envisagées

**A. Plan par cycles — retenue.** Le plan couvre la période jusqu'au prochain Principal (ou
jusqu'au dernier objectif s'il n'y a plus de Principal à venir). Les autres objectifs de la
période y sont intégrés ; les objectifs plus lointains sont donnés à Claude comme horizon. Après
le Principal, on prépare le cycle suivant. Plans de taille raisonnable, proche du code actuel
(un cycle = le plan d'aujourd'hui avec des jalons).

**B. Un plan unique jusqu'au dernier objectif.** Une génération pour toute la saison : réponse
très longue, validation fragile, semaines lointaines peu fiables et réécrites de toute façon.

**C. Plan glissant (4 à 6 semaines).** Le plus souple, mais refonte de la validation du plan, de
l'export et de la page plan, et plus de vue d'ensemble jusqu'à la course.

## 4. Modèle de données

### 4.1 Nouvelle table `Cycle`

Un cycle porte ce qui est aujourd'hui « le plan » dans `Goal` :

| Champ | Type | Rôle |
|---|---|---|
| `id` | int | |
| `created_at` | datetime | |
| `status` | `"active"` \| `"done"` | un seul `active` à la fois |
| `plan_start` | date | lundi de la semaine 1 (repris de `Goal.plan_start`) |
| `end_date` | date | date de la course qui termine le cycle (voir §5.1) ; recalculée |
| `sessions_per_week` | int | |
| `available_days_json` | JSON | |
| `long_run_day` | `Weekday` \| None | |
| `include_bike` | bool | |
| `plan_accepted` | bool | |

`end_date` est stockée (et non dérivée à chaque lecture) pour que `n_weeks`, `week_of`,
`suggested_date` et les contrôles d'imprévus gardent leur forme actuelle ; elle est mise à jour
dans la même transaction que toute modification d'objectif qui la change.

Les réglages (séances par semaine, jours possibles, sortie longue, vélo) deviennent des **réglages
du plan**, communs à tous les objectifs : il n'y a qu'une semaine d'entraînement.

### 4.2 `Goal`

- Nouveau champ `priority` : `"principal" | "secondaire" | "plaisir"`, défaut `"principal"`.
- `status` : `"active"` (à venir), `"done"` (date passée), `"archived"` (retiré par l'athlète).
- Les champs `plan_start`, `sessions_per_week`, `available_days_json`, `long_run_day`,
  `include_bike`, `plan_accepted` ne sont plus lus après migration (on les laisse en base :
  SQLite + migrations additives du projet, cf. `repo._migrate`).
- Restent propres à l'objectif : type, distance, D+, GPX, date, temps visé et sa source, et la
  stratégie du jour J (`RaceStrategy.goal_id`, inchangé).
- Un objectif n'est pas rattaché à un cycle : son cycle se déduit de sa date (§5.1).

### 4.3 `Session` et `Event`

- `Session.cycle_id` remplace `Session.goal_id` comme rattachement.
- `Event.cycle_id` remplace `Event.goal_id` : les imprévus concernent le plan, pas une course.
- Un arrêt (blessure) encore ouvert à la clôture d'un cycle est recopié dans le cycle suivant
  (même `start_date`, `end_date` nulle) pour que la génération en tienne compte.

### 4.4 Migration (idempotente, dans `repo._migrate`)

1. Créer la table `cycle` (`create_all`) et ajouter `goal.priority`, `session.cycle_id`,
   `event.cycle_id`.
2. Pour chaque objectif `active` sans cycle : créer un cycle `active` avec ses réglages,
   `plan_start`, `plan_accepted`, `end_date = race_date`, et priorité `principal`.
3. Renseigner `cycle_id` des séances et imprévus de cet objectif.
4. Les objectifs `archived` gardent leurs séances (historique) : un cycle `done` est créé pour
   chacun qui a des séances, afin que `cycle_id` ne soit jamais nul.

## 5. Règles métier

### 5.1 Composition d'un cycle

- Objectifs du cycle actif = objectifs `active` dont la date est entre `plan_start` et
  `end_date` incluses.
- `end_date` = date du **premier Principal à venir** ; s'il n'y en a pas, date du **dernier
  objectif à venir**.
- *Choix du concepteur :* si d'autres objectifs suivent ce Principal **les jours immédiatement
  consécutifs** (ex. Principal le samedi, Plaisir le dimanche), `end_date` s'étend au dernier jour
  de ce bloc, pour que ces courses appartiennent au cycle et que le cycle suivant commence bien
  un lundi.
- Objectifs après `end_date` = **horizon** : décrits à Claude en une ligne chacun (date, type,
  distance, priorité), sans séance dédiée.

### 5.2 Règle d'écart

- Deux objectifs `active` dont aucun n'est Plaisir doivent avoir au moins **14 jours** d'écart.
- Vérifiée à la création, au changement de date et au changement de priorité.
- Message : « {course} du {date} ({priorité}) est à {n} jours : passe l'un des deux en Plaisir
  ou déplace-le ».

### 5.3 Ce que la priorité demande à Claude (prompt, pas de contrôle Python)

- **Principal** : affûtage complet, comme aujourd'hui.
- **Secondaire** : séance spécifique dans les 10 jours avant, mini-affûtage de quelques jours
  (volume réduit, intensité conservée), récupération après, sans casser la progression vers le
  Principal.
- **Plaisir** : pas d'affûtage ; la course remplace une séance de sa semaine (souvent la sortie
  longue) ; récupération légère après si elle est longue.
- Deux courses consécutives (samedi + dimanche) sont présentées ensemble à Claude comme un bloc.
- L'horizon est rappelé : « Un Principal suit le {date} : le cycle suivant le préparera ;
  termine celui-ci par l'affûtage de {course} sans anticiper le suivant. »

### 5.4 Contrôles Python (ajoutés à `constraint_errors`)

- Aucune séance planifiée le jour d'un objectif du cycle.
- Une semaine qui contient k courses a au plus `sessions_per_week − k` séances (minimum 0).

### 5.5 Temps visé

Chaque objectif garde son temps visé ou laisse Claude l'estimer. `PlanResponse.estimated_time_s`
devient une liste `estimated_times: [{goal_id, seconds}]`, obligatoire pour chaque objectif du
cycle dont la source est `claude`, avec le même plancher d'allure qu'aujourd'hui.

*Choix du concepteur :* `AdjustmentResponse` porte aussi un champ `estimated_times` facultatif,
obligatoire quand l'ajustement intègre au cycle un objectif `claude` encore sans temps. Un objectif
de l'horizon reste sans temps jusqu'à la génération de son cycle ; la page Jour J l'indique
(« Temps estimé à la préparation de son cycle, ou fixe un temps visé ») au lieu du message actuel.

## 6. Parcours

### 6.1 Premier objectif (aucun cycle actif)

Formulaire actuel + priorité (Principal par défaut). Il crée l'objectif **et** le cycle avec
les réglages du plan. Le délai minimal de 14 jours avant la course s'applique comme aujourd'hui.

### 6.2 Ajouter un objectif (un cycle actif existe)

Formulaire sans les réglages du plan : type, distance, D+, GPX, date, temps visé, priorité.
La date doit être après aujourd'hui ; règle d'écart (§5.2). Ensuite :

| Situation | Effet |
|---|---|
| Plan pas encore validé (brouillon) | Le brouillon est marqué périmé ; « Générer » refait le plan |
| Plan validé, objectif dans le cycle | Proposition d'ajustement (comme `update_goal`) |
| Plan validé, la fin du cycle **avance** (Principal plus proche) | `end_date` recalculée, séances au-delà retirées comme pour un report de date (`update_goal`), proposition d'ajustement |
| Plan validé, la fin du cycle **recule** (objectif plus lointain sans Principal, ou Principal retiré) | **Régénération de la suite** (*choix du concepteur*, voir ci-dessous) |
| Objectif après le prochain Principal | Simple ajout à l'horizon, pas d'ajustement |

Rien n'est enregistré si Claude échoue (même garantie que `update_goal`).

*Choix du concepteur — régénération de la suite :* l'ajustement sert à retoucher quelques
séances, pas à écrire des semaines entières. Quand la fin recule, l'objectif est enregistré, le
cycle repasse en brouillon (`plan_accepted = False`) et « Générer » produit un plan pour les
semaines restantes : les semaines passées, les séances faites et celles déjà exportées sur la
montre sont conservées et transmises à Claude comme fixes ; seules les séances `todo` à venir
sont remplacées. En attendant la validation, l'export et la synchro restent dans l'état
« plan non validé » d'aujourd'hui, et le plan précédent reste affiché.

### 6.3 Modifier / retirer un objectif

« Modifier » ajoute la priorité aux champs actuels (date, temps visé). « Retirer l'objectif »
le passe en `archived` (sa stratégie Garmin exportée est nettoyée comme aujourd'hui) puis suit
les mêmes cas que l'ajout. *Choix du concepteur :* retirer le **dernier** objectif à venir
passe le cycle en `done`, supprime ses séances `todo` et retire de la montre celles qui y sont
exportées ; sans cycle actif, l'app se comporte comme aujourd'hui sans objectif (la synchro
importe les activités sans proposer d'ajustement). Les réglages du plan se modifient dans un dialogue « Réglages du
plan » séparé, qui reprend l'ajustement actuel.

### 6.4 Fin d'un cycle

- À la synchro, un objectif dont la date est passée passe en `done`.
- Quand le Principal du cycle (ou son dernier objectif) est passé, le cycle passe en `done`.
- S'il reste des objectifs `active`, l'app affiche « Préparer le cycle suivant » : nouveau cycle
  dont `plan_start` est le lundi suivant la course, réglages recopiés (modifiables), et
  génération avec la consigne « commence par une récupération adaptée à {course passée} ».
- Sans objectif à venir, l'app invite à en ajouter un.

## 7. Interface

- **Objectifs** (actuelle page « Objectif ») : liste des objectifs à venir triés par date, avec
  badge de priorité, type/distance/D+, temps visé, actions Modifier, Jour J, Retirer ; bouton
  « Ajouter un objectif » ; encart « Réglages du plan » ; objectifs courus repliés en bas.
- **Plan** : les jours de course apparaissent dans le calendrier (carte « Course » avec badge de
  priorité) ; les objectifs de l'horizon sont listés sous le plan.
- **Jour J** : sélecteur d'objectif, le prochain par défaut.
- **API** : `/status` renvoie `cycle` (réglages, `plan_accepted`, `end_date`), `goals`
  (à venir) et `next_goal` ; les routes `/goals/{id}/generate`, `/accept` et `/events`
  passent sous `/cycle/...` ; `/goals/{id}/race-plan/*` ne change pas.

## 8. Ordre de livraison

1. **Modèle et migration** : `Cycle`, `priority`, `cycle_id`, repo et services réécrits autour
   du cycle actif, comportement inchangé pour un seul objectif.
2. **Plusieurs objectifs** : ajout, modification, retrait, règle d'écart, page Objectifs.
3. **Prompts et contrôles** : objectifs du cycle et horizon dans les prompts, règles par
   priorité, contrôles §5.4, estimations multiples.
4. **Cycle suivant** : clôture, report de l'arrêt en cours, « Préparer le cycle suivant ».

## 9. Laissé au constructeur

- Noms exacts des routes et des composants, découpage des fichiers.
- Texte précis des consignes de priorité dans le prompt (dans l'esprit du §5.3).
- Présentation exacte du badge de priorité et de la carte « Course ».
- Date de départ d'un cycle préparé en retard (lundi de la semaine courante, comme `plan_start`
  aujourd'hui), sort d'une proposition en attente à la clôture d'un cycle (passée `stale`),
  présence des stratégies Jour J de plusieurs objectifs dans le prompt.
