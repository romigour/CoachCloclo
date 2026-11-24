# Chargement rapide des pages et démarrage discret

À valider (projet, en deux lots livrables séparément).

## Pourquoi

L'utilisateur trouve les pages trop longues à charger, et voit « Analyse de ta séance par Claude… » à chaque
lancement même quand rien n'a changé.

## Constat (mesuré le 2026-11-24, appli installée, base Turso en Irlande)

| Mesure | Temps |
|---|---|
| `GET /api/version` (sans base) | 3 ms ; 3,2 s s'il arrive pendant un `GET /api/plan` |
| `GET /api/zones` (1 lecture) | 0,6 s |
| `GET /api/plan` (7 lectures) | 3,1 à 3,5 s ; 9,5 s quand trois arrivent ensemble |
| `GET /api/status` | 4,9 s |
| `POST /api/sync` sans changement ni appel à Claude | environ 27 s |
| Lecture HTTP directe (`/v2/pipeline`, connexion réutilisée) | environ 80 ms |
| 7 lectures en un seul envoi HTTP | 70 à 100 ms |

- Une lecture par `Repo` coûte environ 0,5 s, contre 80 ms en HTTP direct : `pool_pre_ping`, ouverture et fin de
  transaction, pilote `libsql`. La part de chacun n'a pas été mesurée.
- Pendant un appel `libsql`, tout le serveur est figé : le pilote garde vraisemblablement le verrou Python (GIL).
- `App.svelte` n'affiche rien avant `/api/status` et `/api/setup/status` ; les deux construisent un client Garmin
  (`garmin_state`), le second lance aussi le CLI Claude.
- Le plan, puis les imprévus et les activités, se chargent en chaîne. Chaque changement de page recharge tout.
- Le message ne dépend que de `status.cycle` ; Claude n'est appelé que si une proposition est due.

## Objectifs

- Page affichée en moins de 1 s au lancement (base joignable), moins de 0,3 s pour `plan`, `status`, `zones`,
  `cycle/events` et `activities` une fois la connexion ouverte.
- Aucun appel à la base ne fige les autres requêtes.
- Une page déjà vue réapparaît tout de suite.
- « Analyse de ta séance par Claude… » seulement pendant un appel réel à Claude.
- La synchro de démarrage ne bloque rien et n'écrit que ce qui a changé.

**Non-objectifs.** Changer de base, copie locale ou mode hors ligne, changement de schéma, refonte visuelle.
La vérification Garmin au démarrage reste (elle trouve les nouvelles sorties).

**À éviter.** Une écriture perdue ou jouée deux fois ; des données d'une autre base affichées après une bascule ;
une régression du mode local (SQLite) ou de la PWA mobile.

## Approches

- **A, retenue par l'utilisateur : garder Turso, accès HTTP direct et lectures regroupées.** Données toujours
  fraîches ; le point délicat est la gestion des écritures et transactions.
- B : copie locale synchronisée. Lectures instantanées, mais décalage entre PC et échecs de synchro à gérer.
- C : autre base. Réécriture du stockage et de la PWA, sans gain tant que l'accès reste le même.

Pour A, `pool_pre_ping` désactivé seul est écarté : le pilote continuerait à figer le serveur.

## Lot 1 : accès à la base

**Pilote.** Un module DBAPI maison, derrière le dialecte SQLAlchemy existant, remplace `libsql` pour les bases
distantes. Il parle le protocole HTTP Hrana v2 (`POST /v2/pipeline`) avec `httpx` (à déclarer en dépendance directe)
et un client partagé entre threads, connexions gardées ouvertes. `pool_pre_ping` et `pool_recycle` disparaissent.

**Transactions**, comme `pysqlite` aujourd'hui :
- hors transaction, un `SELECT` part seul, sans `BEGIN` ni `COMMIT` ;
- la première écriture envoie `BEGIN` dans le même envoi ; la transaction suit le jeton de flux (`baton`) renvoyé ;
- `commit` et `rollback` ferment le flux ; sans transaction ouverte, ils ne font aucun appel ;
- les erreurs SQL au milieu d'un envoi arrêtent les instructions suivantes.

**Nouvelles tentatives.** Un `SELECT` hors transaction est rejoué une fois si la connexion gardée ouverte a été
fermée. Une écriture ou un `COMMIT` n'est jamais rejoué : après l'envoi, on ne sait pas s'il a été appliqué.
Un flux expiré fait échouer la transaction entière (le serveur l'annule).

**Erreurs.** Le pilote lève de vraies exceptions DBAPI (`IntegrityError`, `OperationalError`…), que SQLAlchemy
enveloppe : `store_summaries` compte sur `IntegrityError`. Réseau et jeton refusé gardent les messages actuels de
`cloud_errors` ; une erreur SQL ordinaire ne passe jamais pour une panne réseau, donc une exception distincte est
nécessaire pour celle-ci. Le jeton n'apparaît ni dans les messages ni dans les journaux.

**Types.** Entiers 64 bits (chaînes dans le protocole), réels, texte, `NULL`, blobs (GPX) ; `rowcount` et
`lastrowid` exacts (le verrou Garmin dépend de `rowcount`). Certificats : magasin système, comme le reste de l'appli.

**Lectures regroupées.** `/plan` et `/status` au plus 3 envois à la base chacun : lectures en double supprimées
(`upcoming_goals` est lu 3 fois par `/plan`) et le reste envoyé ensemble. Les `IN`/comptes et la sélection de colonnes
évitent de charger `raw_json` là où il ne sert pas (`/activities`, `fetch_missing_laps`). `fetch_missing_laps` trouve
les activités sans tours en une seule requête.

**Compatibilité.** Mode local inchangé. Le paquet `libsql` est retiré de l'appli et de l'installateur si plus rien ne
l'utilise ; les tests qui s'en servent comme base fichier passent à un faux serveur HTTP au-dessus de SQLite.
La PWA n'est pas touchée.

## Lot 2 : démarrage et affichage

**Affichage sans attendre Garmin.** `/api/status` ne construit plus de client Garmin. L'état Garmin vient d'un appel
séparé, lancé en parallèle ; tant qu'il n'est pas connu, il vaut `checking` : ni message d'erreur, ni renvoi vers les
Réglages. Quand la réponse est `auth_required` et qu'aucune route n'a été demandée, l'accueil renvoie vers les Réglages
comme aujourd'hui. `/api/setup/status` ne retarde plus l'affichage, sauf sans base ni objectif (premier lancement).

**Chargement en parallèle.** Les imprévus ne dépendent plus du plan et partent avec lui ; les activités partent dès que
la semaine est connue. Une seule lecture de chaque donnée par affichage.

**Pages déjà vues.** Cache en mémoire dans le navigateur, par donnée (plan, imprévus, activités par semaine,
statistiques…) : affichage immédiat puis relecture et mise à jour. Rien n'est écrit sur le disque. Il est vidé après une
bascule de stockage ou un effacement de connexion. Après une écriture de l'utilisateur, les données concernées
sont relues ; une relecture plus ancienne n'écrase jamais une plus récente.
Si la relecture échoue, l'ancienne donnée reste et l'erreur s'affiche. Même comportement dans la PWA.

**Synchro de démarrage.** Elle part après le premier affichage du contenu. Pendant ce temps :
- bouton de la barre latérale « Synchronisation… », sans bandeau dans la page ;
- bandeau « Analyse de ta séance par Claude… » seulement pendant l'appel à Claude, signalé par le serveur
  (phase `garmin` ou `claude` lue par sondage sur une route qui ne touche pas à la base) ;
- une synchro manuelle se comporte pareil ; une erreur reste affichée.

À la fin, les pages sont relues seulement si la synchro a changé quelque chose de visible.

**Rien de changé, rien d'écrit.** La synchro compare avant d'écrire : instantané (pas de nouvelle ligne si identique à
la dernière du même jour), nuits, records, séances. L'heure de synchro et le verrou s'écrivent toujours. L'instantané
étant utilisé pour les zones, un changement de FC repos ou de seuil crée toujours une ligne. Le résultat de la synchro
gagne un champ `changed`.

## Vérification

- Pilote : tests contre un faux serveur Hrana (types, transaction, retour arrière, erreur au milieu d'un envoi, flux
  expiré, coupure, lecture rejouée, écriture non rejouée, jeton refusé, jeton absent des journaux) ; tests existants du
  stockage (copie, bascule, verrou entre PC) rejoués avec lui ; test réel facultatif comme `test_turso_live`.
- Concurrence : une lecture lente ne retarde pas `/api/version`.
- Nombre d'envois : `/plan` et `/status` au plus 3.
- Synchro deux fois sans changement : la seconde n'écrit que l'heure et le verrou, sans Claude ni renvoi à la montre.
- Front : contenu affiché avant la réponse Garmin ; bandeau Claude seulement en phase `claude` ; cache affiché puis
  mis à jour ; cache vidé à la bascule.
- Mesures avant/après sur la base réelle, en lecture, reportées dans le compte rendu. Un objectif manqué est signalé.

## Laissé au réalisateur

Découpage des fichiers, mécanisme d'envoi groupé, nom et forme de la route d'état Garmin et de phase, forme du cache.

## Choix de ma part, à corriger si besoin

- Deux lots, le lot 1 d'abord : il apporte l'essentiel du gain.
- Pilote maison plutôt qu'un paquet tiers : le protocole est petit et aucun paquet ajouté n'est nécessaire hors `httpx`.
- Cache en mémoire seulement : vide à chaque lancement.
- Bandeau « Synchronisation Garmin… » supprimé ; l'état reste dans la barre latérale.
