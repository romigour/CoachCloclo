# Coach — plan d'entraînement running/trail local, Garmin + Claude

Date : 2026-10-27
Statut : design validé, en attente de relecture de la spec

## 1. Objectif

Application installée localement par chaque utilisateur, qui génère un plan d'entraînement
route ou trail avec Claude à partir des données Garmin Connect de l'athlète, l'ajuste après
chaque séance (avec validation de l'utilisateur) et exporte les séances choisies dans le
calendrier Garmin Connect.

### Critères de succès

- Installation en une commande ; `coach doctor` confirme que tout fonctionne (Claude, Garmin).
- Un objectif saisi (avec GPX facultatif) produit un plan complet jusqu'à la date de course.
- Une séance exportée apparaît dans le calendrier Garmin Connect à la date choisie et se
  synchronise sur la montre comme workout structuré.
- Après une synchro, une proposition d'ajustement justifiée est affichée ; rien ne change
  (plan ni Garmin) sans acceptation.
- Les tokens Garmin et les données ne quittent jamais la machine (hors appels à Garmin et à Claude).

## 2. Périmètre et hypothèses

- Un athlète par installation, un objectif actif à la fois.
- Interface en français. Windows, macOS, Linux.
- Claude appelé via le CLI `claude` en mode headless, connecté au compte de l'utilisateur.
  Mode alternatif : clé API Anthropic. Chaque utilisateur installe et connecte lui-même son
  CLI ; l'application ne gère jamais d'identifiants Claude.
- Pas de service permanent : la synchro a lieu à l'ouverture de l'app et via un bouton.
- Hors périmètre : multi-athlètes, plusieurs objectifs simultanés, renforcement musculaire,
  nutrition, hébergement cloud.

## 3. Architecture

Un paquet Python unique (`coach`), installé avec `uv`. La commande `coach start` lance un
serveur FastAPI qui sert l'API et le front compilé, puis ouvre le navigateur. Données dans le
dossier utilisateur de l'OS (`platformdirs`) : base SQLite, tokens Garmin, fichiers GPX.

```
coach/
├── cli.py          start, doctor [--fix], login-garmin, update
├── doctor/         vérifications d'installation et de connexion
├── garmin/         seul module qui appelle Garmin (python-garminconnect, version figée)
│   ├── auth.py       login + MFA, stockage et renouvellement des tokens
│   ├── reader.py     activités, VO2max, seuil, FC max/repos, zones, statut d'entraînement
│   └── workouts.py   créer, planifier, déplacer, supprimer un workout
├── analysis/       code pur, sans réseau
│   ├── zones.py      zones d'allure et de FC dérivées des métriques Garmin
│   ├── gpx.py        distance, D+, profil, montées, pentes, résumé textuel
│   └── compliance.py prévu vs réalisé, rattachement activité↔séance, charge récente
├── llm/
│   ├── provider.py   LLMProvider ; ClaudeCliProvider, AnthropicApiProvider
│   ├── prompts.py    contexte de génération et d'ajustement
│   └── schemas.py    modèles Pydantic des réponses
├── plan/           modèle métier, stockage SQLite, cycle de vie des propositions
├── export/         Session → JSON workout Garmin (code pur)
├── api/            routes FastAPI
└── web/            front Svelte + Vite, PWA, compilé et embarqué dans le paquet
```

Règles :
- Seul `garmin/` parle à Garmin, seul `llm/` parle à Claude. `analysis/`, `export/` et `plan/`
  sont testables sans réseau.
- Le front ne parle qu'à l'API locale et ne voit jamais de token.
- Écoute sur `127.0.0.1` par défaut. Option `--lan` pour un accès depuis le téléphone, protégée
  par un code PIN défini au premier lancement (cookie de session après saisie).

### Rôle de Claude (approche « Python calcule, Claude décide, Python exécute »)

1. Python prépare un contexte compact : métriques et zones, historique résumé des 8 dernières
   semaines, objectif, résumé GPX, et pour un ajustement les séances prévues/réalisées et à venir.
2. Claude renvoie un JSON strict conforme à `schemas.py`.
3. Python valide (Pydantic), applique et convertit vers Garmin.

Claude n'a accès à aucun outil et n'appelle jamais Garmin.

## 4. Modèle de données

| Entité | Champs principaux |
|---|---|
| **AthleteSnapshot** | date, vo2max, fc_max, fc_repos, fc_seuil, allure_seuil, zones (JSON). Un par synchro. |
| **Goal** | type (`route`/`trail`), distance_km, d_plus_m, race_date, sessions_per_week, gpx_path, gpx_summary (JSON), status (`active`/`archived`) |
| **Session** | goal_id, week_index, order, suggested_day, chaining_note, type (`EF`, `seuil`, `VMA`, `côtes`, `sortie_longue`, `récup`), target_kind (`pace`/`hr`), steps (JSON), est_duration_min, est_distance_km, status (`todo`/`exported`/`done`/`missed`/`sync_error`), scheduled_date (nullable), garmin_workout_id, garmin_schedule_id |
| **Activity** | garmin_activity_id, date, résumé (JSON : durée, distance, D+, FC moy, allure moy, laps), session_id (nullable), match_source (`auto`/`manual`) |
| **Proposal** | created_at, analysis (texte), changes (JSON : liste de `{op: modify/add/remove, session_id?, session?, reason}`), status (`pending`/`accepted`/`rejected`/`stale`) |

Pas de versionnement du plan : l'historique des propositions acceptées en tient lieu.

Cibles d'intensité : allure pour la route et le fractionné sur plat ; FC pour le trail, les
côtes et l'endurance fondamentale. Claude choisit `target_kind` par séance, mais les valeurs
proviennent uniquement des zones calculées dans `analysis/zones.py` (Claude référence une zone,
Python la traduit en bornes).

## 5. Flux

### 5.1 Premier lancement
`doctor` → connexion Garmin dans l'interface (MFA si besoin) → premier AthleteSnapshot.

### 5.2 Création d'objectif
Formulaire (type, distance, D+, date, séances/semaine, GPX facultatif) → analyse GPX locale →
appel Claude « génération » → plan complet en semaines de séances ordonnées, sans dates →
l'utilisateur relit et valide (ou demande une régénération) → séances en `todo`.

### 5.3 Export manuel vers Garmin
Dans la vue Semaine, chaque séance a « Exporter vers Garmin » : sélecteur de date limité aux
jours de sa semaine, jour conseillé présélectionné.
- Avertissement non bloquant si deux séances dures (`seuil`, `VMA`, `côtes`, `sortie_longue`)
  sont à moins de 48 h.
- Déplacer une séance exportée : nouvelle planification puis retrait de l'ancienne.
- Retirer du calendrier : suppression côté Garmin, retour à `todo`.

### 5.4 Synchro (ouverture de l'app ou bouton)
1. Récupération des activités de course depuis la dernière synchro + nouvel AthleteSnapshot.
2. Rattachement :
   - séance `exported` : activité du même jour, à ±1 jour ;
   - séance `todo` : activité libre de la même semaine la plus proche en type et durée,
     suggérée (`match_source=auto`), corrigeable en un clic.
   Une séance rattachée passe en `done` (le workout Garmin éventuel reste dans le calendrier).
3. Semaine terminée : séances sans activité → `missed`.
4. Si au moins une activité rattachée ou une séance `missed` depuis la dernière proposition :
   appel Claude « ajustement » → Proposal `pending`. Une seule `pending` à la fois ; une
   nouvelle synchro avec du nouveau passe l'ancienne en `stale`.

### 5.5 Validation d'une proposition
- Accepter : modifications appliquées en base dans une transaction. Séances `todo` modifiées
  en base seulement ; séances `exported` remplacées côté Garmin à la même date.
- Refuser : aucun changement.

## 6. Gestion des erreurs

**Garmin**
- Token expiré : renouvellement silencieux, sinon bandeau « Reconnexion Garmin requise ».
- 429 : une seule nouvelle tentative différée, puis message ; jamais de boucle.
- Remplacement/déplacement : créer et planifier le nouveau d'abord, supprimer l'ancien ensuite.
  Échec → séance `sync_error` avec bouton « Réessayer ».
- Erreurs inattendues confinées à `garmin/`, message clair, diagnostic via `doctor`.

**Claude**
- `claude -p` en sous-processus, prompt sur stdin, sortie JSON, outils désactivés, délai 180 s.
- JSON invalide ou non conforme : une nouvelle tentative avec l'erreur de validation, puis
  message + « Réessayer ».
- Limite d'abonnement atteinte : message explicite (réessayer plus tard ou passer en clé API).

## 7. Installation et mise à jour

- `install.ps1` (Windows) / `install.sh` (macOS, Linux), lancés en une ligne :
  installe `uv` si absent → `uv tool install coach` → installe le CLI Claude via l'installeur
  natif d'Anthropic si absent → `coach doctor --fix` → `coach start`.
- Le front est compilé en CI et livré dans le paquet : pas de Node chez l'utilisateur.
- `coach doctor` : Python/uv ; garminconnect importable et à la version attendue ; CLI `claude`
  présent ; `claude` connecté (petit appel réel) ; tokens Garmin valides (appel léger) ; dossier
  de données accessible en écriture ; port libre. Chaque échec propose une correction
  (appliquée avec `--fix` quand c'est automatisable).
- `coach update` → `uv tool upgrade coach`.

## 8. Tests

- pytest sur le code pur : zones, analyse GPX (fichiers de test), rattachement, avertissement
  48 h, conversion Session → JSON Garmin (comparée à des workouts Garmin réels anonymisés),
  validation des schémas.
- `FakeGarminClient` et `FakeLLMProvider` pour les flux complets et les cas d'erreur (réponse
  invalide puis nouvelle tentative, échec au milieu d'un remplacement).
- API : `TestClient` FastAPI. Front : Vitest sur les composants à logique (sélecteur de date,
  avertissement).
- Tests réels opt-in (`pytest -m live`) contre un vrai compte Garmin et le vrai CLI Claude ;
  jamais en CI.
- CI GitHub Actions sur Windows, macOS, Linux : tests + script d'installation jusqu'à `doctor`.
