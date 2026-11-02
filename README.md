# CoachCloclo

Application locale qui génère tes plans d'entraînement running/trail à partir de tes données Garmin, avec Claude. Tout tourne sur ta machine ; tes données ne quittent pas ton ordinateur (hormis les appels à Garmin et à Claude).

La page **Stats** (page d'accueil dès que des activités sont importées) donne une vue d'ensemble de toutes tes activités Garmin : chiffres clés, régularité, volume, progression en course, records et compétitions, avec des filtres par période et par sport. Elle ne demande pas d'objectif : la synchronisation importe tes activités dès que Garmin est connecté, puis l'historique complet est importé en arrière-plan (reprise possible après une interruption, et « Réimporter l'historique » dans les Réglages).

**Disponibilités, imprévus et vélo.** À la création de l'objectif (et dans « Modifier l'objectif »), tu coches les jours où tu peux t'entraîner et, si tu veux, le jour de ta sortie longue : le plan ne place aucune séance ailleurs. Quand la vie s'en mêle, « Signaler un imprévu » enregistre une indisponibilité (vacances, déplacement), une blessure ou une maladie (avec ou sans date de reprise), une semaine allégée ou une fatigue : Claude propose aussitôt un ajustement, que tu valides ou refuses (refusé, le plan reste inchangé et l'imprévu reste enregistré). Pendant un arrêt sans date de reprise, la synchronisation ne propose plus d'ajustement ; « Signaler la reprise » produit une proposition de reprise progressive. Enfin, la case « Inclure du vélo » autorise Claude à remplacer au plus une séance facile par semaine par du vélo d'endurance douce (FC en zones 1-2), exporté sur la montre comme workout vélo et rattaché à l'activité vélo correspondante.

Prochaines idées d'amélioration : voir [ROADMAP.md](ROADMAP.md).

## Installation

### Windows (recommandé)

Télécharge `CoachCloclo-Setup-x.y.z.exe` depuis la [dernière release GitHub](https://github.com/romigour/CoachCloclo/releases/latest) et lance-le. L'installateur n'est pas signé : Windows SmartScreen peut afficher un avertissement, clique sur « Informations complémentaires » puis « Exécuter quand même ».

L'installation se fait pour ton compte seulement (aucun droit administrateur) et crée une icône sur le bureau. L'application démarre sans console, ouvre ton navigateur et place une icône près de l'horloge (menu : Ouvrir CoachCloclo, Vérifier les mises à jour, Quitter). Si le port 8765 est occupé, elle utilise un port entre 8766 et 8775.

Au premier lancement, un écran d'accueil installe et connecte Claude (avec ton abonnement) sans passer par un terminal, puis connecte Garmin. Tu peux cliquer sur « Passer pour l'instant » pour l'étape Claude.

Journal : `%LOCALAPPDATA%\CoachCloclo\CoachCloclo\logs\coachcloclo.log`.

### Installation avancée (terminal)

- **Windows (PowerShell)** : `irm https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.ps1 | iex`
- **macOS / Linux** : `curl -LsSf https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.sh | bash`

Le script installe `uv` si besoin, installe CoachCloclo à partir de la wheel de la [dernière release GitHub](https://github.com/romigour/CoachCloclo/releases/latest) (front déjà compilé), lance `coach doctor --fix`, puis `coach start` si tout est vert. Il ne te demande jamais d'identifiant lui-même : `doctor --fix` ouvre `claude` dans ton terminal (« Connecte-toi dans Claude puis tape /exit pour revenir »), puis `coach login-garmin` (connexion Garmin, avec MFA éventuel), et revérifie tout.

Options : `COACH_SOURCE` (chemin ou URL d'une wheel, à la place de la dernière release), `COACH_INSTALL_NO_START=1` (ne lance pas l'app), `COACH_INSTALL_OFFLINE=1` (doctor sans Claude ni Garmin, pour la CI), `--dry-run` / `-DryRun` ou `COACH_DRY_RUN=1` sous PowerShell (affiche les commandes sans les exécuter).

## Mise à jour

Avec l'installateur Windows, un bandeau « Version x.y.z disponible — Mettre à jour » s'affiche au lancement. Tu peux aussi passer par le menu de l'icône près de l'horloge ou par le bouton dans les Réglages. Un clic télécharge le nouvel installateur, vérifie son SHA-256, l'installe en silence et relance l'application. Le dossier de données n'est touché ni par les mises à jour ni par la désinstallation.

Pour tester une mise à jour sur un fork : `COACH_UPDATE_REPO=owner/repo`.

## Commandes

- `coach start [--lan] [--port N] [--no-browser]` : lance l'application sur http://127.0.0.1:8765.
- `coach doctor [--fix] [--offline]` : vérifie l'installation.
- `coach login-garmin` : (re)connexion à Garmin.
- `coach update` : réinstalle la wheel de la dernière release GitHub (installation par terminal).

La commande `coachcloclo` est un alias de `coach`.

## Ce que vérifie `coach doctor`

Python (>= 3.12), bibliothèque `garminconnect`, CLI `claude` installé, connexion Claude valide, tokens Garmin valides, dossier de données accessible en écriture, port 8765 libre. `--fix` corrige ce qui peut l'être : installation du CLI Claude, connexion Claude (lance `claude` en interactif ; connecte-toi puis tape `/exit`), connexion Garmin (`coach login-garmin`), création du dossier ; puis il revérifie. En mode clé API, la connexion Claude se règle dans les réglages de l'app. `--offline` saute les vérifications Claude et Garmin.

## Mode LAN et PIN

Avec la version installée Windows, le bloc « Accès depuis ton téléphone » des Réglages active l'écoute sur tout le réseau local et permet de définir le PIN (4 à 12 chiffres). Au premier passage, le pare-feu Windows demande une autorisation : coche « Réseaux privés ». Depuis le téléphone, ouvre l'adresse affichée dans ce bloc des Réglages (`http://<ip>:<port>`). Sans le mode LAN, seule ta machine peut accéder à l'app.

Cet interrupteur n'existe que dans la version installée Windows : sous `coach start`, le mode LAN s'active avec `coach start --lan` (le PIN se définit à l'invite au premier lancement).

Le PC lui-même n'a plus besoin du PIN (y compris avec `coach start --lan`) ; seul le PC peut activer ou désactiver le mode LAN et changer le PIN.

Note : depuis un téléphone, via `http://<ip>:<port>` en http simple (`--lan`), les navigateurs n'installent pas la PWA et n'enregistrent pas le service worker (contexte sécurisé requis). L'application fonctionne quand même dans le navigateur.

## Données et tokens

Dossier de données (surchargeable avec `COACH_HOME`) :

- Windows : `%LOCALAPPDATA%\CoachCloclo\CoachCloclo`
- macOS : `~/Library/Application Support/CoachCloclo`
- Linux : `~/.local/share/CoachCloclo`

Il contient `coach.db` (base SQLite), `settings.json` (réglages, hash du PIN) et `garmin/` (tokens Garmin). Les tokens ne sont jamais envoyés ailleurs que chez Garmin ; ne partage pas ce dossier.

## Usage de Claude

L'application appelle **ton propre CLI Claude Code** avec **ton propre abonnement**. C'est prévu pour un usage personnel : vérifie les conditions d'utilisation d'Anthropic pour ton cas. Alternative : renseigner une clé API Anthropic dans les réglages de l'app.

## Données réelles à vérifier

À confirmer lors de la première utilisation réelle :

- `tests/fixtures/garmin/*.json` sont **synthétiques** : à remplacer par des réponses réelles (par ex. via `get_workout_by_id`) ou à valider avec les tests live.
- L'unité de la vitesse seuil renvoyée par Garmin (m/s supposé).
- La clé d'identifiant des séances planifiées (schedule id).

Tests live : `uv run pytest -m live` (lecture seule). Les tests qui écrivent sur Garmin exigent en plus `COACH_LIVE_WRITE=1`.

## Développement

```
cd web && npm ci && npm test && npm run build   # produit coach/web_dist/
uv run pytest
uv build                                        # la wheel embarque coach/web_dist/
```

## Publier une version

Les installeurs récupèrent la dernière release GitHub (wheel et installateur Windows). Pour en publier une, mets à jour `version` dans `pyproject.toml`, puis pousse un tag qui vaut `v` + cette version :

```bash
git tag v0.2.0
git push origin v0.2.0
```

Le workflow `release.yml` a trois jobs : `build` (compile le front et construit la wheel), `windows` (construit `CoachCloclo-Setup-<v>.exe` et son `.sha256`) et `publish` (attache le tout à la release). Un déclenchement manuel (`workflow_dispatch`) construit l'installateur sans rien publier : il est disponible dans l'artefact `installer`.
