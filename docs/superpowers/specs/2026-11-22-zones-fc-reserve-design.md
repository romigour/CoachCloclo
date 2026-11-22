# Zones FC calculées par l'app (FC de réserve) — design

Date : 2026-11-22 · Taille : petit changement

## Pourquoi

Les zones FC venaient telles quelles de Garmin Connect. Avec la méthode Garmin par défaut
(« % de FC max », Z1 = 50–60 %), une FC max de ~182 donne Z1 = 91–109 bpm et Z2 = 109–127 bpm :
bien trop bas pour courir. Une séance EF « 30 min en Z2 » devenait irréaliste.

## Objectif

Des zones FC réalistes pour la course, calculées par l'app quel que soit le réglage de zones
dans Garmin Connect.

## Ce qui change

- **Méthode unique : FC de réserve (Karvonen).** Les seuils de zones Garmin
  (`zone1Floor`…`zone5Floor`) ne sont plus utilisés. Toujours :
  Z1 = 50–60 %, Z2 = 60–70 %, Z3 = 70–80 %, Z4 = 80–90 %, Z5 = 90–100 % de (FC max − FC repos),
  ajoutés à la FC repos. Le calcul existe déjà dans `coach/analysis/zones.py` (branche de repli) ;
  il devient la seule branche. Le paramètre `garmin_hr_zones` de `compute_zones` disparaît ;
  `source` contient `"karvonen"`.
- **FC repos** (choix de Claude) : `lastSevenDaysAvgRestingHeartRate` de la réponse
  `get_heart_rates` de Garmin ; repli sur `restingHeartRate` du jour. Une moyenne évite que les
  zones bougent d'un jour à l'autre.
- **FC max** : inchangée (`maxHeartRateUsed` des réglages de zones Garmin, sinon max du jour).
  Les réglages de zones Garmin restent donc lus pour la FC max uniquement.
- **`Metrics.hr_zones`** (choix de Claude) : retiré, plus personne ne le lit.

Exemple (repos 49, max 182) : Z1 116–129, Z2 129–142, Z3 142–155, Z4 155–169, Z5 169–182 bpm.

## Conséquences automatiques

Les séances stockent un nom de zone (« Z2 ») ; les bpm sont résolus à partir des zones courantes
à l'affichage (web), à l'export montre (`coach/export/garmin_workout.py`) et à l'analyse des tours
(`coach/analysis/laps.py`). Les séances existantes prennent les nouvelles valeurs dès la prochaine
synchro, sans régénération.

Exceptions (pas de recalcul automatique) :
- les workouts déjà envoyés sur la montre gardent leurs anciens bpm jusqu'au prochain envoi ;
- les stratégies de course figent leur base (dont les zones FC) à la création : il faut cliquer
  « Actualiser » (page de la course, à côté de « Données Garmin du … ») pour qu'elles prennent
  les nouvelles zones.

## Non-objectifs

- Le « temps par zone » des activités dans les stats (`hr_zones_s`) reste celui de Garmin.
- La composition des séances par le coach (échauffement Z1, EF Z2) ne change pas ; à revoir une
  fois les nouvelles zones constatées.

## Anti-objectifs

- Se retrouver sans zones alors qu'on en avait avant : si la FC repos manque, l'erreur actuelle
  (« FC repos inconnue : synchronise ta montre ») s'applique, comme pour le repli Karvonen actuel.
  Pour qu'une synchro qui marchait avant ne casse pas les jours où Garmin n'a pas encore de FC
  repos, `refresh_snapshot` reprend la FC repos du dernier instantané enregistré.

## Approches envisagées

- **A. FC de réserve** — retenue (choix de l'utilisateur) : simple, toujours calculable.
- **B. % de la FC au seuil lactique** — écartée : seuil pas toujours détecté par Garmin.
- **C. Seuil lactique avec repli FC de réserve** — écartée par l'utilisateur.
- Garder le % de FC max avec des bornes remontées — écartée : repose sur la seule FC max.

## Laissé au constructeur

- Mise à jour des tests (`tests/analysis/test_zones.py`, `tests/garmin/test_client.py`,
  fixtures, tests de services qui passent `hr_zones`).
- Mention éventuelle dans `docs/guide` / README si les zones Garmin y sont décrites.
