# Courses rapprochées et week-ends défi

Date : 2026-11-18
Statut : design relu, en attente de validation
Prolonge : `2026-11-13-multi-objectives-design.md` (remplace sa règle d'écart §5.2)

## 1. Intention

La règle d'écart actuelle refuse deux objectifs non-Plaisir à moins de 14 jours
(`coach/plan/goals.py`, `gap_conflict`). Elle protège contre un calendrier incohérent (deux
affûtages qui se chevauchent), mais elle bloque des saisons réelles. Cas qui motive le
changement :

| Date | Course | Priorité voulue |
|---|---|---|
| dim. 21/03/2027 | Semi-marathon route | Plaisir |
| sam. 27/03/2027 | Urban trail 20 km, ~450 m D+ | Secondaire (important) |
| dim. 28/03/2027 | Urban trail 30 km, ~600 m D+ | Secondaire (important) |
| mai 2027 | Ultra trail | Principal |

Le week-end urban trail est **un seul défi**, une sorte de « week-end choc » sur des courses
officielles : l'athlète veut un temps correct les deux jours, pas seulement finir. Aujourd'hui,
le dimanche devrait être Plaisir, donc préparé comme une sortie longue : le plan passerait à
côté de l'enjeu (30 km sur des jambes fatiguées par le 20 km de la veille).

La fonctionnalité doit traiter le cas général, pas seulement celui-ci : des courses importantes
rapprochées, ou enchaînées sur plusieurs jours, avec un plan cohérent et personnalisé à partir
des données Garmin déjà transmises (zones, VO2max, prédictions, historique).

### Critères de succès

- Deux objectifs non-Plaisir à moins de 14 jours ne sont plus refusés.
- Des courses à 0–2 jours d'écart forment un **bloc** préparé comme un seul défi.
- Pour des courses non-Plaisir à 3–13 jours, l'app désigne **de façon déterministe** celle qui
  reçoit l'affûtage, et le dit à l'athlète.
- Claude reçoit des consignes explicites pour chaque bloc et chaque groupe de courses
  rapprochées ; le plan ne contient jamais deux affûtages qui se chevauchent.
- Le temps estimé du 2ᵉ jour d'un bloc tient compte de la fatigue de la veille (donc le Jour J
  aussi, puisqu'il est calculé depuis le temps visé).
- Un objectif Secondaire long (ou un bloc) à quelques semaines du Principal reçoit un
  mini-affûtage proportionné à sa taille, sans casser la progression vers le Principal.

### Non-objectifs

- Pas d'entité « course à étapes » ni de temps cumulé : un bloc reste plusieurs objectifs
  (approche B écartée, §3).
- Pas de nouveau niveau de priorité (« Secondaire important ») : la taille de la course ou du
  bloc suffit à proportionner l'affûtage.
- Pas de nouvelles métriques Garmin (VFC, temps de récupération, disponibilité à
  l'entraînement) : chantier séparé, décidé plus tard.
- Pas de choix manuel de la course affûtée : la règle (§4.3) décide.

### Anti-objectifs

- Deux affûtages qui se chevauchent dans un plan.
- Un 2ᵉ jour de bloc préparé ou estimé comme s'il était couru seul.
- Un Secondaire qui sacrifie le Principal (affûtage long, coupure de la charge de fond).
- Un résultat différent d'une génération à l'autre sur « quelle course est affûtée ».

## 2. Décisions prises avec l'athlète

| Sujet | Décision |
|---|---|
| Blocage des 14 jours | Retiré, remplacé par des blocs et des groupes rapprochés (§4) |
| Week-end sur 2 jours | Un seul défi : deux objectifs, tous deux Secondaire (ou Principal) possibles |
| Courses rapprochées (3–13 j) | Autorisées avec un avertissement ; la plus prioritaire est affûtée |
| Égalité de priorité | La plus **tardive** est affûtée ; la précédente sert de grosse séance |
| Secondaire « important » | Pas de nouveau niveau : affûtage proportionné à la taille |
| Approche | A : règle Python + consignes explicites à Claude |
| Métriques Garmin en plus | Pas dans ce chantier |

## 3. Approches envisagées

**A. Règle de proximité en Python + consignes explicites — retenue.** Une fonction pure range
les objectifs en blocs et en groupes rapprochés et désigne la course affûtée ; le prompt reçoit
des lignes dédiées ; avertissement au lieu de refus. Pas de migration. Déterministe, testable,
proche du code actuel.

**B. Entité « événement multi-jours ».** Le week-end devient un objet avec étapes et temps
cumulé. Le plus explicite, mais migration, nouveau formulaire, Jour J à refaire ; ne règle pas
les courses à 3–13 jours. Déjà écartée le 13/11.

**C. Retirer le blocage + une phrase générale au prompt.** Le moins cher, mais Claude décide
seul quelle course affûter : non déterministe, retombe sur l'anti-objectif des affûtages qui se
chevauchent.

## 4. Règles métier

### 4.1 Bloc

- Un **bloc** = suite d'objectifs `active` dont chaque écart avec le suivant est **≤ 2 jours**
  (0, 1 ou 2 jours). Les Plaisir en font partie (un dimanche Plaisir reste « sur jambes
  fatiguées »).
- Priorité du bloc = la plus haute de ses objectifs ; date de début / de fin = premier / dernier
  jour.
- Un objectif isolé est un bloc d'un seul objectif (pour simplifier les règles suivantes).

### 4.2 Groupe rapproché

- On ne considère que les blocs **non-Plaisir** (priorité du bloc ≠ Plaisir).
- Deux blocs non-Plaisir dont l'écart (fin du premier → début du second) est **< 14 jours**
  sont dans le même **groupe rapproché** ; la relation est transitive (composantes connexes
  dans l'ordre des dates).
- Les blocs Plaisir ne créent ni ne cassent de groupe : ils gardent leur traitement actuel.

### 4.3 Bloc affûté

Dans un groupe de plusieurs blocs, un seul est **affûté** : celui de plus haute priorité ; à
égalité, le plus tardif. Les autres blocs du groupe :

- **avant** le bloc affûté → « intégré à l'affûtage » : pas d'affûtage propre, couru comme une
  grosse séance d'intensité dans la période d'affûtage, récupération courte après ;
- **après** le bloc affûté (possible seulement si celui-ci est plus prioritaire) → « course de
  rebond » : pas d'affûtage, la récupération de la course affûtée en tient lieu ; objectif
  réaliste compte tenu de la fatigue.

Cas de l'athlète : le semi est Plaisir → hors groupe ; le bloc 27–28/03 est seul dans son
groupe → affûté comme un Secondaire ; l'ultra est le Principal du cycle.

### 4.4 Fonction pure

Dans `coach/plan/goals.py`, remplacer `gap_conflict` par une fonction (nom au choix du
constructeur, ex. `race_groups(goals)`) qui renvoie pour chaque objectif : son bloc, son groupe
rapproché, son rôle (`affute`, `integre`, `rebond`, ou aucun) et la course affûtée de
référence. Elle sert au service (avertissement), à l'API (affichage) et aux prompts. Pas de
stockage : tout se recalcule depuis les objectifs actifs.

`MIN_GAP_DAYS = 14` reste, comme seuil du groupe rapproché ; une constante `BLOCK_MAX_GAP_DAYS
= 2` est ajoutée.

*Choix du concepteur (relecture) — objectifs déjà courus :* la fonction reçoit les objectifs
`active` **et** les objectifs `done` dont la date est dans les 14 derniers jours (les
`archived` restent ignorés). Sans cela, `close_passed` (qui passe un objectif à `done` le
lendemain) casse deux cas : la course de rebond, préparée dans le cycle suivant quand le
Principal est déjà `done`, redeviendrait un Secondaire isolé avec un mini-affûtage ; et un
ajustement entre les deux jours d'un bloc perdrait la consigne de fatigue du jour 2. Les
objectifs `done` servent seulement à former blocs et groupes et à nommer le bloc dans la note
de récupération ; ils ne reçoivent pas de consigne de préparation.

### 4.5 Fin de cycle

`cycle_end` étend aujourd'hui la fin du cycle aux jours **consécutifs** suivant le premier
Principal. Elle s'étend désormais au **bloc** entier (écarts ≤ 2 jours), pour qu'un week-end
Principal sam.–lun. reste dans un seul cycle.

*Choix du concepteur (relecture) :* si le premier Principal appartient à un groupe rapproché
dont le bloc affûté est **plus tardif** (ex. deux Principaux à 8 jours, égalité → le second est
affûté), la fin du cycle s'étend jusqu'à la fin de ce bloc affûté. Sinon l'affûtage serait coupé
par la frontière entre cycles et la ligne d'horizon « Termine ce cycle par l'affûtage de … »
contredirait le rôle « intégré » du premier. Conséquences :

- `next_bounds` et la classification des changements (`classify_change`) utilisent cette fin
  étendue : ajouter un objectif qui devient le bloc affûté du groupe du Principal **recule** la
  fin du cycle (cas « régénération de la suite » existant), au lieu d'aller à l'horizon ;
- la ligne d'horizon nomme le bloc affûté qui termine le cycle, pas le premier Principal ;
- les blocs « rebond » situés après le bloc affûté restent au cycle suivant.

*Choix du concepteur :* une course de rebond **après** un Principal tombe dans le cycle suivant
(règle actuelle des cycles, inchangée) ; la génération de ce cycle-là reçoit, en plus de la
note de récupération, la consigne « course de rebond » pour cet objectif.

### 4.6 Récupération après un bloc

La note de récupération du cycle suivant (`services/plans.py`, `_recovery_note`) nomme le bloc
entier quand la course de référence en fait partie : « Commence par une récupération adaptée au
bloc Trail de 20 km (27/03) + Trail de 30 km (28/03), soit 50 km et 1 050 m de D+ en 2 jours ».
Même logique dans le prompt de génération pour la récupération après un bloc au milieu d'un
cycle.

## 5. Ce que Claude reçoit (prompt)

Texte exact laissé au constructeur, dans l'esprit suivant.

### 5.1 Règles de priorité (remplace `PRIORITY_RULES`)

- **Principal** : affûtage complet, inchangé.
- **Secondaire** : séance spécifique dans les 10 jours avant ; mini-affûtage **proportionné** à
  la taille de la course ou du bloc (quelques jours pour une course courte, jusqu'à environ une
  semaine pour une course longue ou un bloc) et à sa distance au Principal ; volume réduit,
  intensité conservée ; récupération après ; la charge de fond du Principal est maintenue.
- **Plaisir** : inchangé.

### 5.2 Bloc

Pour chaque bloc de plusieurs objectifs, une ligne qui remplace l'actuel « (enchaînés, à
traiter comme un bloc) » :

- le bloc se prépare comme **un seul défi** (affûtage unique avant le premier jour) ;
- préparation spécifique : enchaînements dos à dos (ex. sortie longue + sortie le lendemain),
  travail du D+ et de la descente si le bloc en comporte ;
- chaque jour se court sur la fatigue des jours précédents : l'estimation de temps de chaque
  jour en tient compte ;
- la récupération après est dimensionnée sur le **cumul** (distance, D+, nombre de jours).

### 5.3 Groupe rapproché

Pour chaque groupe de plusieurs blocs, une ligne explicite par bloc non affûté : « {course} est
intégrée à l'affûtage de {course affûtée} : pas d'affûtage propre, à courir comme une grosse
séance d'intensité, récupération courte » ou « {course} est une course de rebond après
{course affûtée} : pas d'affûtage, objectif réaliste compte tenu de la fatigue ».

### 5.4 Horizon

Inchangé, sauf que les lignes d'horizon marquent aussi les blocs.

### 5.5 Où

Génération et ajustement (`build_generation_prompt`, prompt d'ajustement) : les deux passent
déjà par `_goals_text` et `_cycle_rules`, c'est là que les lignes s'ajoutent.

## 6. Contrôles Python

Inchangés : aucune séance le jour d'une course ; une semaine avec k courses a au plus
`sessions_per_week − k` séances (`_race_week_count_errors`, qui gère déjà deux courses dans la
même semaine). Pas de contrôle Python de « l'affûtage » : il n'est pas mesurable de façon fiable
sur des séances ; c'est le rôle des consignes.

## 7. Service et API

### 7.1 Plus de refus

`_apply_change` et `create_goal` (`coach/services/goals.py`) ne lèvent plus d'erreur d'écart.
Le reste du flux (proposition d'ajustement, régénération, horizon) est inchangé.

### 7.2 Avertissement

*Choix du concepteur :* l'avertissement est calculé côté serveur, pas dupliqué en TypeScript.

- La réponse de `POST /goals` et `PATCH /goals/{id}` porte un champ `notice` (texte ou `null`)
  quand l'objectif ajouté/modifié appartient à un groupe rapproché ou à un bloc de plusieurs
  objectifs. Ex. : « Semi-marathon du 13/03 et Trail de 20 km du 20/03 sont à 7 jours : Trail
  de 20 km sera affûté, Semi-marathon sera intégré à son affûtage. » / « Trail de 20 km
  (27/03) et Trail de 30 km (28/03) seront préparés comme un seul bloc. »
- Le formulaire d'ajout et le dialogue de modification affichent ce `notice` après
  l'enregistrement (bandeau d'information, pas d'erreur).
- `_goal_dict` (dans `/status` et `/cycle`) ajoute pour chaque objectif son rôle et la course
  de référence ; la page Objectifs affiche un libellé court sous l'objectif (« Bloc avec Trail
  de 30 km », « Intégré à l'affûtage de … », « Course de rebond après … »).

## 8. Tests attendus

- `race_groups` : bloc 0/1/2 jours, pas de bloc à 3 jours, Plaisir dans un bloc, groupe
  transitif de 3 blocs, égalité → le plus tardif, priorité plus haute avant → rebond, Plaisir
  hors groupe, objectifs `archived` ignorés, objectifs `done` de moins de 14 jours pris en
  compte (rebond après un Principal couru, jour 2 d'un bloc dont le jour 1 est couru).
- `cycle_end` étendue à un bloc avec un jour d'écart, et jusqu'au bloc affûté quand deux
  Principaux sont à moins de 14 jours.
- Prompts : lignes de bloc et de groupe rapproché présentes, texte « objectif unique »
  inchangé.
- Service : ajout à 1 jour et à 7 jours d'un non-Plaisir accepté, `notice` renvoyée ; les tests
  actuels « gap conflict » sont remplacés.
- Web : affichage du `notice` et des libellés de rôle.

## 9. Laissé au constructeur

- Nom et forme exacts de `race_groups` et de son résultat.
- Formulation précise des consignes du prompt (§5) et des libellés / du `notice` (§7).
- Seuil exact de « course longue » dans la consigne du Secondaire (laissé à Claude dans le
  texte, pas de calcul Python).
- Présentation du bandeau d'information dans le web.
