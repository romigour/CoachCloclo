# CoachCloclo

Application locale qui génère tes plans d'entraînement running/trail à partir de tes données Garmin, avec Claude. Tout tourne sur ta machine ; par défaut, tes données ne quittent pas ton ordinateur (hormis les appels à Garmin et à Claude). Tu peux en option les stocker dans le cloud, sur ta propre base Turso, pour retrouver les mêmes données sur deux PC (voir [Stockage dans le cloud](#stockage-dans-le-cloud-turso)).

La page **Stats** (page d'accueil dès que des activités sont importées) donne une vue d'ensemble de toutes tes activités Garmin : chiffres clés, régularité, volume, progression en course, records et compétitions, avec des filtres par période et par sport. Elle ne demande pas d'objectif : la synchronisation importe tes activités dès que Garmin est connecté, puis l'historique complet est importé en arrière-plan (reprise possible après une interruption, et « Réimporter l'historique » dans les Réglages).

**Disponibilités, imprévus et vélo.** À la création de l'objectif (et dans « Modifier l'objectif »), tu coches les jours où tu peux t'entraîner et, si tu veux, le jour de ta sortie longue : le plan ne place aucune séance ailleurs. Quand la vie s'en mêle, « Signaler un imprévu » enregistre une indisponibilité (vacances, déplacement), une blessure ou une maladie (avec ou sans date de reprise), une semaine allégée ou une fatigue : Claude propose aussitôt un ajustement, que tu valides ou refuses (refusé, le plan reste inchangé et l'imprévu reste enregistré). Pendant un arrêt sans date de reprise, la synchronisation ne propose plus d'ajustement ; « Signaler la reprise » produit une proposition de reprise progressive. Enfin, la case « Inclure du vélo » autorise Claude à remplacer au plus une séance facile par semaine par du vélo d'endurance douce (FC en zones 1-2), exporté sur la montre comme workout vélo et rattaché à l'activité vélo correspondante.

Découvrir l'application en images : [romigour.github.io/CoachCloclo/guide](https://romigour.github.io/CoachCloclo/guide/).

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

Python (>= 3.12), bibliothèque `garminconnect`, CLI `claude` installé, connexion Claude valide, tokens Garmin valides, dossier de données accessible en écriture, base cloud joignable (seulement si le stockage cloud est activé), port 8765 libre. `--fix` corrige ce qui peut l'être : installation du CLI Claude, connexion Claude (lance `claude` en interactif ; connecte-toi puis tape `/exit`), connexion Garmin (`coach login-garmin`), création du dossier ; puis il revérifie. En mode clé API, la connexion Claude se règle dans les réglages de l'app. `--offline` saute les vérifications Claude, Garmin et cloud.

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

Par défaut (mode local), il contient `coach.db` (base SQLite), `settings.json` (réglages, hash du PIN) et `garmin/` (tokens Garmin). Les tokens ne sont jamais envoyés ailleurs que chez Garmin ; ne partage pas ce dossier.

En mode cloud, tes données (séances, plan, historique, état de synchro) vont dans ta base Turso et `coach.db` disparaît du PC. Restent sur chaque PC, jamais envoyés dans le cloud : les tokens Garmin, la connexion Claude et la clé API, le PIN, le réglage LAN, les logs, et l'URL et le jeton Turso eux-mêmes.

## Stockage dans le cloud (Turso)

Option pour retrouver les mêmes données sur plusieurs PC (maison, travail). Elle utilise ta propre base [Turso](https://turso.tech) ; c'est gratuit pour un usage personnel.

### Mise en place

1. Crée un compte sur turso.tech.
2. Crée une base, dans une région proche de toi.
3. Crée un jeton d'accès limité à cette seule base.
4. Dans CoachCloclo, ouvre Réglages → Stockage des données, colle l'URL `libsql://…` et le jeton, puis active le stockage cloud.
5. Sur le 2ᵉ PC, fais pareil avec la même URL et le même jeton : l'app détecte que la base contient déjà des données et te demande de confirmer. Elle adopte alors le cloud : les données de ce 2ᵉ PC ne sont pas envoyées dans le cloud, mais son ancienne base est gardée dans le dossier de données sous le nom `coach.db.bak`.
   Si des séances de ce PC sont déjà sur ta montre, la demande de confirmation l'indique : elles n'en seront pas retirées. Retire d'abord ce plan de la montre si tu n'en veux plus.

### Ce qui se passe

- À l'activation sur une base cloud vide, tes données locales sont copiées dans le cloud. Les fichiers locaux ne sont supprimés qu'après vérification de la copie (même nombre de lignes dans chaque table).
- « Revenir au stockage local » recopie les données du cloud sur ce PC. La base cloud est conservée : tes autres PC continuent de l'utiliser.
- « Effacer mes données du cloud » ramène d'abord ce PC en local (les données sont recopiées ici), puis vide la base cloud. Les autres PC devront eux aussi revenir en local.
- Pour changer de base cloud, reviens d'abord au stockage local, puis active la nouvelle.
- En mode cloud, l'app a besoin du réseau. Si la base est injoignable, elle l'indique ; `coach doctor` vérifie aussi cet accès.
- La synchro Garmin ne tourne que sur un PC à la fois : un autre PC qui essaie affiche « Synchronisation en cours sur un autre PC ».
- Si un PC a une version de l'app trop ancienne pour la base, il demande de mettre à jour CoachCloclo.
- Restent sur chaque PC : tokens Garmin, connexion Claude, clé API, PIN, mode LAN, et le jeton Turso.
- Si un fichier local n'a pas pu être supprimé ou renommé pendant la bascule (fichier bloqué par un antivirus, par exemple), l'app s'en occupe au démarrage suivant en mode cloud. Un `coach.db` resté là n'est jamais supprimé : il est renommé en `coach.db.bak`.
- Une bascule attend que l'app soit au repos : pendant une synchro, un import ou une génération de plan, elle répond « Une opération est en cours, réessaie dans un instant. »

### Si la base cloud a disparu

Si la base Turso est définitivement perdue (supprimée, compte fermé), « Revenir au stockage local » ne peut plus rien recopier. Pour repartir en local à la main :

1. Ferme CoachCloclo.
2. Dans `settings.json` du dossier de données (voir « Données et tokens »), remplace `"storage_mode": "turso"` par `"storage_mode": "local"`.
3. Relance CoachCloclo : il repart sur `coach.db`, ou sur une base vide s'il n'y en a pas (le cas normal en mode cloud).

Les données du cloud sont alors perdues pour ce PC. Si ce PC avait adopté le cloud, son ancienne base est dans `coach.db.bak` : renomme-la en `coach.db` (app fermée) pour la retrouver, telle qu'elle était avant l'adoption.

## Version mobile

Une appli mobile en lecture seule, installable sur l'écran d'accueil du téléphone : <https://romigour.github.io/CoachCloclo/app/>. Elle lit ta base Turso, donc le stockage cloud doit déjà être activé sur l'appli de bureau (voir [Stockage dans le cloud](#stockage-dans-le-cloud-turso)). Différence avec le [mode LAN](#mode-lan-et-pin) : le LAN exige le PC allumé et le téléphone sur le même réseau, avec toutes les fonctions ; la version mobile marche partout, en lecture seule, via Turso.

- Au premier lancement, elle demande seulement l'URL et le jeton Turso, enregistrés sur le téléphone. L'écran « Connexion » permet de les modifier ou de les effacer.
- Crée un jeton en lecture seule : `turso db tokens create <base> --read-only`.
- Tu peux consulter Aujourd'hui (la séance du jour), Plan (la semaine, imprévus visibles) et Statistiques. Aucune action ne crée, modifie ou supprime quoi que ce soit.
- Si elle affiche « Mets à jour l'appli de bureau puis relance-la une fois », installe la dernière version de l'appli de bureau et relance-la.

Elle est publiée par le workflow `pages.yml`, construite depuis le dernier tag `v*`. Deux réglages à faire une seule fois dans le dépôt GitHub :

1. Settings → Pages → Source : « GitHub Actions ».
2. Settings → Environments → `github-pages` → Deployment branches and tags → ajouter une règle autorisant les tags `v*` (par défaut, seule la branche par défaut peut déployer, ce qui bloque les déploiements sur tag).

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
