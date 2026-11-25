# Statistiques en sous-pages — conception

Date : 2026-11-25
Statut : à relire par Romain
Source d'idées : « Idées de statistiques pour une application de running » (document Claude Docs de Romain)

## 1. Intention

La page Statistiques empile tout : on s'y perd, il y a trop de données d'un coup. On la range **par question**,
en sous-pages, on garde ce qui est bien, et on ajoute des stats pertinentes et utiles.

**Objectifs**
- Une sous-page = une question, peu de blocs, chaque bloc conclu par une phrase d'interprétation.
- Période et sport conservés d'une sous-page à l'autre, recalcul instantané.
- Mêmes statistiques sur PC et dans la version mobile en lecture seule.

**Hors périmètre** : flux seconde par seconde (records par fenêtre glissante, dérive cardiaque, GAP),
analyse d'une séance, technique de course, sommeil/HRV/corrélations, météo, chaussures, badges et bilans.

**À éviter** : remettre autant de données, réparties autrement ; un chiffre sur trop peu de données ;
un ton médical ou prédictif sur la blessure.

## 2. Approches

| Approche | Pour | Contre |
|---|---|---|
| **A. Vraies sous-pages `#/stats/…`, calculs côté front (choix de Romain)** | Retour et favoris marchent, calculs communs au mobile, filtres instantanés | Étendre la gestion des adresses |
| B. Onglets dans la page actuelle | Un peu plus rapide | Retour quitte Statistiques, `Stats.svelte` grossit |
| C. Calculs côté serveur | Logique en Python | Écarté : le mobile lit Turso sans serveur, tout serait écrit deux fois |

Décisions de Romain : données déjà en base seulement ; approche A. Le reste est proposé par Claude.

## 3. Navigation

| Adresse | Sous-page | Question |
|---|---|---|
| `#/stats` | Aperçu | Où j'en suis ? |
| `#/stats/progress` | Progression | Est-ce que je m'améliore ? |
| `#/stats/load` | Charge | Est-ce que je m'entraîne bien ? |
| `#/stats/intensity` | Intensité | Est-ce que je cours à la bonne intensité ? |
| `#/stats/races` | Records & courses | Qu'ai-je réussi ? |

- Les onglets sont des liens (`aria-current="page"`), sous le titre ; défilement horizontal sur téléphone.
- `#/stats/inconnu` affiche l'Aperçu. L'entrée « Statistiques » de la barre latérale reste unique et active partout.
- Changer d'onglet ne relit ni les activités ni les records : la coquille `Stats.svelte` reste montée.
- Filtres : mêmes valeurs mémorisées (`coach.stats.filters`). Le choix du sport est masqué là où il n'agit pas
  (Progression, Intensité, Records & courses : toujours course et trail). Records & courses garde la période
  pour les compétitions ; les records restent absolus et le disent.
- Sur Charge, les deux filtres restent : le sport agit sur le volume, pas sur la forme (voir 4.3), et l'écran le dit.

## 4. Contenu

### 4.1 Aperçu
- Chiffres clés et calendrier de régularité, inchangés, filtrés par période et sport.
- **Constats** : au plus 4 phrases, une par sous-page (efficacité, forme, part facile, dernier record ou
  compétition de la période), chacune avec un lien. Un constat sans données suffisantes est omis.

### 4.2 Progression
- **Efficacité aérobie**, **VO2max**, **sortie la plus longue par mois**, **résumé trail** : repris, avec une phrase.
  La VO2max gagne une moyenne mobile sur 5 valeurs ; aucune courbe lissée avant 5 valeurs.
- **FC à allure donnée** : sorties retenues par l'efficacité aérobie actuelle. Allure de référence = médiane des
  allures de la période, arrondie à 5 s/km. On garde les sorties à ±10 s/km et on compare la FC moyenne du premier
  et du dernier tiers, par date. Au moins 9 sorties retenues, sinon « Pas assez de sorties à cette allure ».
  Phrase : « Autour de 5:30/km, ta FC moyenne est passée de 158 à 149 bpm. » Un écart de moins de 2 bpm est « stable ».
- **Prédicteur de temps** (Riegel, exposant 1,06) pour 5 km, 10 km, semi, marathon. Références possibles :
  compétitions `run` entrant dans une catégorie de distance (temps officiel, à défaut montre) et records Garmin
  5 km, 10 km, semi, marathon. Datées de 365 jours au plus avant aujourd'hui, indépendamment de la période.
  Référence retenue pour chaque distance cible : la plus proche en rapport de distances ; à égalité la plus récente.
  La référence (distance, date, temps) est affichée ; une cible à plus de 4 fois (ou moins d'un quart de)
  la distance de référence n'est pas prédite. Sans référence : « Aucune course ou record de moins d'un an ».

### 4.3 Charge
- **Volume** et **répartition par sport** : repris, filtrés par période et sport.
- **Variation hebdo** : heures de la dernière semaine complète (lundi-dimanche) par rapport à la moyenne des
  4 précédentes, filtre sport appliqué, période ignorée. Repère au-delà de +15 %. Rien si cette moyenne est nulle.
- **Charge d'une séance** (TRIMP de Banister) : `min × x × 0,64 × e^(1,92 x)`, `x = (FC moy − FC repos) / (FC max − FC repos)`
  borné à [0, 1]. Coefficients uniques pour tous, l'application ne connaissant pas le sexe : c'est une échelle
  personnelle, pas une comparaison entre athlètes.
- **FC repos et max** : déduites des zones FC de `api.zones()`, déjà lues sur bureau et mobile, donc sans nouvelle
  donnée : `FC max = Z5 haut`, `FC repos = 2 × Z1 bas − Z5 haut` (précision de l'arrondi : 1 à 2 bpm), seulement si `source`
  contient `karvonen`. Sinon les blocs de charge affichent « Synchronise Garmin pour calculer ta charge ».
  Les valeurs actuelles servent à tout l'historique (approximation indiquée à l'écran).
- **Forme, fatigue, fraîcheur** : charge par jour, tous sports et tout l'historique, jours vides compris, jusqu'à
  aujourd'hui ; `CTL` et `ATL` partent de 0, avec `v += (charge − v) / N`, N = 42 et 7. `TSB` = CTL − ATL du même jour.
  Courbe affichée sur la période, masquée pendant les 42 premiers jours de l'historique. Libellés : forme, fatigue, fraîcheur.
  Phrase selon `TSB / CTL` : > 0,1 « frais », de −0,3 à 0,1 « en charge équilibrée », < −0,3 « fatigue élevée ».
- **ACWR** : charge moyenne par jour sur 7 jours / sur 28 jours, aujourd'hui ; repère 0,8-1,3. Exige 28 jours
  d'historique et une charge non nulle. Formulation : « repère, pas une prédiction de blessure ».
- **Couverture** : nombre de séances sans FC des 42 derniers jours ; au-delà de 30 % de la durée, avertissement.

Monotonie et strain de Foster ne sont pas repris : redondants avec fatigue et ACWR pour un premier rangement.

### 4.4 Intensité
- **Zones FC** : reprises. Précision affichée : zones de la montre (Garmin).
- **Facile / moyen / dur** : Z1-2 / Z3 / Z4-5, en une barre, avec repère 80 % facile. Phrase : ≥ 75 % facile « proche
  du 80/20 » ; sinon, zone moyenne > 20 % « beaucoup de zone grise » ; sinon « part d'intensité élevée ».
- **Évolution par mois** : barres empilées à 100 %. Un mois couvert à moins de 50 % (règle existante) est laissé vide.

### 4.5 Records & courses
Records et compétitions repris tels quels, édition comprise.

## 5. Construction

- `App.svelte` : `parse()` accepte `stats/…` et passe la sous-page à `Stats`.
- `Stats.svelte` : coquille (chargement, filtres, bannières, onglets). Une vue par sous-page dans
  `web/src/components/stats/views/`. `RunningProgress.svelte` est découpé entre Progression et Intensité.
- Calculs purs et testés dans `web/src/lib/stats/` : `load.ts`, `predict.ts`, `intensity.ts`, `insights.ts`,
  et la FC à allure donnée dans `running.ts`. Les phrases sont des fonctions pures.
- Aucun changement Python, de schéma, ni de `web/src/lib/turso/`.
- Les liens existants vers `#/stats` restent valables. Guide et captures (`docs/guide`) mis à jour.
- Thèmes clair et sombre, `EChart` et couleurs existantes ; texte et légendes lisibles sans la couleur seule.

## 6. Erreurs et tests

- États actuels conservés sur toutes les sous-pages : chargement, erreur, import en cours, aucune activité.
- Zones absentes ou en échec : seuls les blocs de charge sont remplacés par leur message.
- Tests unitaires : TRIMP, CTL/ATL sur séries connues, semaines, ACWR, références et limites de Riegel, seuils de
  données, frontières de chaque phrase.
- Tests d'écran : adresses, onglet actif, sous-page inconnue, filtres conservés, une seule lecture des activités, mobile.
- Vérification visuelle : ordinateur et téléphone, clair et sombre.

## 7. Laissé au constructeur

Noms de composants, mise en page fine, formulation exacte des phrases, ordre de livraison.
