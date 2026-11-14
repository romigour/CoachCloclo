# Version mobile en lecture seule (PWA sur GitHub Pages)

Date : 2026-11-14
Statut : design relu, en attente de validation

## 1. Intention

Sur le téléphone, il n'y a ni Garmin Connect ni Claude : l'appli de bureau ne peut pas y tourner.
L'accès réseau local (LAN + PIN) existe déjà, mais seulement quand le PC est allumé et sur le même
réseau. On veut pouvoir **consulter** son entraînement depuis le téléphone, n'importe où, dès que
les données sont dans la base cloud Turso (mode de stockage cloud déjà en place depuis la 0.9.0).

La version mobile est une PWA installable, hébergée sur GitHub Pages, qui lit **directement** la
base Turso depuis le navigateur. Elle réutilise les écrans Svelte existants : un seul front, deux
builds.

### Critères de succès

- Au premier lancement, la PWA ne demande que l'URL et le jeton Turso ; après validation (la base
  répond et son schéma est connu), ils sont gardés sur le téléphone et l'appli s'ouvre sur
  « Aujourd'hui ».
- « Aujourd'hui », « Plan » et « Statistiques » affichent les mêmes données que l'appli de bureau
  pour la même base.
- Aucune action de création / modification / suppression n'est visible ni possible.
- Depuis un écran « Connexion », on peut modifier l'URL / le jeton, ou les effacer (retour à
  l'écran de saisie).
- Le build de bureau (`coach/web_dist`) est inchangé dans son comportement.

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs (v1)** : écrans Aujourd'hui, Plan (semaine), Statistiques ; écran de connexion
Turso ; écran « Connexion » pour modifier / effacer ; installation PWA ; publication sur Pages.

**Non-objectifs (v1)** :
- Comparaison prévu / réalisé (logique Python lourde dans `coach/services/laps.py`).
- Stratégie de course (`race_strategy.get_race_view` écrit en base à la première lecture),
  Objectifs, Propositions, Réglages de bureau, accueil Garmin/Claude.
- Consultation hors ligne des données (le service worker ne met en cache que la coquille).
- Toute modification côté Python / schéma de la base.

**Anti-objectifs** (échec même si « ça marche ») :
- La PWA écrit quoi que ce soit dans la base, même indirectement.
- Le jeton Turso se retrouve dans le bundle publié, dans une URL ou dans un log.
- Deux jeux d'écrans à maintenir (copies de Today/Plan/Stats pour le mobile).
- Le téléphone télécharge tout le `raw_json` Garmin de chaque activité pour les stats.

## 3. Contraintes constatées dans le code

- Le front n'accède jamais à la base aujourd'hui : tout passe par `web/src/lib/api.ts` → FastAPI
  (`coach/api/app.py`), qui fait requêtes SQL + mise en forme (`_cycle_dict`, `_goal_dict`,
  `_session_dict`, `_event_dict`, `_activity_row`, `stat_row` dans `coach/stats/normalize.py`).
- Appels des écrans visés : `api.status`, `api.plan`, `api.events`, `api.activities(week)`,
  `api.statsActivities`, `api.statsRecords`, `api.zones` (via `loadZones`, pour l'affichage des
  étapes dans `SessionCard`).
- Versions de schéma : `appstate.schema_version` (`{"v": 1}`, `SCHEMA_VERSION` dans
  `coach/plan/repo.py`). Des colonnes ont déjà été ajoutées par `_migrate` sans incrément : la
  vérification de version ne suffit pas à elle seule, d'où la publication alignée sur les
  releases (§ 6).
- GitHub Pages publie déjà le guide depuis `master /docs` (Jekyll, `docs/_config.yml`) à
  `romigour.github.io/CoachCloclo/guide/`. La PWA doit cohabiter avec lui.
- Le build Vite actuel sort dans `../coach/web_dist`, chemins absolus `/`, service worker
  `src/sw.ts` qui ignore `/api`.

## 4. Approches envisagées

**A. Un seul front, source de données échangeable selon le build (retenue).** `api.ts` garde ses
signatures et ses types. Dans le build mobile, les lectures passent par un module qui interroge
Turso (`@libsql/client/web`, HTTP) et reconstruit exactement le JSON de l'API Python ; les
écritures lèvent une erreur ; un indicateur `READONLY` masque les actions. Coût : réécrire en TS
la mise en forme de ces lectures et dépendre du schéma.

**B. Instantané JSON préparé par le bureau.** Le bureau écrit, après chaque écriture, les
réponses JSON dans une table `mobile_snapshot` que la PWA lit telle quelle. Zéro logique en
double, mais un oubli de rafraîchissement donne des données périmées en silence, le JSON des stats
grossit, et il faut une table + migration. Écartée.

Écartées d'emblée : Python dans le navigateur (Pyodide, > 10 Mo, pas de libsql) ; serveur
intermédiaire (perd l'intérêt de Pages).

**Choix de l'utilisateur : A.**

## 5. Design

### 5.1 Build mobile

- `vite build --mode mobile` (script npm `build:mobile`), `import.meta.env.MODE === "mobile"`
  exposé en une constante `READONLY` (`web/src/lib/mode.ts`). Vite élimine le code mort : le
  build de bureau ne contient pas le client libsql.
- Sortie `web/dist-mobile` (ignorée par git), `base: "/CoachCloclo/app/"`.
- Manifest dédié (nom « CoachCloclo », `start_url` / `scope` relatifs à la base) ; icônes
  existantes.
- Service worker : même stratégie (réseau d'abord, coquille en cache), chemins relatifs à la base,
  et ne met **jamais** en cache les requêtes vers Turso (autre origine, déjà ignorée).

### 5.2 Accès aux données (`web/src/lib/turso.ts`)

- Lit `{ url, token }` du stockage local ; crée un client `@libsql/client/web`. Accepte
  `libsql://`, `https://` ou un hôte nu (même normalisation que `turso_host` en Python).
- N'expose que des fonctions de lecture nommées (`status()`, `plan()`, `activities(week)`,
  `statsActivities()`, `statsRecords()`, `zones()`, `checkConnection()`), chacune avec ses
  requêtes `SELECT` écrites en dur. Aucune fonction générique « exécuter du SQL » n'est exportée.
- Chaque fonction renvoie le **même type** que la fonction homonyme d'`api.ts`, construit selon
  les mappers Python correspondants (port fidèle de `_cycle_dict`, `_goal_dict`, `_session_dict`,
  `_event_dict`, `_activity_row`, `stat_row`, des requêtes `Repo` utilisées : `active_cycle`,
  `upcoming_goals`, `past_goals`, `goals_in`, `horizon_goals`, `open_injury`, `sessions`,
  `activities_since`, `all_activities`, `races`, `records`, `latest_snapshot`, `last_done_cycle`,
  `has_activities`, et de `calendar.week_monday`).
- Stats : les champs tirés du `raw_json` (`startTimeLocal`, `activityName`, `maxHR`,
  `vO2MaxValue`, `hrTimeInZone_1..5`, `eventType.typeKey`) sont extraits **dans la requête** avec
  `json_extract`, pour ne pas transférer le JSON brut. Le filtrage `_finite` / `_positive` reste
  côté TS.
- `status()` en lecture seule : `garmin` vaut une valeur neutre (pas de connexion Garmin),
  `llm_mode` sans objet, `history` lu dans `appstate` comme en Python (`load_state`) — affiché
  seulement, jamais relancé.
- « Aujourd'hui » = date locale du téléphone.

### 5.3 Branchement dans `api.ts`

- Les fonctions de lecture ci-dessus délèguent à `turso.ts` quand `READONLY`, sinon `fetch` comme
  aujourd'hui.
- Toutes les autres fonctions lèvent `ApiError("readonly", "Action indisponible en lecture
  seule")` quand `READONLY` (ceinture : l'UI ne doit déjà pas les appeler).
- Erreurs Turso traduites en `ApiError` : jeton refusé (`auth`), base injoignable
  (`unreachable`), schéma trop récent (`schema_too_new`), base pas encore migrée par l'appli de
  bureau (`schema_outdated`, message « Mets à jour l'appli de bureau puis relance-la une fois » ;
  *décision du concepteur*). `checkConnection()` et le démarrage vérifient, via
  `PRAGMA table_info`, que chaque colonne lue par `turso.ts` existe (liste tenue dans
  `turso.ts`) ; une erreur SQL « no such column » en cours d'usage est aussi traduite en
  `schema_outdated`. Les messages sont affichés par
  `ErrorBanner` / la page « Données indisponibles » existante.

### 5.4 Écrans

Les écrans existants sont réutilisés ; les parties d'écriture sont masquées par `{#if !READONLY}` :

- `App.svelte` : routes limitées à `today`, `plan`, `stats`, `connection` ; pas de synchro auto,
  pas de `readSetup`, pas d'`UpdateBanner`, pas de redirection vers Welcome/Setup/Goal. Sans
  connexion enregistrée → écran de connexion. Accueil : `today` si plan accepté, sinon `stats`.
- `Sidebar` : liens Aujourd'hui / Plan / Statistiques / Connexion ; bloc Garmin + bouton de synchro
  masqués ; liens Jour J / Proposition / Objectifs / Réglages masqués.
- `Today` / `Plan` : boutons « Signaler un imprévu », « Générer » masqués ; message « cycle terminé
  → Préparer le cycle suivant » remplacé par un texte sans lien.
- Imprévus (*choix de l'utilisateur*) : `EventList` (Plan) et `InjuryBanner` (Today, Plan) restent
  visibles, sans leurs actions (supprimer, reprise `resumeInjury`, `requestAdjustment`). Ajoute la
  lecture `events()` à `turso.ts` (port de `GET /cycle/events` / `repo.events`, `_event_dict`).
- Proposition en attente (*choix de l'utilisateur*) : `status()` lit `pending_proposal`
  (`pending_proposal_id`) ; la carte de Today devient un texte sans lien « Une proposition
  d'ajustement t'attend sur l'ordinateur ».
- `SessionCard` : envoi montre, changer de jour, retirer, réessayer, correction du rattachement et
  dépliage prévu / réalisé masqués. Les étapes et le statut restent affichés.
- `Stats` : boutons d'import / reprise de l'historique masqués ; édition de course
  (`RaceEditDialog`) masquée.

### 5.5 Écran de connexion (`web/src/routes/Connection.svelte`, mobile seulement)

- Formulaire URL + jeton ; « Valider » appelle `checkConnection()` : lecture de
  `appstate.schema_version` (absente ou > version connue → refus avec message clair). Succès →
  enregistrement local puis accueil.
- Une fois connecté, la même route affiche l'hôte (jeton masqué) et deux actions :
  **Modifier** (formulaire prérempli, revalidé avant remplacement) et **Effacer** (supprime les
  identifiants du téléphone après confirmation, retour au formulaire vide).
- Texte d'aide : recommander un jeton **en lecture seule**
  (`turso db tokens create <base> --read-only`), pour que la base refuse elle-même toute écriture.
- Stockage : `localStorage` (clé dédiée, try/catch). Le jeton n'apparaît jamais dans l'URL ni dans
  les logs.

### 5.6 Publication

- Nouveau workflow `.github/workflows/pages.yml` : déclenché sur les tags `v*`, sur les pushes
  de `master` touchant `docs/` (le guide reste publié aussitôt, comme aujourd'hui) et à la
  demande (`workflow_dispatch`). Il construit le guide depuis le commit déclencheur (`docs/`,
  Jekyll, mêmes exclusions) et la PWA **toujours depuis le dernier tag `v*`** (checkout séparé),
  pour qu'elle corresponde au schéma de l'appli de bureau publiée ; place la PWA sous `app/` et
  déploie avec `actions/deploy-pages`. *Décision du concepteur.*
- Action manuelle de l'utilisateur, une fois : passer la source Pages de « branche master /docs »
  à « GitHub Actions » dans les réglages du dépôt. Le guide reste à `/CoachCloclo/guide/`.
- Seconde action manuelle, une fois : l'environnement `github-pages` n'autorise par défaut que la
  branche par défaut, ce qui bloque les déploiements sur tag. Réglages → Environments →
  `github-pages` → Deployment branches and tags → ajouter une règle autorisant les tags `v*`.
- README + guide : une section « Version mobile » (URL, création du jeton lecture seule).

### 5.7 Tests

- Vitest : `turso.ts` testé contre une base SQLite en mémoire (client libsql `:memory:` côté
  Node) peuplée de données représentatives ; pour chaque lecture, le JSON produit est comparé à
  des fixtures générées par l'API Python sur les **mêmes** données (script de génération + test
  Python qui garde les fixtures à jour), afin de détecter toute divergence de portage.
- Tests de composants : en mode `READONLY`, aucun bouton d'action dans Today / Plan / Stats /
  SessionCard / Sidebar.
- Test `api.ts` : toute fonction d'écriture lève `readonly` en mode mobile.
- CI : ajouter `npm run build:mobile` au workflow `ci.yml`.

## 6. Laissé au builder

- Découpage exact de `turso.ts` (un fichier ou plusieurs par domaine).
- Forme précise de la constante `READONLY` (module, `define` Vite) tant que le code mort est
  éliminé du build de bureau.
- Mécanique de génération des fixtures partagées Python ↔ TS.
- Présentation visuelle de l'écran de connexion, dans le style existant.
