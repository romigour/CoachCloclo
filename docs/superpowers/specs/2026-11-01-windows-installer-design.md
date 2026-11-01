# Installateur Windows, lancement sans terminal et mise à jour intégrée

Date : 2026-11-01
Statut : implémenté

## 1. Objectif

Aujourd'hui, installer, lancer et mettre à jour CoachCloclo passe par le terminal
(`irm … | iex`, `coach start`, `coach update`), et la connexion Claude ouvre `claude` en
interactif dans la console. C'est trop difficile pour des proches non techniques.

On veut un **installateur Windows classique** (`CoachCloclo-Setup-x.y.z.exe`), une **icône sur
le bureau** pour lancer l'application, et une **mise à jour intégrée** qui vérifie au lancement
ou à la demande s'il existe une nouvelle version, et l'installe en un clic. Le mode LAN devient
activable depuis les Réglages.

### Critères de succès

- Quelqu'un qui n'a jamais ouvert de terminal installe, lance, connecte Claude et Garmin, met à
  jour et désinstalle CoachCloclo uniquement par double-clics et dans le navigateur.
- Aucune fenêtre console n'apparaît en usage normal (seule exception possible : le repli de
  connexion Claude, §5.2).
- Aucun droit administrateur n'est demandé, ni à l'installation ni aux mises à jour.
- Les données de l'utilisateur survivent aux mises à jour et à la désinstallation.
- `install.ps1`, `install.sh`, la wheel et les commandes `coach` continuent de fonctionner
  comme avant pour les utilisateurs avancés.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Public | Quelques proches non techniques, zéro terminal |
| Langage | On garde Python : le problème est la distribution, et `garminconnect` n'a pas d'équivalent Rust |
| Empaquetage | PyInstaller (mode dossier) + installateur Inno Setup, par utilisateur (`%LOCALAPPDATA%\Programs\CoachCloclo`) |
| Approches écartées | Coquille Tauri (Rust en plus, deux processus), Python embarqué + mise à jour par wheel (dépendances résolues chez l'utilisateur) |
| Claude | Abonnement Claude via le CLI `claude`, installé et connecté depuis l'application |
| Lancement | Serveur sans console, onglet dans le navigateur par défaut, icône dans la zone de notification |
| Mise à jour | Proposée (bandeau + notification), installée en un clic, appli relancée automatiquement |
| Signature de code | Aucune : avertissement SmartScreen accepté au premier téléchargement |
| Mode LAN | Activable dans les Réglages, sans redémarrer l'application |
| Première version avec installateur | 0.2.0 |

## 3. Expérience utilisateur

1. L'utilisateur télécharge `CoachCloclo-Setup-x.y.z.exe` depuis la page des releases GitHub.
   SmartScreen avertit (« Informations complémentaires » → « Exécuter quand même ») ; le README
   l'explique avec une capture.
2. L'assistant d'installation (en français) propose l'icône sur le bureau (cochée par défaut),
   installe sans demande d'élévation et lance CoachCloclo à la fin.
3. L'application ouvre l'onglet `http://127.0.0.1:8765` et affiche une icône près de
   l'horloge (Ouvrir CoachCloclo / Vérifier les mises à jour / Quitter).
4. Au premier lancement, un écran d'accueil enchaîne la connexion Claude puis Garmin (§5).
5. Les lancements suivants (double-clic sur l'icône) ouvrent l'onglet ; si l'application tourne
   déjà, un nouvel onglet s'ouvre sur l'instance existante.
6. Quand une nouvelle version existe, un bandeau « Version x.y.z disponible — Mettre à jour »
   apparaît ; un clic installe et relance l'application, l'onglet se recharge seul (§6).
7. La désinstallation passe par « Applications » de Windows ; le dossier de données est conservé.

## 4. Architecture

### 4.1 Nouveau paquet `coach/desktop/`

Code utilisé uniquement par l'exécutable installé. Chaque unité a des dépendances injectables
(exécuteur de processus, client HTTP, horloge), comme `coach/doctor.py`.

| Unité | Rôle | Dépend de |
|---|---|---|
| `launcher.py` | Point d'entrée de `CoachCloclo.exe` : journalisation, instance unique, choix du port, serveur uvicorn dans un thread, icône de notification, ouverture du navigateur, arrêt propre, option `--smoke` | `instance`, `tray`, `server`, `create_app` |
| `instance.py` | Mutex Windows nommé `CoachCloclo.Instance` ; lecture/écriture de `desktop.json` (`port`, `pid`) dans le dossier de données ; choix du port (8765 puis 8766 à 8775) | — |
| `server.py` | Enveloppe `uvicorn.Server` : démarrer, arrêter, relancer l'écoute sur un autre hôte avec le même objet `app` (mode LAN) | uvicorn |
| `tray.py` | Icône `pystray` et son menu ; bulle de notification quand une mise à jour est disponible | `updater` |
| `updater.py` | Vérification de la dernière release, téléchargement, SHA-256, lancement de l'installateur ; état exposé à l'API | API GitHub |
| `claude_setup.py` | Recherche du CLI, installation sans fenêtre, `claude auth login --claudeai`, `claude auth status --json` | — |
| `errors.py` | Boîte de dialogue Windows (`MessageBoxW` via `ctypes`) pour les erreurs fatales, avec le chemin du journal | — |

L'application sait qu'elle tourne en version installée quand `sys.frozen` est vrai ;
`create_app` reçoit alors un objet `desktop` (updater, claude_setup, server) qui active les
endpoints du §4.3. Sous `coach start`, `desktop` vaut `None` et ces endpoints répondent 404.

### 4.2 Modifications du code existant

- `coach/api/app.py` :
  - le mode LAN n'est plus figé à la création : `app.state.lan` est lu à chaque requête par
    `require_pin` et `host_guard`, toujours enregistrés (§7.2) ;
  - les requêtes venant de la boucle locale (`request.client.host` dans `127.0.0.1`, `::1`) sont
    dispensées du PIN, y compris sous `coach start --lan` ;
  - nouvel endpoint `GET /api/version` → `{"version": "x.y.z"}` (test de fumée, rechargement
    après mise à jour).
- `coach/config.py` : `Settings` gagne `lan_enabled: bool = False`.
- `coach/doctor.py` : `_check_claude_cli` cherche aussi `%USERPROFILE%\.local\bin\claude.exe`
  quand `claude` n'est pas dans le PATH (fonction partagée avec `claude_setup.find_claude`).
- `coach/cli.py` : la création du PIN réutilise la validation partagée (4 à 12 chiffres) avec
  l'endpoint LAN.
- `pyproject.toml` : nouveau groupe de dépendances `desktop = ["pyinstaller", "pystray", "pillow"]`.
  La wheel n'en dépend pas.

### 4.3 Nouveaux endpoints (version installée uniquement)

| Endpoint | Rôle |
|---|---|
| `GET /api/setup/status` | `{claude_cli, claude_auth, claude_step, garmin}` (`claude_step` : `idle`, `installing`, `logging_in`, `failed` avec message) |
| `POST /api/setup/claude/install` | Lance l'installation du CLI en arrière-plan |
| `POST /api/setup/claude/login` | Lance `claude auth login --claudeai` en arrière-plan |
| `GET /api/update` | `{current, latest, available, state, progress, error}` |
| `POST /api/update/check` | Revérifie maintenant (bouton des Réglages) |
| `POST /api/update/install` | Télécharge, vérifie et lance l'installateur, puis arrête l'application |
| `GET /api/lan` | `{enabled, has_pin, addresses: ["http://192.168.1.12:8765", …], local}` |
| `POST /api/lan` | `{enabled, pin?}` ; refusé (403 `local_only`) si la requête ne vient pas de la boucle locale |

Toutes les requêtes `POST` restent soumises au contrôle CSRF existant (`x-coach: 1`).

### 4.4 Empaquetage

- `packaging/windows/coachcloclo.spec` : PyInstaller en mode dossier (démarrage plus rapide
  qu'un exécutable unique), `console=False`, icône `packaging/windows/coachcloclo.ico`,
  inclusion de `coach/web_dist/` et `copy_metadata("coachcloclo")` pour que
  `importlib.metadata.version` fonctionne.
- `packaging/windows/installer.iss` : Inno Setup 6, `PrivilegesRequired=lowest`,
  `DefaultDirName={localappdata}\Programs\CoachCloclo`, langue française, icône bureau (tâche
  cochée par défaut), entrée du menu Démarrer, désinstallation. `AppId` fixe pour que chaque
  installation remplace la précédente. Version passée par `/DAppVersion`.
  - `[Code]` `InitializeSetup` : attend jusqu'à 30 s la libération du mutex
    `CoachCloclo.Instance` ; au-delà, abandon (code de sortie non nul, l'ancienne version reste).
  - `[Run]` : `{app}\CoachCloclo.exe` avec `Flags: nowait postinstall` **sans**
    `skipifsilent`, pour relancer l'application après une mise à jour silencieuse.
  - La désinstallation ne touche pas au dossier de données.

## 5. Premier lancement : Claude puis Garmin

### 5.1 Détection

Au chargement, le front appelle `GET /api/setup/status`. Tant que Claude (CLI + connexion) ou
Garmin n'est pas prêt, et que l'utilisateur n'a pas passé l'étape Claude, il affiche l'écran
d'accueil à la place de l'application. L'état est recalculé à chaque appel ; rien n'est
mémorisé côté serveur, sauf le fait d'avoir passé l'étape Claude (mémorisé dans le navigateur,
`localStorage`, pour cette session de configuration).

La vérification « Claude connecté » de l'écran d'accueil utilise `claude auth status --json`
(instantané, sans appel au modèle). `coach doctor` garde son appel réel.

### 5.2 Étape Claude

1. **CLI absent** : texte « CoachCloclo utilise ton abonnement Claude » et bouton « Installer
   Claude ». `POST /api/setup/claude/install` exécute
   `powershell -NoProfile -Command "irm https://claude.ai/install.ps1 | iex"` avec
   `CREATE_NO_WINDOW`. Le front interroge `/api/setup/status` toutes les 2 s (« Installation en
   cours… »). Échec (code non nul, réseau) : message et bouton « Réessayer ». Délai maximal
   d'installation : 600 s (choix d'implémentation).
2. **CLI installé, non connecté** : bouton « Se connecter à Claude ».
   `POST /api/setup/claude/login` lance `claude auth login --claudeai` avec `CREATE_NO_WINDOW`
   et une entrée standard fermée ; la page de connexion Anthropic s'ouvre dans le navigateur.
   Le front interroge l'état jusqu'à ce que `claude auth status` indique une connexion. Après
   5 minutes, le processus est arrêté et « Réessayer » s'affiche.
3. **Repli** (non nécessaire, voir résultat ci-dessous) : si l'étape 1 du plan (§9) montre que la connexion exige une saisie dans le
   terminal, le bouton ouvre à la place une fenêtre console (`CREATE_NEW_CONSOLE`) lançant
   `claude auth login --claudeai`, avec un texte dans l'appli : « Une fenêtre va s'ouvrir :
   suis les instructions, elle se fermera toute seule ». C'est la seule console possible.
   **Résultat du test (2026-11-01, Claude Code 2.1.285)** : `claude auth login --claudeai`
   sans console ni entrée standard ouvre le navigateur et se termine avec le code 0 une fois
   la connexion faite. Aucun repli console n'est nécessaire (`LOGIN_NEEDS_CONSOLE = False`).
4. **« Passer pour l'instant »** : l'écran passe à Garmin. La page Stats fonctionne sans
   Claude ; la génération de plan affiche « Connecte Claude » avec un lien vers cette étape
   (l'écran d'accueil reste accessible depuis les Réglages).

Le mode clé API reste réglable dans les Réglages comme aujourd'hui et n'apparaît pas dans
l'écran d'accueil. Si `llm_mode` vaut `api`, l'étape Claude est considérée comme faite.

### 5.3 Étape Garmin

Réutilise le formulaire de connexion existant (email, mot de passe, MFA éventuel) et
`POST /api/garmin/login`. Une fois connecté, la synchronisation démarre comme aujourd'hui et
l'utilisateur arrive sur la page Stats. Si la connexion Garmin expire plus tard, l'écran
d'accueil réapparaît sur cette étape.

## 6. Mise à jour

### 6.1 Version et vérification

- Version installée : `importlib.metadata.version("coachcloclo")` ; `pyproject.toml` reste la
  seule source de vérité.
- `updater.check()` interroge `https://api.github.com/repos/<repo>/releases/latest`
  (`<repo>` = `romigour/CoachCloclo`, surchargeable par `COACH_UPDATE_REPO` pour les tests),
  délai 10 s. Comparaison de versions par tuple d'entiers `x.y.z` (pas de nouvelle dépendance).
- Une release n'est proposée que si elle contient `CoachCloclo-Setup-<version>.exe` **et**
  `CoachCloclo-Setup-<version>.exe.sha256`. Sinon : pas de mise à jour disponible.
- Déclencheurs :
  - au lancement, en arrière-plan une fois le serveur prêt ; un échec est journalisé, rien
    n'est affiché ;
  - menu « Vérifier les mises à jour » de l'icône (bulle : « À jour », « Version x.y.z
    disponible » ou l'erreur) ;
  - bouton « Vérifier les mises à jour » des Réglages (même retour, dans la page).

### 6.2 Présentation

- Bandeau en haut de l'application : « Version x.y.z disponible — Mettre à jour » + « Plus
  tard ». « Plus tard » le masque pour cette version (`localStorage`) ; il revient pour la
  version suivante.
- Bulle de l'icône de notification au lancement si une mise à jour est disponible.
- Les Réglages affichent toujours la version installée.

### 6.3 Installation en un clic

`POST /api/update/install` :

1. Télécharge l'installateur dans `%TEMP%\CoachCloclo-update\` ; `GET /api/update` expose
   `state = downloading` et `progress` (0–100).
2. Vérifie le SHA-256 avec le fichier `.sha256`. En cas d'écart : suppression du fichier,
   `state = failed`, message « Le fichier téléchargé est corrompu, réessaie » ; rien n'est
   installé.
3. `state = installing` ; le front affiche « Mise à jour en cours, CoachCloclo va
   redémarrer… ».
4. Lance l'installateur détaché (`DETACHED_PROCESS`) avec
   `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, puis arrête proprement l'application (serveur,
   icône, mutex).
5. L'installateur attend la libération du mutex, remplace les fichiers, relance
   `CoachCloclo.exe`.
6. L'onglet ouvert interroge `GET /api/version` toutes les 2 s ; quand la nouvelle version
   répond, il recharge la page. Au bout de 2 minutes sans réponse : « La mise à jour semble
   bloquée : relance CoachCloclo depuis l'icône du bureau ».

Une seule installation à la fois : un second `POST /api/update/install` pendant une
installation renvoie 409.

## 7. Mode LAN depuis les Réglages

### 7.1 Interface

Bloc « Accès depuis ton téléphone » dans les Réglages :

- interrupteur Activé / Désactivé ;
- à la première activation (aucun PIN), saisie du PIN (4 à 12 chiffres, deux fois) ;
- juste avant l'activation : « Windows va te demander l'autorisation : coche *Réseaux privés*
  puis *Autoriser* » ;
- une fois activé : la ou les adresses à ouvrir sur le téléphone avec un bouton « Copier »,
  un lien « Changer le PIN », et l'aide « Le téléphone n'arrive pas à se connecter ? Vérifie
  le pare-feu Windows » ;
- consulté depuis un téléphone (`local = false`), le bloc est en lecture seule.

### 7.2 Fonctionnement

- `create_app` enregistre toujours `require_pin` et `host_guard` ; ils lisent `app.state.lan`.
  `create_app(lan=True)` exige toujours un PIN, comme aujourd'hui.
- `POST /api/lan` valide le PIN (s'il est fourni ou requis), enregistre `pin_hash` et
  `lan_enabled`, met à jour `app.state.lan`, puis demande à `server.py` de relancer l'écoute
  sur `0.0.0.0` ou `127.0.0.1`, même port, même objet `app`. Les tâches en arrière-plan
  (import d'historique) et les sessions PIN continuent. La réponse part avant la relance.
- Désactiver le mode LAN vide aussi `app.state.sessions` (les téléphones devront ressaisir le
  PIN à la prochaine activation).
- Au lancement, `launcher.py` démarre dans le mode enregistré (`lan_enabled`).
- Adresses affichées : adresses IPv4 privées de la machine (hors boucle locale et
  link-local), suivies du port.

### 7.3 Sécurité

- La boucle locale est dispensée du PIN ; tout autre client doit le saisir.
- Seule la boucle locale peut modifier le mode LAN ou le PIN (`POST /api/lan`) : un téléphone
  connecté ne peut ni changer le PIN ni rouvrir l'accès.
- `POST /api/update/install` et les endpoints `setup` sont aussi réservés à la boucle locale.
- Pas de règle de pare-feu créée par l'installateur (elle exigerait des droits
  administrateur) : on s'appuie sur la fenêtre d'autorisation de Windows.

## 8. Erreurs et journal

- Journal : `<dossier de données>\logs\coachcloclo.log`, rotation (5 fichiers × 1 Mo),
  incluant la sortie d'uvicorn et les exceptions non rattrapées.
- Erreur fatale au démarrage (aucun port libre entre 8765 et 8775, exception au démarrage du
  serveur) : boîte de dialogue Windows avec le message et le chemin du journal, puis sortie.
- Instance déjà lancée mais qui ne répond pas sur le port de `desktop.json` : boîte de
  dialogue « CoachCloclo semble bloqué : quitte-le depuis l'icône près de l'horloge ou
  redémarre l'ordinateur ».
- Échec de l'installateur : Inno annule ; l'ancienne version reste en place.
- Pas de retour automatique à l'ancienne version si la nouvelle ne démarre pas : réinstaller
  depuis la page des releases.

## 9. Construction et publication

### 9.1 `release.yml` (tag `v*`)

1. **`build`** (ubuntu) : front (`npm ci`, `npm test`, `npm run build`), `uv run pytest`,
   `uv build`. Artefacts : la wheel et `coach/web_dist/`.
2. **`windows`** (`windows-latest`, `needs: build`) :
   - récupère `coach/web_dist/` ;
   - `uv run --group desktop pyinstaller packaging/windows/coachcloclo.spec` ;
   - test de fumée : `dist\CoachCloclo\CoachCloclo.exe --smoke` démarre le serveur sans icône
     ni navigateur, vérifie que `GET /api/version` renvoie la version du tag, puis sort avec le
     code 0 ;
   - installe Inno Setup via `choco install innosetup` s'il est absent, puis
     `iscc /DAppVersion=<version> packaging/windows/installer.iss` ;
   - calcule `CoachCloclo-Setup-<version>.exe.sha256` ;
   - artefacts : l'installateur et son `.sha256`.
3. **`publish`** (`needs: [build, windows]`) : `gh release create` avec la wheel,
   l'installateur et le `.sha256`. La release n'existe que si tout a réussi.

`workflow_dispatch` : exécute `build` et `windows` sans `publish`, pour tester un installateur
avant de poser le tag.

### 9.2 `ci.yml`

Ajout d'un job `pytest` sur `windows-latest` (code spécifique à Windows : mutex, chemins,
drapeaux de création de processus). La construction de l'installateur reste réservée à
`release.yml`.

## 10. Tests

### 10.1 Automatisés (pytest)

- `updater` : comparaison de versions (dont `0.10.0 > 0.9.0`), release sans installateur ou
  sans `.sha256` ignorée, SHA-256 faux, réseau en panne ou délai dépassé, progression,
  409 en cas d'installation concurrente, `COACH_UPDATE_REPO`.
- `claude_setup` : CLI dans le PATH ou dans `~\.local\bin`, absent ; lecture de
  `auth status --json` (connecté, non connecté, sortie invalide) ; abandon de la connexion
  après le délai (exécuteur et horloge simulés) ; échec de l'installation.
- `instance` : écriture/lecture de `desktop.json`, port de repli, erreur si tous les ports
  sont pris.
- API LAN : `app.state.lan` modifiable en cours de route ; boucle locale dispensée du PIN,
  autre IP soumise au PIN ; `POST /api/lan` refusé hors boucle locale ; validation du PIN ;
  sessions vidées à la désactivation ; non-régression de `create_app(lan=True)`.
- Endpoints `desktop` absents (404) quand `create_app` est appelé sans `desktop`.
- `doctor` : CLI trouvé dans `~\.local\bin` hors PATH.

### 10.2 Front (vitest)

- Écran d'accueil piloté par `/api/setup/status`, bouton « Passer », retour sur l'étape
  Garmin quand la connexion expire.
- Bandeau de mise à jour : affiché, masqué pour une version, réaffiché pour la suivante ;
  progression ; rechargement quand `/api/version` change.
- Bloc LAN : saisie et confirmation du PIN, adresses, lecture seule depuis un téléphone.

### 10.3 Vérification en conditions réelles (Windows Sandbox ou machine propre)

- [ ] Téléchargement depuis le navigateur, avertissement SmartScreen, installation sans UAC
- [ ] Icône du bureau et entrée du menu Démarrer
- [ ] Premier lancement : installation et connexion Claude sans console, puis Garmin avec MFA
- [ ] Second double-clic : nouvel onglet sur l'instance existante
- [ ] Port 8765 occupé : démarrage sur 8766
- [ ] Mise à jour vN → vN+1 via un fork (`COACH_UPDATE_REPO`), relance et rechargement
- [ ] Désinstallation : programme supprimé, données conservées, réinstallation qui les retrouve
- [ ] Mode LAN : activation, fenêtre du pare-feu, accès depuis un téléphone avec PIN,
      PC sans PIN, désactivation
- [ ] Erreur fatale : boîte de dialogue avec le chemin du journal

## 11. Ordre de mise en œuvre

1. Test de `claude auth login --claudeai` sans console : décide si le repli du §5.2 est
   nécessaire.
2. `coach/desktop/` : lanceur, instance unique, serveur, icône, journal ; empaquetage
   PyInstaller et Inno Setup ; `--smoke`.
3. Écran d'accueil (endpoints `setup` et front).
4. Mise à jour (updater, endpoints, bandeau, Réglages, `[Code]` Inno).
5. Mode LAN dynamique et bloc des Réglages.
6. CI (`release.yml` en trois jobs, `ci.yml` sous Windows).
7. README : la section Windows devient « Télécharge `CoachCloclo-Setup.exe` » (avec
   SmartScreen) ; `install.ps1` passe en option avancée ; ROADMAP mise à jour. Version 0.2.0.

## 12. Hors périmètre

- Certificat de signature de code.
- macOS et Linux (inchangés : `install.sh`).
- Mise à jour différentielle, canal bêta, retour automatique à la version précédente.
- QR code de l'adresse LAN, HTTPS en mode LAN (installation de la PWA sur téléphone).
- Mode clé API dans l'écran d'accueil.
- Démarrage automatique avec Windows.
