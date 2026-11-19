# Mise à jour du guide — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** remettre `docs/guide/index.html` à jour pour la v0.13.0, avec de nouvelles captures prises sur les vraies données de l'utilisateur.

**Architecture :** on garde la page actuelle (CSS, lightbox, sections `.feature` / `.split` / `.band`) et on réécrit le contenu. Un petit script Node pilote Chrome en headless via le protocole DevTools (aucune dépendance) pour produire des captures JPG reproductibles.

**Tech Stack :** HTML et CSS statiques (GitHub Pages), Node 20 (`--experimental-websocket`), Chrome headless.

**Spec :** `docs/superpowers/specs/2026-11-19-guide-update-design.md`

## Global Constraints

- Ton : tutoiement, phrases courtes, registre « vitrine » et non « notice ». Le contenu technique (Turso, coûts) reste discret, et la carte Diagnostic n'apparaît pas.
- Captures au format JPG, avec un facteur d'échelle de 2, comme les actuelles. Pour le bureau, une fenêtre de 1080 × 675 CSS px (soit 2160 × 1350). Pour le mobile, 390 × 844 (soit 780 × 1688). Viser 200 Ko au plus par image.
- Les captures viennent de l'appli **installée** de l'utilisateur, déjà lancée sur `http://127.0.0.1:8765`. Version attendue : 0.13.0, à vérifier avec `GET /api/version`.
- **Rien n'est modifié dans les données** : navigation et lectures seulement. Aucun clic sur Synchroniser, Envoyer, Accepter, Enregistrer ni Signaler.
- Toute image du dossier `docs/guide/img/` doit être référencée par la page, et toute référence doit exister.
- Hors périmètre : README, documentation Turso, page de la version mobile.

## Review Focus

- **Données personnelles sensibles sur une capture** (nom complet, adresse e-mail, jeton Turso, PIN, adresse IP du LAN) : chaque capture est relue avant le commit, et on recadre ou on choisit un autre écran si besoin.
- **Thème sombre de l'OS pendant la capture** : les captures en clair forcent `prefers-color-scheme: light` par émulation, sinon le guide mélangerait les thèmes.
- **Page capturée avant la fin du chargement** (squelettes, graphiques vides) : le script attend que le réseau soit au repos et qu'un sélecteur attendu soit visible avant de capturer.
- **Pas de cycle à plusieurs objectifs dans la base** : on le vérifie à la tâche 1, et on s'arrête pour demander à l'utilisateur avant de faire la section « Ta saison ».
- **Page lue sur un téléphone** : la nouvelle section respecte la grille existante (passage en une colonne sous 860 px) et ne crée aucun défilement horizontal à 375 px.

---

### Task 1 : script de capture et vérification des données

**Files :**
- Create : `docs/guide/shots.mjs`

**Interfaces :**
- Produces : `node --experimental-websocket docs/guide/shots.mjs [nom…]`, qui écrit `docs/guide/img/<nom>.jpg` pour chaque capture de la table `SHOTS`, ou seulement pour celles dont le nom est passé en argument.

- [ ] **Step 1 : vérifier l'appli.** Lancer `curl -s http://127.0.0.1:8765/api/version` puis `curl -s http://127.0.0.1:8765/api/status`. La version attendue est 0.13.0. Si l'appli ne répond pas, demander à l'utilisateur de lancer CoachCloclo.
- [ ] **Step 2 : vérifier les données.** Ouvrir `#/goal` dans le navigateur intégré, en lecture seulement, et vérifier qu'il y a au moins deux objectifs dans le cycle, idéalement avec une course rapprochée. Sinon, **s'arrêter et demander à l'utilisateur** comment montrer la section « Ta saison ».
- [ ] **Step 3 : écrire `shots.mjs`.** Le script lance `chrome.exe --headless=new --remote-debugging-port=9333 --user-data-dir=<tmp>`. Pour chaque entrée `{ name, hash, viewport: [w, h], scheme: 'light'|'dark', mobile?: bool, scrollTo?: selector, clip?: selector, waitFor: selector }`, il enchaîne les appels CDP suivants : `Emulation.setDeviceMetricsOverride` (avec `deviceScaleFactor: 2`), `Emulation.setEmulatedMedia` (`prefers-color-scheme`), `Page.navigate` vers `http://127.0.0.1:8765/<hash>`, attente de `waitFor` puis 800 ms, défilement éventuel, et `Page.captureScreenshot({format: 'jpeg', quality: 80, clip?})`. Il ferme Chrome à la fin. Dans la table `SHOTS`, garder les noms de fichiers existants quand l'écran est le même, et en créer de nouveaux pour les écrans nouveaux :
  `week` (Ma semaine, remplace `today` et `plan`), `goals` (page Objectifs, cycle), `goals-close` (avertissement de courses rapprochées, cadré sur l'élément), `proposal`, `event`, `race`, `stats-top`, `stats-run`, `stats-records`, `stats-dark` (scheme dark), `m-week` et `m-stats` (mobile 390 × 844), `lan-panel`, `usage` (carte Consommation Claude, cadrée sur l'élément).
  Les sélecteurs viennent des composants Svelte de `web/src/routes/` et `web/src/components/`.
  Pour `proposal` et `event`, s'il n'existe ni proposition en attente ni imprévu, ne prendre que ce qui est visible sans rien créer, ou garder l'ancienne capture et le signaler.
- [ ] **Step 4 : lancer le script et relire chaque image.** Lancer `node --experimental-websocket docs/guide/shots.mjs`, puis ouvrir chaque JPG avec Read. Vérifier que l'écran est le bon, entièrement chargé, sans donnée sensible (voir Review Focus), dans le bon thème, et qu'il pèse 200 Ko au plus (sinon passer à `quality: 70`).
- [ ] **Step 5 : commit**, avec `git add docs/guide/shots.mjs docs/guide/img` et le message `docs(guide): nouvelles captures v0.13.0 et script de capture`.

### Task 2 : contenu du guide

**Files :**
- Modify : `docs/guide/index.html`
- Delete : les images qui ne sont plus référencées (`today.jpg`, `plan.jpg`, `goal.jpg`, `m-today.jpg`, si elles sont remplacées)

**Interfaces :**
- Consumes : les noms d'images produits par la tâche 1.

- [ ] **Step 1 : accroche et étapes.** Le texte principal parle de « ta saison » et de « tes courses » au lieu de « ta prochaine course ». L'étape 02 devient « Fixe tes objectifs » : plusieurs courses, avec une priorité chacune. L'image d'en-tête devient `img/week.jpg`, avec une légende sur « Ma semaine ».
- [ ] **Step 2 : nouvelle section `id="saison"` « Ta saison »**, placée après Statistiques et avant Plan, avec la même structure `.feature` et `.split` que ses voisines. Contenu : une course principale, des courses de préparation, les priorités ; Claude construit le cycle autour d'elles ; les courses rapprochées s'enchaînent en bloc, avec récupération, et un avertissement signale un enchaînement trop serré ; à la fin du cycle, l'appli propose de préparer le suivant. Images : `goals.jpg` et `goals-close.jpg`. Ajouter « Saison » dans la navigation du haut.
- [ ] **Step 3 : section Plan.** La réécrire autour de « Ma semaine » : séance du jour, semaine et programme sur un seul écran, envoi sur la montre, analyse après la synchro. Le contenu actuel sur le formulaire d'objectif (route ou trail, distances, jours, vélo, temps visé) passe dans « Ta saison » ou y est condensé.
- [ ] **Step 4 : Ajustements, Jour J, Apparence.** Mettre à jour uniquement les `src` et `data-full` des captures. Ajouter sous Apparence (ou dans « Démarrer ») une courte mention de la carte Consommation Claude, avec `usage.jpg` : « tu vois ce que coûte chaque génération ».
- [ ] **Step 5 : partie téléphone.** Ajouter une ligne : le stockage cloud Turso, qui se règle dans les Réglages, permet aussi de partager la même base entre deux PC. Remplacer `m-today` par `m-week`.
- [ ] **Step 6 : pied de page.** La phrase devient : « Tes données restent chez toi, ou dans ta propre base Turso si tu l'actives : l'appli ne parle qu'à Garmin, à Claude et, si tu le choisis, à Turso. » Remplacer « version 0.7.3 » par « version 0.13.0 ».
- [ ] **Step 7 : vérifier les références.** Lancer `grep -oE 'img/[a-z-]+\.jpg' docs/guide/index.html | sort -u`, puis `ls docs/guide/img`. Les deux listes doivent être identiques : supprimer les orphelines avec `git rm`.
- [ ] **Step 8 : vérification visuelle.** Ouvrir `docs/guide/index.html` dans le navigateur intégré, à 1280 px puis à 375 px. Vérifier qu'il n'y a pas de défilement horizontal (`document.documentElement.scrollWidth <= innerWidth`), que la lightbox s'ouvre sur une nouvelle image et que la nouvelle entrée de navigation mène à `#saison`.
- [ ] **Step 9 : commit**, avec `git add -A docs/guide` et le message `docs(guide): mise à jour pour la v0.13.0 (saison, Ma semaine, cloud)`.
