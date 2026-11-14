# Stockage des données dans le cloud (option)

Date : 2026-11-14
Statut : design relu, en attente de validation

## 1. Intention

L'athlète alterne entre **deux PC (maison et travail)**. Aujourd'hui tout vit dans le dossier de
données local (`coach.db`, `gpx/`, `history.json`, `settings.json`) : sur l'autre PC, il faut
recréer les objectifs, relancer une génération de plan avec Claude et réimporter l'historique
Garmin.

On ajoute une **option** « Stocker mes données dans le cloud ». Activée, l'application utilise
une base en ligne comme **unique lieu de stockage** des données partagées : il n'y a plus de
copie locale, donc rien à synchroniser entre PC. Désactivée (le défaut), rien ne change.

L'utilisateur fournit **sa propre base** (modèle « chacun sa base ») : l'isolation des données
entre utilisateurs est garantie par construction (un jeton n'ouvre qu'une base) ; l'auteur de
l'application n'héberge rien et ne gère aucun compte.

### Critères de succès

- Sans action, une installation existante ou neuve fonctionne exactement comme aujourd'hui, en local.
- Après activation sur le PC 1 puis sur le PC 2, les deux PC voient les mêmes objectifs, plans,
  séances, activités, imprévus, stratégies (GPX compris) et le même état d'import d'historique,
  sans régénération Claude ni réimport Garmin.
- Une modification faite sur un PC est visible sur l'autre au prochain chargement de page.
- Jamais deux synchros / exports Garmin en même temps sur les deux PC (pas de workout en double sur la montre).
- La désactivation ramène toutes les données en local sur ce PC, sans perte.
- Aucune perte de données si une étape de bascule échoue (réseau coupé, jeton invalide…).

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs**
- Option activable / désactivable depuis les Réglages, avec bascule des données dans les deux sens.
- Turso (SQLite hébergé, libSQL) comme premier hébergeur.
- Architecture qui permet d'ajouter un autre hébergeur sans toucher aux services.

**Non-objectifs**
- Fonctionnement hors ligne en mode cloud (sans réseau, l'app affiche une erreur claire).
- Comptes utilisateurs, connexion e-mail / Google, service opéré par l'auteur (modèle « B » écarté).
- Partager les tokens Garmin, la connexion Claude, la clé API, le PIN ou le mode LAN : ils restent par PC.
- Réplique locale (embedded replica Turso) : possible plus tard si la latence gêne, hors périmètre.
- Fusion de deux jeux de données différents (local du PC 2 + cloud) : on choisit l'un des deux.

**Anti-objectifs** (échec même si « ça marche »)
- Supprimer des données locales avant d'avoir vérifié qu'elles sont bien dans le cloud.
- Laisser un PC à une ancienne version corrompre ou mal lire une base migrée par une version plus récente.
- Envoyer dans le cloud un secret (tokens Garmin, clé API, hash du PIN, jeton Turso).
- Rendre le mode local plus lent ou plus fragile.

## 3. Contraintes

- La base est en SQLModel / SQLAlchemy avec des migrations SQLite maison (`_migrate`, `PRAGMA
  table_info`, `ALTER TABLE … RENAME COLUMN`). Turso parle le même dialecte : ces migrations
  doivent fonctionner telles quelles.
- Un seul point d'entrée crée le moteur : `Repo(make_engine(db_path()))` dans `coach/api/app.py`.
- Le réseau du PC du travail est potentiellement filtré : l'accès doit passer par HTTPS (443).
- L'app reste dans la zone de notification tant qu'on ne la quitte pas : elle peut être ouverte
  sur les deux PC en même temps.
- Le volume est faible (quelques Mo même avec l'historique complet).
- Données de santé (FC, blessures) : elles ne vont que dans la base de l'utilisateur.

## 4. Approches envisagées

1. **Turso, SQLite hébergé** — *retenue*. Même dialecte que la base actuelle, donc code et
   migrations quasi inchangés ; HTTPS ; offre gratuite suffisante ; authentification par URL de
   base + jeton. Contrepartie : latence réseau sur chaque requête.
2. **Postgres hébergé (Supabase, Neon)** — écartée : migrations à réécrire (spécifiques SQLite),
   connexions sur 5432/6543 souvent bloquées en entreprise.
3. **Serveur web maison avec API** — écartée : un serveur à héberger et maintenir, disproportionné.

Sur l'authentification : **chacun sa base** (A) retenu contre **service opéré par l'auteur avec
comptes utilisateurs** (B) : B impose de réécrire l'accès aux données, d'héberger un serveur, de
payer à l'échelle et de devenir responsable de données de santé.

Approche initiale « dossier synchronisé (OneDrive…) » écartée par l'utilisateur au profit d'un service en ligne.

## 5. Ce qui a été décidé

### 5.1 Ce qui va où

| Donnée | Mode local | Mode cloud |
|---|---|---|
| Tables de `coach.db` (objectifs, cycles, séances, activités, tours, propositions, imprévus, courses, records, stratégies, snapshots) | `coach.db` | base cloud |
| Fichiers GPX (`gpx/<goal_id>.gpx`) | **table de la base** (dans les deux modes) | base cloud |
| État d'import d'historique (`history.json`) | **table de la base** (dans les deux modes) | base cloud |
| `last_sync_at`, `proposal_due` (aujourd'hui dans `settings.json`) | **table de la base** (dans les deux modes) | base cloud |
| Verrou de synchro Garmin | table de la base | base cloud |
| Tokens Garmin, `llm_mode`, clé API, modèle, `pin_hash`, `lan_enabled`, logs, `desktop.json`, `claude-cwd`, `ca-bundle.pem` | local | local |
| Choix du mode et identifiants Turso (URL, jeton) | — | local (`settings.json`) |

Déplacer GPX, état d'import et état de synchro **dans la base, y compris en mode local**, fait que
« toutes les données partagées = la base » : la bascule et un futur changement d'hébergeur se
réduisent à copier une base. Une migration reprend les fichiers existants (le fichier GPX est
conservé, la base devient la référence ; `history.json` et les deux champs de `settings.json`
sont lus une fois puis ignorés).

### 5.2 Source de données interchangeable

L'application ne connaît qu'une **source de données** qui fournit un moteur SQLAlchemy. Deux
implémentations : **locale** (fichier SQLite) et **Turso**. Les services et le `Repo` ne savent pas
laquelle est utilisée. Ajouter un hébergeur = ajouter une implémentation compatible SQLite + la
saisie de ses identifiants ; la copie entre sources est générique (table par table, via SQLAlchemy).

### 5.3 Activer le cloud

Réglages → « Stocker mes données dans le cloud » : l'utilisateur colle l'URL de la base et le
jeton ; un lien mène à un guide pas à pas (création du compte et de la base Turso, génération du jeton).

1. L'app teste la connexion (lecture + écriture). Échec : message clair, rien ne change.
2. **Base cloud vide** : migrations appliquées sur la base cloud, copie de toutes les données
   locales, **vérification** (nombre de lignes par table identique). Échec à n'importe quel
   moment : on reste en local, données locales intactes.
3. **Base cloud non vide** (cas du 2ᵉ PC) : confirmation explicite (« Les données de ce PC seront
   remplacées par celles du cloud »). Le local est ignoré.
4. Une fois l'étape 2 vérifiée ou l'étape 3 confirmée : le mode et les identifiants sont
   enregistrés, l'app bascule sur la base cloud, puis **`coach.db` est supprimé** (avec les
   fichiers `gpx/` et `history.json` résiduels).

### 5.4 Désactiver le cloud

1. Copie de la base cloud dans un nouveau `coach.db` local, vérification.
2. Bascule en mode local ; les identifiants Turso sont effacés de `settings.json`.
3. **La base cloud n'est pas effacée** (l'autre PC l'utilise peut-être). Un bouton séparé
   « Effacer mes données du cloud » (avec confirmation) la vide, disponible en mode cloud.

Échec de la copie : on reste en mode cloud, rien n'est supprimé.

### 5.5 Deux PC ouverts en même temps

- **Verrou de synchro** : une ligne en base « détenu par <PC>, jusqu'à <heure> ». **Tout chemin
  qui écrit sur Garmin** le prend : `POST /sync`, import d'historique, export ou retrait de séance,
  mais aussi les exports déclenchés par la création d'objectif, `accept_plan`,
  `update_plan_settings`, l'acceptation d'une proposition, `move_session`, l'export de stratégie
  de course et les aides de `services/garmin_export.py`. Le verrou n'est accordé que s'il est
  libre, expiré ou déjà détenu par ce PC. Le détenteur le prolonge tant qu'il travaille et le
  libère à la fin.
- **Verrou pris ailleurs** (décision du concepteur) :
  - Une synchro explicite, un import ou un export manuel est refusé (409) avec le message
    « Synchronisation en cours sur un autre PC ».
  - Pour une action métier (création d'objectif, validation de plan, proposition…), la
    modification en base **passe quand même**. Les séances concernées sont laissées en
    `sync_error` avec ce message, et le mécanisme existant les reprend : relance par
    `retry_pending_cleanup` à la synchro suivante, ou bouton « réessayer ». Aucune file d'attente
    nouvelle.
- **Démarrage du 2ᵉ PC** : `recover_orphan` ne marque un import « en cours » comme interrompu
  que si le verrou est libre ou expiré, pour ne pas casser l'import qui tourne sur l'autre PC.
- Le reste (pages, création d'objectif, validation de plan) passe par la base unique : le dernier
  écrit gagne, comme deux onglets aujourd'hui.

### 5.6 Versions différentes sur les deux PC

La base porte un **numéro de version de schéma**. Une app dont le schéma est plus ancien que
celui de la base refuse de l'utiliser et affiche « Mets à jour CoachCloclo sur ce PC » (avec le
bouton de mise à jour existant). Une app plus récente migre la base, comme aujourd'hui en local.

### 5.7 Erreurs réseau et jeton

En mode cloud, une base injoignable ou un jeton refusé donne une page d'erreur claire (réessayer,
ouvrir les Réglages pour corriger le jeton ou repasser en local à partir d'une copie, impossible
sans réseau : le message le dit). `coach doctor` vérifie la connexion à la base cloud quand le mode est actif.

### 5.8 Secrets

Le jeton Turso est stocké dans `settings.json` local, comme la clé API (permissions 600 sous
POSIX), jamais renvoyé en clair par l'API web (affiché masqué), jamais journalisé.

## 6. Laissé au constructeur

- Choix de la bibliothèque d'accès Turso (dialecte SQLAlchemy libSQL ou équivalent) et
  **premier pas du plan : un essai** branchant l'app sur une base Turso depuis le réseau du
  travail. Ce qu'il doit montrer (décision du concepteur) :
  - le réseau du travail laisse passer Turso ;
  - les migrations existantes (`PRAGMA table_info`, `RENAME COLUMN`) et les transactions du
    `Repo` fonctionnent avec le pilote ;
  - la page Stats et la page du plan se chargent en **moins de 2 s** sur une base contenant
    l'historique complet.

  Si le seuil n'est pas atteint, regrouper les requêtes concernées et mesurer à nouveau. Si le
  réseau bloque ou si le pilote ne suit pas, **arrêter et revenir vers l'utilisateur** avant toute
  autre tâche (les pistes de repli seraient la réplique embarquée ou un autre hébergeur
  compatible SQLite).
- Bascule de base sans redémarrage (reconstruire `app.state.repo` et le `HistoryRunner`).
  Une copie vers le cloud n'est considérée complète qu'après l'écriture d'un **marqueur de fin**
  en base. Une base sans ce marqueur compte comme « vide » (copie interrompue à refaire) et ne
  remplace jamais les données d'un PC.
- « Effacer mes données du cloud » vide toutes les tables de l'application dans la base cloud.
- Forme exacte des tables ajoutées (GPX, état d'import, état de synchro, verrou, version de
  schéma), durée et prolongation du verrou.
- Identifiant de PC pour le verrou (nom de machine + identifiant aléatoire stocké localement).
- Textes de l'interface et du guide Turso (README + lien depuis les Réglages).
- Tests : la source Turso est remplacée par une seconde base SQLite dans les tests de bascule ;
  test réel Turso marqué comme les tests `live` existants.
