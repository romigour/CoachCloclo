# Jour J — un guide de course plutôt qu'un tableau

Date : 2026-11-26
Statut : design en relecture

## 1. Intention

La page Jour J affiche aujourd'hui un tableau de segments. Sur une course sur route sans GPX, le
parcours est découpé en tranches égales de 1 km, toutes « plat », avec la même allure : un gros
tableau qui ne dit rien. La nutrition et l'eau n'existent qu'en trail.

Le coureur veut savoir **comment gérer sa course** : comment partir, quand pousser, quoi manger et
boire, que faire la semaine d'avant et le matin. La page devient un **guide de course**, lu la
semaine d'avant pour se préparer et **relu le matin même, sur le téléphone**.

Le guide vaut pour toutes les courses (route avec ou sans GPX, trail). Le détail du parcours
(profil, montées et descentes, ravitos, barrières) s'ajoute quand il existe.

### Critères de succès

- Route sans GPX : plus aucun tableau par km. La page montre un encadré « À retenir le matin »,
  3 ou 4 phases de course avec une allure repère chacune, des temps de passage aux bornes clés,
  un plan eau et nutrition adapté à la durée, et des conseils de préparation.
- La page s'affiche immédiatement et complètement **sans Claude**.
- Un bouton ajoute des « Conseils du coach » rédigés par Claude, personnels (notes de l'objectif,
  historique), sans aucun chiffre inventé.
- Le guide se lit sur le téléphone (appli mobile en lecture seule), tel que l'ordinateur l'a
  calculé en dernier.

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs**
- Un guide calculé par règles (Python, déterministe) commun à toutes les courses.
- Des allures par phase plutôt que par km ; des temps de passage aux bornes clés.
- Eau et nutrition pour la route aussi, avec des valeurs recommandées selon la durée prévue.
- Une couche facultative « Conseils du coach » rédigée par Claude, à la demande.
- Le guide lisible sur mobile.

**Non-objectifs**
- Météo, poids, taux de sudation (l'appli ne les a pas).
- Calibration du modèle d'allure sur l'historique.
- Modifier les textes du guide à la main.
- Changer le calcul de prédiction (Minetti, Riegel) : il reste tel quel.

**Anti-objectifs** (échec même si « ça marche »)
- Claude donne une allure, un temps ou une heure qui ne vient pas du calcul.
- La page est vide ou bloquée quand Claude est indisponible.
- Le tableau par km revient pour une route sans GPX, sous une autre forme.
- La PWA écrit dans la base, ou on maintient deux copies de l'écran (ordinateur / mobile).

## 3. Approches envisagées

| | Approche | Pour | Contre |
|---|---|---|---|
| A | Conseils par règles seulement | instantané, gratuit, reproductible, testable | peu personnel |
| B | Guide entier rédigé par Claude | très personnel | attente et coût, page vide sans Claude, chiffres peu fiables |
| **C** | **Base calculée par règles + couche Claude facultative** | fiable, immédiat, et personnel en plus | deux parties à construire |

**Choix : C** (choix de l'utilisateur). Le matin de la course, il faut des chiffres justes et une
page qui s'affiche quoi qu'il arrive ; Claude apporte ce que les règles ignorent (tendances de
l'athlète, notes de l'objectif).

## 4. Décisions prises avec l'utilisateur

| Sujet | Décision |
|---|---|
| Moment de lecture | La semaine d'avant (préparer), relu le matin même |
| Périmètre | Toutes les courses ; détail du parcours en plus quand il existe |
| Production des conseils | Approche C |
| Mobile | Inclus dans ce projet |

## 5. Le guide

### 5.1 Contenu, dans l'ordre de la page

```
Jour J · Semi de Lyon · dim. 14 déc. · départ 9:00          [Objectif ▾]
┌─ À retenir le matin ─────────────────────────────────────────┐
│ Objectif 1:45 · allure moyenne 4:58/km                         │
│ Départ : 5:05–5:10 /km les 3 premiers km, pas plus vite        │
│ Passages : 5 km 25:00 · 10 km 49:45 · 15 km 1:14:30            │
│ Petit-déj avant 6:00 · échauffement 8:35 · 1 gel au km 12      │
└────────────────────────────────────────────────────────────────┘
Réglages        heure de départ · temps visé (Modifier l'objectif) · glucides / eau
Pendant la course   phases (nom, km de → à, allure repère, conseil)
Passages        bornes clés : km, temps écoulé, heure
Eau et nutrition    principe selon la durée + quoi prendre et quand
Préparation     La semaine d'avant · La veille · Le matin (avec heures)
Conseils du coach   (Claude) bouton / texte / « à redemander »
Parcours        (GPX ou trail) profil + détail des segments, replié par défaut
Ravitaillements (trail) inchangé
[Enregistrer] [Envoyer à la montre]
```

### 5.2 Calcul (`coach/analysis/race_guide.py`, module pur)

Entrée : le `RacePlan` déjà calculé, le type et la distance, les réglages. Sortie : `RaceGuide`
(Pydantic), sérialisable tel quel pour le mobile. Sans temps de référence, le guide existe quand
même : allures, passages et heures sont absents, les conseils restent, et l'avertissement actuel
(« saisis un temps visé ») s'affiche.

**Tranches de distance** (pilotent phases, passages et conseils) — *mon choix, ajustable* :
`≤ 12 km` (5–10 km), `≤ 25 km` (semi), `≤ 45 km` (marathon), au-delà (ultra). Le trail utilise
les mêmes tranches mais ses conseils parlent d'effort et de FC plutôt que d'allure.

**Phases** (route) — *mon choix* : départ, installation, cœur de course, final. Bornes en
proportion de la distance (ex. départ ≈ 10–15 %, final ≈ 10–15 % ; un 5–10 km peut n'avoir que
3 phases). Le départ est légèrement plus lent que l'allure moyenne (≈ +5 à +10 s/km), le final
légèrement plus rapide si les sensations le permettent ; les allures sont recalées pour que la
somme redonne exactement le temps de référence. Chaque phase porte une fourchette d'allure et
un conseil court. Avec un GPX, l'allure de chaque phase est la moyenne pondérée des segments
qu'elle couvre, et la phase signale ses montées notables (« côte km 14, +40 m : reste à
l'effort, pas à l'allure »). En trail, une phase donne la zone FC et l'effort ressenti plutôt
qu'une allure.

**Passages** : tous les 5 km jusqu'au semi ; 5, 10, semi, 25, 30, 35 km au marathon ; tous les
10 km au-delà ; toujours l'arrivée. En trail : les ravitos (tableau actuel des passages).

**Eau et nutrition** — recommandations par durée prévue (*mon choix, consensus usuel*) :
moins de 1 h 15 : pas de glucides nécessaires, eau facultative ; 1 h 15 à 2 h 30 : 30–60 g/h,
boire à la soif aux ravitos ; plus de 2 h 30 : 60–90 g/h, gel toutes les 30–40 min, boire
régulièrement. Le guide en tire des prises concrètes (« gel au km 12 ») à partir de
`carbs_g_h` et du temps de référence. En trail, le tableau par tronçon actuel reste.

`carbs_g_h` et `water_ml_h` deviennent facultatifs (`None` = recommandation selon la durée) et
sont désormais réglables aussi sur route. Les stratégies route existantes ont 60 / 500 enregistrés
mais jamais affichés : la migration les remet à `None`. Les stratégies trail gardent leurs valeurs.

**Préparation** : blocs « La semaine d'avant », « La veille », « Le matin », choisis par tranche
de distance et type. Le matin est daté à partir de l'heure de départ : petit-déjeuner ≈ 3 h avant
(2 h pour ≤ 12 km), échauffement adapté (≈ 15–20 min dont quelques accélérations sur 5–10 km,
plus court sur semi, quasi rien au-delà), arrivée sur place. Exemples de contenu : affûtage et
sommeil, repas plus riches en glucides les 2 jours avant un marathon, ne rien tester de nouveau
(chaussures, gels), préparer le sac et le dossard la veille, repérer l'accès au départ. Le texte
exact est laissé au constructeur, avec ces exigences : phrases courtes, tutoiement, français
correct, pas de valeur au kilo de poids (poids inconnu).

### 5.3 Conseils du coach (Claude)

- Bouton « Demander les conseils du coach » ; texte enregistré, affiché avec sa date.
- Entrée du prompt : ligne de l'objectif avec ses notes, le guide calculé (chiffres compris),
  l'historique récent et les courses passées (fonctions déjà utilisées par les autres prompts).
- Sortie structurée (`ask_structured`) : quelques conseils courts (titre + texte), nombre borné.
  La validation rejette toute réponse qui contient une allure, une durée ou une heure absente du
  guide fourni ; une relance, puis erreur affichée.
- Coût suivi par `tracked(repo, "race_advice")`.
- Les conseils restent affichés si l'objectif, le temps visé ou les réglages changent, avec la
  mention « Objectif modifié depuis : redemande les conseils » (empreinte comme `export_stale`).
- Claude indisponible : message d'erreur dans la section, le reste de la page est intact.

### 5.4 Envoi à la montre

- Route sans GPX : une étape par **phase** (à la distance, cible d'allure ± 5 s/km).
- Route avec GPX et trail : inchangé (une étape par segment).

### 5.5 Mobile

- La PWA ne calcule rien : l'ordinateur enregistre une **copie du guide** (JSON `RaceGuide` +
  conseils du coach + date) dans la stratégie, chaque fois qu'il recalcule la vue (lecture,
  enregistrement, actualisation, conseils) et après une modification de l'objectif.
- Nouvelle route `race` sur mobile, lien « Jour J » dans la barre latérale mobile, lecture via
  `web/src/lib/turso` comme les autres écrans. Sélecteur d'objectif comme sur l'ordinateur.
- **Un seul composant d'affichage du guide**, partagé ; réglages, boutons et parcours éditable
  masqués par `READONLY`.
- Objectif sans copie : « Ouvre le Jour J sur l'ordinateur pour préparer ce guide ». La copie
  affiche « mis à jour le … ».

### 5.6 Stockage

Colonnes ajoutées à `RaceStrategy` (migration, `SCHEMA_VERSION` 5) : copie du guide (JSON) et
sa date, conseils du coach (JSON), leur date et leur empreinte. La table `racestrategy` rejoint
la liste des tables migrées.

## 6. Précisions après relecture (mes choix, à corriger)

- **Départ prudent et final, partout sur route.** L'écart d'allure (départ plus lent, final un
  peu plus rapide, total inchangé) est appliqué dans `build_race_plan` lui-même pour la route,
  avec ou sans GPX, et pas seulement dans le guide. Segments, phases, passages et montre disent
  donc la même chose. Le trail n'est pas concerné (il se pilote à la FC).
- **Rafraîchir la copie mobile.** Un seul point d'entrée recalcule la copie dès que le temps visé,
  la date, la distance ou le GPX changent : page Jour J, modification de l'objectif, temps estimé
  par Claude à la génération ou à l'ajustement, synchro. Si la stratégie n'existe pas encore, on
  ne la crée pas pour ça : le mobile affiche « Ouvre le Jour J sur l'ordinateur ». La mention
  « mis à jour le … » reste affichée.
- **Chiffres autorisés pour Claude.** Claude peut citer les chiffres réels présents dans le
  prompt (guide, historique, courses passées : « ton semi de mars en 1:48 »). Il ne doit jamais
  prescrire une allure, un temps ou une heure qui n'y figure pas. La validation rejette tout
  chiffre de ce type absent du prompt.
- **Glucides et eau facultatifs partout.** `None` est permis aussi en trail. Une nouvelle
  stratégie démarre à `None`, et les trails existants gardent leurs valeurs. Avec `None`, le
  tableau par tronçon utilise le milieu de la fourchette recommandée pour la durée.
- **Empreinte des conseils du coach.** Elle couvre ce qui change la course : temps de
  référence, date, distance ou GPX, notes de l'objectif. L'heure de départ et la nutrition ne
  la touchent pas, pour éviter un « à redemander » pour un détail.

## 7. Trail : de vraies phases (choix de l'utilisateur)

Le trail reçoit son propre découpage en phases, distinct des tronçons entre ravitos.

- **Découpage sur le temps prévu**, pas sur la distance (*mon choix*). En trail, la fatigue et la
  nutrition suivent la durée : un km de descente et un km de montée n'ont rien de commun. Il y a
  3 ou 4 phases selon la durée : départ, installation, cœur, final. Une borne proche d'un ravito
  (moins de 10 % de la durée de la phase) est calée sur ce ravito, pour que le coureur ait un
  repère concret.
- **Chaque phase porte** : km de → à, heure de passage prévue, zone FC et effort ressenti, les
  montées et descentes notables qu'elle contient (« montée km 18–23, +600 m : marche active
  au-delà de 15 % »), et un conseil d'effort. Exemples : ne pas suivre le peloton au départ,
  marcher tôt dans les montées, manger avant d'avoir faim au cœur, garder du jus pour les
  descentes de fin.
- **Encadré « À retenir le matin » en trail** : temps visé, consigne FC, résumé des phases,
  passages aux ravitos avec la marge sur chaque barrière, et la nutrition (glucides par heure,
  eau à emporter).
- **Ravitos et tableau de nutrition par tronçon** : inchangés, sous les phases.
- **Montre** : inchangée (une étape par segment, cible FC).

## 8. Laissé au constructeur

- Les textes exacts des conseils et leur répartition par tranche (dans le respect de 5.2).
- Les bornes exactes des phases et l'écart d'allure du départ et du final.
- La mise en page fine (cartes, repli du détail du parcours), en suivant le style existant.
- La forme exacte du schéma de sortie Claude et la règle de détection des chiffres.
