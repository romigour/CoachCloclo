# Prévu / réalisé étape par étape — tours Garmin rapprochés des étapes du workout

Date : 2026-11-01
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

Pour une séance réalisée, mettre chaque étape prévue (échauffement, fractions, récupérations,
retour au calme) en face de ce qui a été couru (durée, distance, allure, FC), l'afficher dans le
détail de la séance et le transmettre à Claude lors de l'ajustement. Aujourd'hui Claude ne voit
qu'une ligne « prévu : titre -> réalisé : résumé global de l'activité ».

### Critères de succès

- Une séance courue avec le workout lancé sur la montre affiche, étape par étape, la cible, le
  réalisé, l'écart de volume et un verdict « dans la cible / trop vite / trop lent » (ou FC trop
  haute / trop basse).
- Une séance courue sans le workout (auto-lap, tours manuels) affiche ses tours bruts, sans
  rapprochement deviné.
- Le prompt d'ajustement contient ce détail pour les séances réalisées de la synchro.
- Une erreur Garmin sur les tours ne fait jamais échouer une synchro ni un rattachement.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Usage de la montre | Les deux cas existent : workout lancé sur la montre, ou course libre |
| Course libre | Mode dégradé : tours bruts affichés et transmis, aucun rapprochement |
| Affichage | Chiffres + verdict par étape, bornes de zone sans tolérance réglable |
| Architecture | Tours récupérés à la synchro, stockés à part, comparaison calculée à la lecture |
| Zones du verdict | Celles du dernier `AthleteSnapshot` (pas d'historique des zones) |

## 3. Récupération et stockage des tours

### 3.1 Port Garmin (`coach/garmin/port.py`, `coach/garmin/client.py`)

Nouveau modèle :

```python
class LapSummary(BaseModel):
    index: int                  # rang du tour dans l'activité, à partir de 0
    duration_s: float
    distance_m: float
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_s_km: float | None = None
    step_order: int | None = None  # étape du workout exécutée, None hors workout
    raw: dict
```

Nouvelle méthode du `GarminPort` : `activity_laps(garmin_id: int) -> list[LapSummary]`.

- `GarminClient` appelle `get_activity_splits(activity_id)` (bibliothèque `garminconnect`) et
  normalise les `lapDTOs`. L'allure vient de `averageSpeed` (m/s) via `_pace_s_km`. Un tour sans
  durée ou distance exploitable est ignoré.
- Le champ portant l'étape du workout (`wktStepIndex` ou équivalent) et sa base (index 0 ou
  `stepOrder` 1) sont confirmés sur une vraie activité avant d'écrire la normalisation
  (`tests/garmin/test_live.py`) ; la fixture `tests/fixtures/garmin/activity_splits.json` en est
  tirée (une activité avec workout, une sans).
- `FakeGarminClient` reçoit un dictionnaire `laps: dict[int, list[LapSummary]]` et passe par
  `_check("activity_laps")` comme les autres lectures.

### 3.2 Stockage (`coach/plan/models.py`, `coach/plan/repo.py`)

Nouvelle table (créée par `create_all` sur les bases existantes, pas de migration) :

```python
class ActivityLaps(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    activity_id: int = Field(unique=True, index=True)
    laps_json: str
    fetched_at: dt.datetime = Field(default_factory=_now)
```

`Repo` gagne `laps(activity_id) -> list[LapSummary] | None` et `save_laps(activity_id, laps)`
(remplacement si une ligne existe déjà).

### 3.3 Quand récupérer

- **Synchro** (`coach/services/sync.py`) : après le rattachement et avant la proposition, pour
  toute activité rattachée à une séance (`session_id` non nul) sans ligne `ActivityLaps`. Cela
  rattrape aussi les rattachements de synchros précédentes.
- **Rattachement manuel** (`POST /activities/{id}/match` avec `session_id` non nul) : récupération
  immédiate si les tours sont absents, après la transaction du rattachement.
- **Pas de récupération** pour l'historique importé ni les activités non rattachées.
- Une erreur Garmin (`GarminUnavailable`, `GarminRateLimited`, `GarminAuthRequired`) sur les tours
  est journalisée puis ignorée : l'activité suivante est traitée, le rattachement est conservé, et
  la synchro suivante réessaie puisque la ligne est toujours absente.

## 4. Rapprochement et verdict (`coach/analysis/laps.py`)

Fonction pure `compare_session(spec: SessionSpec, laps: list[LapSummary], zones: Zones) -> StepComparison`.

### 4.1 Étapes prévues à plat

Les répétitions sont dépliées : `6 × (actif 400 m, récup 200 m)` donne 12 étapes prévues. Chaque
étape à plat porte :

- son libellé de position (`group` = rang de l'élément de premier niveau, `iteration` = numéro de
  répétition ou `None`) ;
- son `StepSpec` ;
- son `step_order` Garmin, calculé exactement comme dans `coach/export/garmin_workout.py` (le
  groupe de répétition prend un numéro avant ses enfants). Ce calcul est extrait dans une fonction
  partagée (`step_orders(spec)` ou équivalent) utilisée par l'export et par le rapprochement, pour
  ne pas dupliquer la numérotation.

### 4.2 Mode workout

Conditions : tous les tours ont un `step_order`, et tous ces `step_order` existent dans le plan.
Sinon, mode dégradé (4.3).

Parcours séquentiel des tours et des étapes prévues :

- un tour dont le `step_order` est celui de l'étape attendue la démarre ;
- des tours consécutifs de même `step_order` (appui manuel sur « tour » pendant une étape) sont
  fusionnés : durée et distance additionnées, allure recalculée, FC moyenne pondérée par la durée,
  FC max = maximum. Exception : si l'étape prévue suivante a le même `step_order` (répétition à une
  seule étape), le tour démarre cette étape au lieu d'être fusionné (voir limites, section 10) ;
- un tour dont le `step_order` correspond à une étape plus loin dans le plan fait passer les étapes
  intermédiaires en « non réalisée » (étape sautée) ;
- les étapes restantes à la fin des tours sont « non réalisées » (workout arrêté avant la fin) ;
- un tour qui ne peut correspondre à aucune étape restante (retour en arrière) fait basculer toute
  la comparaison en mode dégradé, pour ne jamais afficher un rapprochement faux.

### 4.3 Mode dégradé

Au moins un tour sans `step_order`, ou incohérence de structure : `followed_workout = False` et la
liste des tours bruts, sans rapprochement.

### 4.4 Verdict d'une étape réalisée

- Pas de verdict si l'étape n'a pas de zone, ou si la donnée nécessaire manque (FC absente,
  allure absente, zone d'allure demandée alors que `zones.pace` est nul).
- Zone d'allure `[rapide, lente]` (s/km) : `in` si l'allure est dans la plage, `fast` si plus
  rapide, `slow` si plus lente.
- Zone FC `[basse, haute]` (bpm) : `in`, `hr_high` ou `hr_low`.
- Les bornes font foi, sans tolérance. La plage utilisée accompagne le verdict.
- Écart de volume : réalisé contre prévu, en distance si l'étape est définie en distance, en durée
  sinon.

### 4.5 Résultat

```python
class StepResult(BaseModel):
    group: int
    iteration: int | None
    kind: str                      # warmup | active | recovery | cooldown
    planned_duration_s: int | None
    planned_distance_m: int | None
    zone: str | None
    target_low: float | None       # s/km ou bpm selon la zone
    target_high: float | None
    done: bool
    duration_s: float | None
    distance_m: float | None
    avg_pace_s_km: float | None
    avg_hr: int | None
    verdict: Literal["in", "fast", "slow", "hr_high", "hr_low"] | None

class StepComparison(BaseModel):
    followed_workout: bool
    target_kind: str               # "pace" | "hr"
    steps: list[StepResult]        # vide en mode dégradé
    laps: list[LapSummary]         # tours bruts, toujours fournis
```

## 5. API (`coach/api/app.py`)

`GET /sessions/{id}/comparison` :

- 404 si la séance n'existe pas ;
- `{"available": false, "reason": "no_activity"}` si aucune activité n'est rattachée ;
- `{"available": false, "reason": "no_laps"}` si les tours ne sont pas encore récupérés ;
- sinon `{"available": true, ...StepComparison}` (sans `raw` dans les tours).

Endpoint séparé de `/plan` : le plan reste léger, la comparaison n'est calculée qu'à l'ouverture.

## 6. Affichage (`web/src/components/SessionCard.svelte`)

- Pour une séance `done` avec une activité rattachée, et hors `readonly` : un bloc repliable
  « Prévu / réalisé » sous la ligne « Activité : … », replié par défaut ; la requête part au
  premier dépliage.
- Mode workout : une ligne par étape à plat, format compact lisible sur téléphone :
  `3.2 · Actif 400 m · Z5 3:40–3:55/km` → `412 m · 3:48/km · 172 bpm` + pastille de verdict
  (verte « dans la cible », orange « trop vite / trop lent / FC trop haute / FC trop basse », grise
  sans cible). Étape non réalisée en grisé. En tête de chaque répétition, une synthèse
  « 5/6 fractions dans la cible » (étapes `active` avec verdict `in` sur les étapes `active` du
  groupe).
- Mode dégradé : « Séance non suivie sur la montre : tours bruts », puis les tours (n°, distance,
  durée, allure, FC).
- `no_laps` : « Détail par étape disponible après la prochaine synchro ».
- Le formatage (libellés d'étape, plages, verdicts, synthèse de répétition) vit dans
  `web/src/lib/comparison.ts`, testé ; le type de réponse et `api.comparison(sessionId)` dans
  `web/src/lib/api.ts`. Thèmes clair et sombre via les variables CSS existantes.

## 7. Transmission à Claude (`coach/llm/prompts.py`, `coach/services/sync.py`)

- `build_adjustment_prompt` reçoit pour chaque paire réalisée une `StepComparison | None`
  (calculée dans `_propose` avec les zones de la synchro). `None` (tours absents) conserve la ligne
  actuelle.
- Sous la ligne « prévu -> réalisé », un bloc indenté :
  - mode workout : une ligne par étape simple (`échauffement 15 min : 15:02, 5:31/km, 138 bpm`) ;
    une ligne par étape d'une répétition, résumant ses itérations
    (`6× actif 400 m Z5 [3:40–3:55/km] : 3:48, 3:50, 3:52, 3:58 (trop lent), 4:01 (trop lent), non réalisée`),
    la valeur listée étant l'allure pour une cible allure, la FC pour une cible FC ;
  - mode dégradé : « séance non suivie sur la montre, tours : » puis un tour par ligne, plafonné à
    30 tours avec « … N tours de plus ».
- Ajout à la consigne : « Le détail par étape compare le réalisé aux zones cibles ; appuie ton
  analyse dessus quand il est présent. »
- Seules les séances réalisées de la synchro en cours sont détaillées ; l'historique reste en
  résumés.

## 8. Erreurs

| Cas | Comportement |
|---|---|
| Erreur Garmin sur les tours (synchro) | Journalisée, activité suivante, réessai à la synchro suivante |
| Erreur Garmin sur les tours (rattachement manuel) | Rattachement conservé, réponse `ok`, réessai à la synchro |
| Tour malformé | Ignoré à la normalisation |
| Structure incohérente | Mode dégradé |
| Zones d'allure absentes | Pas de verdict d'allure, chiffres affichés |

## 9. Tests

- `tests/analysis/test_laps.py` (TDD) : rapprochement 1:1, fusion de tours manuels, étape sautée,
  workout arrêté avant la fin, retour en arrière → dégradé, tour sans `step_order` → dégradé,
  verdicts allure et FC aux bornes, données manquantes, écart de volume.
- `tests/export/test_garmin_workout.py` : la numérotation partagée produit les mêmes `stepOrder`
  qu'avant.
- `tests/garmin/test_client.py` : normalisation des `lapDTOs` depuis la fixture.
- `tests/services/test_sync.py` : tours récupérés pour les activités rattachées seulement ;
  synchro réussie malgré une erreur sur les tours ; réessai à la synchro suivante ; comparaison
  passée au prompt.
- `tests/api/test_app.py` : `/sessions/{id}/comparison` (disponible, dégradé, `no_activity`,
  `no_laps`, 404) ; récupération des tours au rattachement manuel, y compris en erreur Garmin.
- `tests/llm/test_prompts.py` : rendu des blocs workout, dégradé et plafond de 30 tours.
- `web/src/lib/comparison.test.ts`, `web/src/components/SessionCard.test.ts` : formatage et
  affichage des trois états.
- `tests/garmin/test_live.py` : contrôle manuel des champs réels de `get_activity_splits`.

## 10. Limites connues

- Les verdicts utilisent les zones actuelles, pas celles du jour de l'export.
- Une répétition dont le groupe ne contient qu'une étape, courue avec des appuis manuels sur
  « tour », ne peut pas être distinguée d'itérations successives : les tours sont alors pris comme
  des itérations distinctes.
- Pas de découpage du flux GPS en mode dégradé (option écartée : rapprochement trop souvent faux
  avec un auto-lap au kilomètre).
