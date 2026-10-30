# Page d'accueil « Stats » — statistiques globales Garmin

Date : 2026-10-30
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

Une page d'accueil interactive et très visuelle qui présente des statistiques globales sur
l'ensemble des données Garmin de l'athlète : tous sports en vue d'ensemble, course à pied et
trail en détail, records et compétitions. Elle remplace `#/plan` comme page par défaut dès
qu'au moins une activité est en base.

Principe directeur : **chaque bloc répond à une question utile**. Pas de stats gadget, peu
exploitables ou trompeuses ; un bloc sans données suffisantes l'affiche explicitement au lieu
de montrer un chiffre non représentatif.

### Critères de succès

- Après la première synchro, tout l'historique Garmin est importé en arrière-plan, avec une
  progression visible ; un import interrompu reprend sans doublon.
- Les filtres (période, sport) recalculent toute la page instantanément, sans requête serveur.
- Les records personnels Garmin et les compétitions (détectées ou marquées, avec temps officiel
  et classement saisis) sont affichés.
- La page est utilisable sur PC et sur téléphone (mode LAN), en thème clair et sombre.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| « Les courses » | Course à pied détaillée **et** section compétitions |
| Compétitions | Détection auto (`eventType` = `race` dans Garmin) + marquage et saisie manuels dans l'app |
| Historique | Import complet, une seule fois, en arrière-plan ; synchros suivantes incrémentales |
| Records | Records personnels calculés par Garmin + temps officiels de compétition |
| Autres sports | Vue d'ensemble seulement (volume, répartition, évolution) |
| Architecture | Agrégations côté front (TS pur) + graphiques ECharts |

## 3. Contenu de la page

### 3.1 Filtres

En haut de page, collants au défilement :

- **Période** : 12 derniers mois (défaut), année civile, tout l'historique, dates personnalisées.
- **Sport** : tous, course à pied (route + tapis + trail), trail seul, chacun des autres sports
  pratiqués (liste construite à partir des familles présentes dans les données).

Cliquer une barre du graphique de volume ou une case du calendrier restreint la période à
cette semaine, ce mois ou ce jour. Un bouton « Réinitialiser » revient aux filtres par défaut.
Les filtres choisis sont mémorisés dans `localStorage` (try/catch, valeurs par défaut sinon).

### 3.2 Blocs

1. **Chiffres clés** — *est-ce que j'en fais plus ou moins ?*
   Heures d'activité, distance de course, nombre de séances, D+ total. Chacun avec la variation
   par rapport à la période précédente de même durée (« ▲ +12 % »). Pas de variation affichée
   si la période précédente n'a aucune activité (« — »), ou si la période est « tout
   l'historique ».
2. **Régularité** — *suis-je constant ?*
   Calendrier heatmap (durée par jour) sur la période ; nombre de semaines actives sur le total ;
   série actuelle et série record de semaines consécutives avec au moins une séance (semaines du
   lundi au dimanche, la semaine en cours ne casse pas la série actuelle).
3. **Volume dans le temps** — *comment évolue ma charge ?*
   Barres empilées par famille de sport, agrégées par semaine si la période fait au plus 6 mois,
   par mois sinon ; métrique au choix heures / distance ; moyenne mobile sur 4 périodes en ligne.
   À côté : donut de répartition par sport **en heures**.
4. **Course à pied** — *est-ce que je progresse ?* (masqué si le filtre sport exclut la course)
   - **Efficacité aérobie** : vitesse (m/min) / FC moyenne par sortie, nuage de points dans le
     temps + tendance (régression linéaire). Sorties retenues : famille `run` (pas trail), durée
     ≥ 20 min, FC moyenne présente, D+ ≤ 10 m/km. Tendance affichée à partir de 8 points.
   - **VO2max** estimée par Garmin (`vO2MaxValue` des activités), courbe dans le temps.
   - **Sortie la plus longue par mois** (distance), barres.
   - **Répartition par zones FC** sur la période (cumul des `hrTimeInZone_1..5`), avec repère
     « facile = zones 1-2 ». Masqué si moins de 50 % des sorties de la période ont ces données.
   - **Trail** : D+ cumulé et D+ moyen par km sur la période (si au moins une sortie trail).
5. **Records** — tableau des records personnels Garmin : 1 km, 1 mile, 5 km, 10 km, semi,
   marathon, sortie la plus longue ; avec date, allure, lien vers l'activité sur Garmin Connect.
   Non filtré par période (ce sont des records absolus), mention explicite à l'écran.
6. **Compétitions**
   - Frise / liste chronologique : date, épreuve, distance, temps officiel (à défaut temps montre,
     signalé), allure, classement général et catégorie, et **percentile** (« top 15 % ») quand
     le rang et l'effectif sont connus.
   - Progression des temps pour chaque catégorie de distance courue au moins 2 fois
     (catégories : 5 km, 10 km, semi, marathon à ±3 % ; trail regroupé par distance arrondie
     n'est **pas** comparé, le dénivelé rendant les temps incomparables).
   - Chaque compétition s'édite via `RaceEditDialog`. Un bouton « Ajouter une compétition »
     ouvre la liste des activités `run` et `trail` (les plus récentes d'abord, recherche par nom
     ou date) ; choisir une activité ouvre `RaceEditDialog` pour elle.

### 3.3 Exclu volontairement

Calories (estimation peu fiable), nombre de pas, FC moyenne ou allure moyenne mélangeant route,
trail et autres sports, records calculés sur la distance totale d'une activité, toute tendance
calculée sur trop peu de points.

## 4. Données et back-end

### 4.1 Port Garmin

Ajouts à `GarminPort` (et à `FakeGarminClient`) :

- `activities_page(offset: int, limit: int) -> list[ActivitySummary]` : page de
  `get_activities(start, limit)`, du plus récent au plus ancien ; liste vide en fin d'historique.
- `personal_records() -> list[PersonalRecordSummary]` : `get_personal_record()`, mappé par
  `typeId` (1 = 1 km, 2 = 1 mile, 3 = 5 km, 4 = 10 km, 5 = semi, 6 = marathon, 7 = sortie la plus
  longue ; à vérifier sur une réponse réelle, les autres types sont ignorés).
  `PersonalRecordSummary` : `kind`, `value` (secondes ou mètres), `activity_id`, `date`.

### 4.2 Import de l'historique — `coach/services/history.py`

- `import_history(repo, garmin, on_progress)` : pagine par 100, enregistre les activités absentes
  (même conversion que `_import_activities` de `sync.py`, factorisée dans une fonction commune),
  s'arrête à la première page incomplète (moins de 100 activités). Pause de 1 s entre les pages, en plus du réessai existant
  sur 429. Rafraîchit ensuite les records personnels.
- Lancé dans un thread (un seul à la fois, verrou en mémoire) :
  - automatiquement à la fin d'une synchro réussie si `history.status` vaut `idle` ;
  - à la demande via `POST /api/history/import` (relance aussi après `error` ou `done`).
- État dans un fichier dédié `history.json` du dossier de données (pas dans `settings.json`,
  que `sync` réécrit en entier et écraserait en parallèle) : `status` (`idle` | `running` | `done` | `error`), `imported`
  (nombre d'activités ajoutées), `error` (message ou `null`), `finished_at`. Au démarrage du
  serveur, un état `running` orphelin repasse à `error` (« Import interrompu »).
- Idempotent : relancer reprend simplement, les activités déjà en base sont ignorées.

### 4.3 Normalisation — `coach/stats/normalize.py`

Fonctions pures, calculées à la lecture à partir des colonnes et de `raw_json` (aucune migration
des colonnes existantes) :

- `sport_family(type_key) -> str` : table unique `typeKey` → `run` | `trail` | `bike` | `swim` |
  `strength` | `walk` | `other` (ex. `running`, `treadmill_running`, `track_running` → `run` ;
  `trail_running` → `trail` ; `cycling`, `road_biking`, `mountain_biking`, `indoor_cycling` → `bike`).
- `stat_row(activity, race) -> dict` : `id`, `garmin_id`, `start` (date-heure locale,
  `startTimeLocal`), `name`, `family`, `type_key`, `duration_s`, `distance_m`, `d_plus_m`,
  `avg_hr`, `max_hr`, `vo2max`, `hr_zones_s` (liste de 5 ou `null`), `race` (objet ou `null`).
  `race` est non nul si une ligne `Race` non exclue existe, ou si `eventType.typeKey == "race"`
  et aucune ligne `Race` exclue n'existe.

### 4.4 Nouvelles tables

- `Race` : `id`, `activity_id` (unique, FK logique vers `Activity.id`), `name`,
  `official_time_s`, `overall_rank`, `overall_total`, `category`, `category_rank`,
  `category_total`, `excluded: bool = False`. Tous les champs de saisie sont facultatifs.
- `PersonalRecord` : `id`, `kind`, `value`, `garmin_activity_id`, `date`. Remplacée en entier à
  chaque rafraîchissement (fin d'import, fin de synchro). Un échec Garmin ne vide pas la table.

### 4.5 API

- `GET /api/stats/activities` → `{"activities": [stat_row...]}`, triées par date.
- `GET /api/stats/records` → `{"records": [...], "updated_at": ...}`.
- `PUT /api/races/{activity_id}` : crée ou met à jour la ligne `Race` (`excluded = false`) ;
  validation : rangs ≥ 1, rang ≤ effectif quand les deux sont fournis, temps > 0.
- `DELETE /api/races/{activity_id}` : dé-marque (ligne `Race` avec `excluded = true`, pour ne
  pas être re-détectée).
- `POST /api/history/import` : lance l'import ; `409` si déjà en cours.
- `GET /api/status` gagne `has_activities: bool` et `history: {status, imported, error}`.

## 5. Front-end

- Dépendance : `echarts` (version exacte épinglée), importé de façon modulaire
  (`echarts/core` + `BarChart`, `LineChart`, `PieChart`, `ScatterChart`, `HeatmapChart`,
  composants calendrier / tooltip / grille / dataZoom / légende, renderer SVG).
- `web/src/components/stats/EChart.svelte` : enveloppe (init, `setOption` réactif, resize via
  `ResizeObserver`, thème clair/sombre suivant `prefers-color-scheme` et les variables de
  `app.css`, événement `onclick` remonté).
- `web/src/routes/Stats.svelte` : charge activités + records, détient l'état des filtres, grille
  de blocs (2 colonnes ≥ 900 px, 1 colonne en dessous), bandeau d'import si `history.status`
  vaut `running` ou `error` (bouton « Reprendre »).
- Composants `web/src/components/stats/` : `Filters`, `KpiRow`, `ConsistencyCalendar`,
  `VolumeChart`, `SportDonut`, `RunningProgress`, `Records`, `Races`, `RaceEditDialog`.
  Ils ne calculent rien : ils affichent ce que renvoient les modules ci-dessous.
- Modules purs `web/src/lib/stats/` : `filter.ts` (période, sport, période précédente),
  `kpis.ts`, `consistency.ts` (heatmap, séries de semaines), `volume.ts` (agrégation semaine /
  mois, moyenne mobile, répartition), `running.ts` (efficacité aérobie + régression, VO2max,
  plus longue sortie, zones, trail — avec les seuils nommés en constantes), `races.ts`
  (percentiles, catégories de distance, progression).
- `App.svelte` : route `stats` ajoutée, lien « Stats » en premier dans le menu ; route par
  défaut `#/stats` si `status.has_activities`, sinon comportement actuel.
- `lib/api.ts` : types et appels des nouveaux endpoints.

## 6. Erreurs

- Garmin indisponible ou authentification expirée pendant l'import : `history.status = error`
  avec le message ; les activités déjà importées restent ; le bandeau propose « Reprendre »
  (et renvoie vers les Réglages si l'authentification est en cause).
- `personal_records` est facultatif : en cas d'échec, la table existante est conservée ; si elle
  est vide, le bloc Records affiche « Records indisponibles ».
- Bloc sans données suffisantes : état vide explicite (« Pas assez de données sur cette
  période »), jamais de graphique vide ou de chiffre trompeur.
- Saisie de compétition invalide : erreurs de validation affichées dans le formulaire (format
  d'erreur existant de l'API).

## 7. Tests

- **pytest**
  - `normalize` : familles de sport, champs facultatifs absents, zones FC, détection `race`
    et priorité de la ligne `Race` (dont `excluded`). Fixtures JSON Garmin, dont une réponse
    réelle anonymisée à capturer (comme pour les fixtures existantes).
  - `history` : pagination jusqu'à la page vide, reprise sans doublon, erreur en cours d'import
    (état `error`, activités conservées), verrou (pas deux imports simultanés), état `running`
    orphelin au démarrage.
  - API : nouveaux endpoints, validation des compétitions, champs ajoutés à `/api/status`.
- **Vitest**
  - Chaque module `lib/stats/*` : filtres et période précédente, séries de semaines (semaine en
    cours), bascule semaine / mois, moyenne mobile, exclusions de l'efficacité aérobie et seuil
    de tendance, masquage des zones, percentiles et catégories de distance.
  - Rendu de `Stats.svelte` avec API simulée et ECharts simulé (états vide, import en cours,
    erreur, données).
  - Route par défaut dans `App.test.ts`.

## 8. Hors périmètre

Page statique publique, calcul maison des meilleurs efforts à partir des données seconde par
seconde, analyse détaillée des sports autres que la course, export des statistiques.
