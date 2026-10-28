# CoachCloclo

Application locale qui génère tes plans d'entraînement running/trail à partir de tes données Garmin, avec Claude. Tout tourne sur ta machine ; tes données ne quittent pas ton ordinateur (hormis les appels à Garmin et à Claude).

Prochaines idées d'amélioration : voir [ROADMAP.md](ROADMAP.md).

## Installation (une commande)

- **Windows (PowerShell)** : `irm https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.ps1 | iex`
- **macOS / Linux** : `curl -LsSf https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.sh | bash`

Le script installe `uv` si besoin, installe CoachCloclo à partir de la wheel de la [dernière release GitHub](https://github.com/romigour/CoachCloclo/releases/latest) (front déjà compilé), lance `coach doctor --fix`, puis `coach start` si tout est vert. Il ne te demande jamais d'identifiant lui-même : `doctor --fix` ouvre `claude` dans ton terminal (« Connecte-toi dans Claude puis tape /exit pour revenir »), puis `coach login-garmin` (connexion Garmin, avec MFA éventuel), et revérifie tout.

Options : `COACH_SOURCE` (chemin ou URL d'une wheel, à la place de la dernière release), `COACH_INSTALL_NO_START=1` (ne lance pas l'app), `COACH_INSTALL_OFFLINE=1` (doctor sans Claude ni Garmin, pour la CI), `--dry-run` / `-DryRun` ou `COACH_DRY_RUN=1` sous PowerShell (affiche les commandes sans les exécuter).

## Commandes

- `coach start [--lan] [--port N] [--no-browser]` : lance l'application sur http://127.0.0.1:8765.
- `coach doctor [--fix] [--offline]` : vérifie l'installation.
- `coach login-garmin` : (re)connexion à Garmin.
- `coach update` : réinstalle la wheel de la dernière release GitHub.

La commande `coachcloclo` est un alias de `coach`.

## Ce que vérifie `coach doctor`

Python (>= 3.12), bibliothèque `garminconnect`, CLI `claude` installé, connexion Claude valide, tokens Garmin valides, dossier de données accessible en écriture, port 8765 libre. `--fix` corrige ce qui peut l'être : installation du CLI Claude, connexion Claude (lance `claude` en interactif ; connecte-toi puis tape `/exit`), connexion Garmin (`coach login-garmin`), création du dossier ; puis il revérifie. En mode clé API, la connexion Claude se règle dans les réglages de l'app. `--offline` saute les vérifications Claude et Garmin.

## Mode LAN et PIN

`coach start --lan` écoute sur tout le réseau local (par ex. pour ouvrir l'app depuis ton téléphone). Un PIN de 4 à 12 chiffres est demandé au premier lancement, puis requis pour se connecter. Sans `--lan`, seule ta machine peut accéder à l'app.

Note : depuis un téléphone, via `http://<ip>:8765` en http simple (`--lan`), les navigateurs n'installent pas la PWA et n'enregistrent pas le service worker (contexte sécurisé requis). L'application fonctionne quand même dans le navigateur.

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

Les installeurs récupèrent la wheel de la dernière release GitHub. Pour en publier une, mets à jour `version` dans `pyproject.toml`, puis pousse un tag :

```bash
git tag v0.1.0
git push origin v0.1.0
```

Le workflow `release.yml` compile le front, construit la wheel et l'attache à la release.
