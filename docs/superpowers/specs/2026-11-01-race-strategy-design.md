# Stratégie du jour J — plan de course à partir du GPX

Date : 2026-11-01
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

À partir du GPX de l'objectif actif et des données de l'athlète, produire un plan de course :
une prédiction de temps, un découpage en segments (montées, plats, descentes) avec allure et
temps de passage, et, en trail, un plan de ravitaillement avec les barrières horaires.
`coach/analysis/gpx.py` analyse déjà le parcours ; il reste à en tirer ce plan.

### Usages

- **Consulter** le plan dans l'appli les jours précédant la course.
- **L'envoyer à la montre** sous forme de workout « Jour J » programmé le jour de la course.
- **Le transmettre à Claude**, qui ne doit en tenir compte que très légèrement pour orienter
  l'affûtage et les dernières séances.

### Critères de succès

- Avec un GPX et des prédictions Garmin, la page affiche sans saisie un temps prédit et un
  découpage par segment cohérent (montées plus lentes, descentes plus rapides).
- Saisir un temps visé recale tous les temps de passage sur ce temps.
- En trail, les ravitos sont pré-remplis depuis les waypoints du GPX, modifiables, et chaque
  barrière affiche sa marge et un statut (`ok`, `serré`, `hors délai`).
- Le workout envoyé à la montre contient une étape par segment, à la distance, avec une cible
  d'allure (route) ou de FC (trail).
- Les chiffres sont reproductibles : mêmes entrées, même plan.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Calcul | Modèle déterministe en Python (approche A) ; pas d'appel LLM pour le plan |
| Temps | Prédiction calculée + temps visé facultatif qui recale le découpage |
| Ravitos et barrières | Waypoints du GPX pré-remplis, puis saisie et correction manuelles |
| Plan de ravitaillement | Heures de passage et marges + glucides et eau par tronçon |
| Montre | Workout à la distance : cible d'allure sur route, de FC en trail |
| Claude | Une ligne indicative dans les prompts, influence très légère sur l'affûtage |
| Hors périmètre | Texte de stratégie rédigé par Claude, calibration sur l'historique (notés dans la ROADMAP) |

## 3. Architecture

### 3.1 Analyse (pur, sans Garmin ni base)

**`coach/analysis/gpx.py`** — la lecture du fichier est factorisée ; `analyze_gpx` garde son
comportement. Deux fonctions s'ajoutent :

- `profile(data: bytes) -> list[ProfilePoint] | None` : profil lissé (même lissage que
  `analyze_gpx`) rééchantillonné tous les 50 m ; `ProfilePoint(km: float, ele_m: float)`.
  `None` si la trace n'a pas d'altitude.
- `waypoints(data: bytes) -> list[Waypoint]` : les `<wpt>` du GPX, chacun projeté sur le point
  de trace le plus proche ; `Waypoint(name: str, km: float)`. Les waypoints à plus de 200 m de
  la trace sont ignorés.

Les deux lèvent `GpxError` dans les mêmes cas que `analyze_gpx`.

**`coach/analysis/race_plan.py`** (nouveau) — découpage, modèle d'allure, prédiction,
passages aux ravitos, nutrition. Une fonction d'entrée :

```python
def build_race_plan(
    *,
    distance_km: float,
    trail: bool,
    profile: list[ProfilePoint] | None,
    basis: RaceBasis,          # prédictions Garmin, allure seuil, zones FC, date de capture
    settings: RaceSettings,    # temps visé, heure de départ, nutrition, ravitos
) -> RacePlan
```

`RacePlan` contient : temps prédit (ou `None`), temps visé, distance équivalente, segments,
passages aux ravitos, tronçons de nutrition, avertissements.

### 3.2 Stockage

Nouvelle table **`RaceStrategy`** (une par objectif, `goal_id` unique). L'appli crée ses
tables par `create_all` sans migration : une nouvelle table se crée seule, alors qu'une colonne
ajoutée à `Goal` ou `AthleteSnapshot` casserait les bases existantes.

| Colonne | Contenu |
|---|---|
| `goal_id` | objectif lié |
| `target_time_s` | temps visé, facultatif |
| `start_time` | heure de départ (`HH:MM`), défaut `08:00` |
| `carbs_g_h` | glucides par heure, défaut 60 |
| `water_ml_h` | eau par heure, défaut 500 |
| `carry_ml` | contenance emportée, défaut 1 000 |
| `aid_stations_json` | liste de ravitos (km, nom, type, barrière, arrêt) |
| `basis_json` | données de référence : prédictions 5 km / 10 km / semi / marathon, allure seuil, zones FC, date de capture |
| `garmin_workout_id`, `garmin_schedule_id` | workout exporté |
| `pending_old_workout_id`, `pending_old_schedule_id` | ancien workout restant à supprimer |
| `export_error` | dernier échec d'export, effacé au succès |

Les données de référence sont capturées à la création de la stratégie et à la demande
(« Actualiser avec mes dernières données »). La page s'affiche sans appeler Garmin et les
chiffres ne changent pas d'eux-mêmes. Le plan calculé n'est pas stocké : il est recalculé à
chaque lecture (quelques millisecondes).

Le port Garmin `Metrics` gagne `pred_5k_s`, `pred_half_s` et `pred_marathon_s` (lus dans
`get_race_predictions`, aujourd'hui seul `time10K` est lu).

### 3.3 Service et API

`coach/services/race_strategy.py` : lecture (création à la première lecture, avec capture de la
base et pré-remplissage des ravitos depuis le GPX), enregistrement des réglages, actualisation
de la base, réimport des ravitos, export Garmin.

| Route | Rôle |
|---|---|
| `GET /api/goals/{id}/race-plan` | réglages + plan calculé |
| `PUT /api/goals/{id}/race-plan` | enregistre les réglages, renvoie le plan recalculé |
| `POST /api/goals/{id}/race-plan/refresh` | recapture la base depuis Garmin |
| `POST /api/goals/{id}/race-plan/reimport` | remplace les ravitos par les waypoints du GPX |
| `POST /api/goals/{id}/race-plan/export` | envoie le workout, programmé à la date de course |

Seul l'objectif actif est accepté (`GoalError` sinon, comme pour le plan).

### 3.4 Sans GPX

La page fonctionne : découpage en tranches de distance régulières, sans profil ni graphique,
sans ravitos importés (saisie manuelle possible en trail). Si `gpx_path` pointe vers un fichier
disparu, même comportement, avec un avertissement.

## 4. Modèle de calcul

### 4.1 Distance équivalente à plat

Pour chaque pas de 50 m du profil, de pente `i` (fraction, bornée à ±0,45) :

- coût de Minetti `C(i) = 155,4 i⁵ − 30,4 i⁴ − 43,3 i³ + 46,3 i² + 19,5 i + 3,6` (J/kg/m) ;
- multiplicateur `m(i) = C(i) / C(0)`, borné entre **0,8** (une descente raide n'est pas
  « gratuite ») et **6**.

Distance équivalente `D_eq = Σ longueur × m`. Ordres de grandeur : un km à +10 % ≈ 1,66 km
plat, un km à −5 % ≈ 0,8 km plat. Sans profil, `D_eq` = distance.

### 4.2 Temps de course prédit

1. Référence : la prédiction Garmin (5 km, 10 km, semi, marathon) dont la distance est la plus
   proche de `D_eq`.
2. Riegel : `T = T_ref × (D_eq / D_ref)^1,06`. Au-delà de 42,195 km équivalents, la portion
   restante utilise l'exposant **1,10** : `T = T_42 × (D_eq / 42,195)^1,10`, où `T_42` est le
   temps à 42,195 km obtenu avec 1,06.
3. Repli sans prédiction : allure marathon = allure seuil × 1,09, puis Riegel depuis 42,195 km.
4. Ni prédiction ni allure seuil : pas de temps prédit (avertissement « Saisis un temps visé
   pour obtenir le découpage »).

### 4.3 Temps total et temps visé

- Arrêts = somme des arrêts prévus aux ravitos (trail uniquement).
- Temps total prédit = temps de course prédit + arrêts.
- Temps visé saisi : il remplace le total ; temps de course = temps visé − arrêts (refusé s'il
  est ≤ aux arrêts).
- Les temps de passage sont calculés sur le temps de référence : le visé s'il est saisi, sinon
  le prédit.

### 4.4 Segments

1. Chaque pas est classé selon la pente moyenne glissante sur 200 m : **montée** (> +3 %),
   **descente** (< −3 %), **plat** sinon.
2. Les pas consécutifs de même type sont fusionnés.
3. Un segment de moins de 500 m est absorbé par son voisin le plus long.
4. Tant qu'il y a plus de 25 segments, le plus court est fusionné avec son voisin le plus
   court ; le type du segment fusionné est celui qui domine en distance.
5. Sans profil : tranches de 1, 2 ou 5 km (la plus petite qui donne au plus 25 tranches), de
   type plat.

### 4.5 Par segment

- Temps = temps de course × (`D_eq` du segment / `D_eq` totale).
- Allure moyenne = temps / longueur ; passage cumulé (arrêts des ravitos franchis inclus) ;
  heure de passage = heure de départ + cumul.
- D+, D-, pente moyenne.
- Cible montre :
  - **route** : allure du segment ± 5 s/km ;
  - **trail** : zone de course selon la durée totale de référence — **Z4** sous 1 h 30, **Z3**
    jusqu'à 4 h, **Z2** au-delà — en montée et sur le plat ; la zone inférieure en descente.

## 5. Ravitos, barrières et nutrition (trail)

### 5.1 Ravitos

- Champs : `km`, `name`, `kind` (`eau` | `complet`), `cutoff` (heure du jour `HH:MM`,
  facultative), `stop_min` (défaut 1 pour `eau`, 3 pour `complet`).
- À la création, pré-remplis depuis les waypoints (`kind` = `complet`). Ensuite, les waypoints
  ne sont relus que sur « Réimporter depuis le GPX ».
- Validation : `0 < km < distance`, `cutoff` au format `HH:MM`, `stop_min ≥ 0`. Les ravitos
  sont triés par km.

### 5.2 Passages et barrières

- Heure d'arrivée = heure de départ + temps cumulé interpolé au km du ravito dans son segment +
  arrêts des ravitos précédents.
- Marge = barrière − arrivée. Statut : `ok` (> 30 min), `serré` (0 à 30 min), `hors délai`
  (< 0).
- Calculés pour le temps prédit **et** pour le temps visé s'il est saisi.
- Une barrière `hors délai` sur le temps prédit produit un avertissement en tête de page.
- Une barrière est une heure du jour sur la journée de départ ; une course qui passe minuit
  n'est pas gérée (hors périmètre).

### 5.3 Nutrition par tronçon

Tronçons : départ → ravito 1 → … → dernier ravito → arrivée. Pour chacun : durée prévue,
glucides = durée × `carbs_g_h`, eau = durée × `water_ml_h`, et une alerte si l'eau dépasse
`carry_ml`. Pas de recommandation de produits.

Sur route, ravitos et nutrition ne sont pas affichés.

## 6. Écran « Jour J »

Route `#/race`, entrée « Jour J » dans la barre latérale, visible dès qu'un objectif est actif.

- **En-tête** : temps prédit avec la date des données de référence et le bouton
  « Actualiser » ; champ temps visé ; heure de départ ; allure moyenne ; D+ en trail ;
  avertissements.
- **Profil** (ECharts, si GPX avec altitude) : altitude selon le km, segments colorés par
  type, repères verticaux aux ravitos.
- **Segments** : n°, type, km début → fin, D+/D-, pente, allure, temps, passage cumulé, heure,
  cible montre.
- **Trail** : tableau des ravitos modifiable sur place (km, nom, type, barrière, arrêt, heure
  prévue, marge, statut coloré), bouton « Réimporter depuis le GPX », nutrition par tronçon.
- **Enregistrer** : le `PUT` renvoie le plan recalculé ; tant que ce n'est pas fait, les champs
  modifiés sont signalés et les chiffres affichés sont les précédents.
- **Envoyer à la montre** : état de l'export (envoyé, erreur).

## 7. Export vers la montre

- Workout « Jour J – <distance> km », programmé à `race_date`.
- Une étape `interval` par segment, condition de fin à la distance du segment.
- Cible : allure (`pace.zone`, m/s, borne lente d'abord) sur route ; FC (`heart.rate.zone`,
  bornes en bpm de la zone) en trail.
- Note de l'étape : type, D+ et temps visé du segment, par exemple « Montée +450 m – viser
  52 min ».
- Pas d'étape pour les ravitos ; leur arrêt est compté dans le passage cumulé.
- Ré-export : le nouveau workout est envoyé et programmé d'abord ; l'ancien est ensuite
  supprimé. Si cette suppression échoue, ses ids passent dans `pending_old_*` et la suppression
  est retentée au prochain export. Si l'envoi échoue, l'ancien workout reste en place,
  `export_error` est renseigné et l'erreur est remontée par le mécanisme d'erreurs existant.

## 8. Claude

Si une stratégie existe pour l'objectif, `build_generation_prompt` et `build_adjustment_prompt`
reçoivent une seule ligne, par exemple :

> Stratégie jour J (indicative) : temps prévu 5 h 12, visé 5 h 00 ; montées clés km 12 (+450 m)
> et km 31 (+600 m). N'en tenir compte que pour orienter légèrement le contenu de l'affûtage,
> sans modifier la structure ni le volume du plan.

Les « montées clés » sont les trois plus gros D+ parmi les segments de montée. Rien d'autre ne
change côté LLM.

## 9. Erreurs

| Cas | Comportement |
|---|---|
| GPX illisible | `invalid_gpx` (422), comme aujourd'hui |
| Fichier GPX disparu | mode sans GPX + avertissement |
| Ni prédiction ni allure seuil | plan sans temps prédit + avertissement ; tout fonctionne avec un temps visé |
| Base de plus de 30 jours | avertissement suggérant « Actualiser » |
| Saisie invalide | erreurs de validation au format `_invalid` existant, par champ |
| Temps visé ≤ arrêts | erreur de validation sur le temps visé |
| Échec Garmin à l'actualisation ou à l'export | erreurs Garmin existantes ; `export_error` pour l'export |
| Objectif absent ou archivé | `GoalError` (« Objectif introuvable ou archivé ») |

## 10. Tests

- `tests/analysis/test_race_plan.py` : multiplicateur de Minetti (plat = 1, bornes) ; Riegel et
  bascule à l'exposant 1,10 ; repli allure seuil ; découpage (fusion, absorption, plafond de
  25, tranches sans profil) ; remise à l'échelle sur le temps visé ; interpolation des passages
  et statuts de barrière ; nutrition et alerte de contenance ; zones FC selon la durée.
- `tests/analysis/test_gpx.py` : `profile` et `waypoints`, avec un nouveau fixture
  `trail_wpt.gpx` généré par `make_fixtures.py` (montée, descente, deux waypoints dont un hors
  trace).
- `tests/services/test_race_strategy.py` : création avec pré-remplissage des ravitos,
  enregistrement puis lecture, actualisation (faux Garmin), réimport, export et ré-export
  (suppression de l'ancien, `pending_old_*` en cas d'échec).
- `tests/export/` : JSON du workout de course (étapes à la distance, cibles allure ou FC,
  notes).
- `tests/garmin/test_client.py` : lecture des quatre prédictions.
- `tests/api/test_app.py` : les cinq routes, objectif archivé, validation.
- `tests/llm/test_prompts.py` : ligne « Stratégie jour J » présente ou absente.
- Front (Vitest) : formatage des temps et heures ; page en route (sans ravitos) et en trail
  (avec) ; signalement des modifications non enregistrées.
