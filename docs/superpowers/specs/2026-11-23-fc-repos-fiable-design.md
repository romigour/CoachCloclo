# FC repos fiable et renvoi des séances à la montre — design

Date : 2026-11-23 · Taille : projet

## Pourquoi

Les zones FC sont calculées par l'app avec la FC de réserve (voir `2026-11-22-zones-fc-reserve-design.md`),
à partir de la FC repos que fournit Garmin (`lastSevenDaysAvgRestingHeartRate`, sinon la valeur du jour,
sinon celle du dernier instantané). L'athlète ne porte pas sa montre en continu. Sans montre la nuit,
Garmin calcule la FC repos sur la journée : elle sort trop haute, la moyenne sur 7 jours l'est aussi, et
toutes les zones montent d'autant. Constat de l'athlète : les bpm affichés pour une séance EF étaient trop
hauts, alors qu'il tourne autour de 130 bpm en EF.

Deuxième problème : les séances déjà envoyées sur la montre gardent les bpm calculés le jour de leur envoi.
Une FC repos corrigée ne les atteint donc pas.

## Objectifs

1. Une FC repos calculée seulement à partir des **nuits où la montre était portée**, qui suit l'évolution
   de l'athlète sur quelques semaines.
2. Une **FC repos saisie à la main**, facultative, prioritaire sur le calcul automatique.
3. L'app **affiche la FC repos retenue et sa provenance** (« 47 bpm, moyenne de 9 nuits » / « saisie à la
   main » / « valeur Garmin »), pour que l'athlète puisse vérifier.
4. Les **séances à venir déjà envoyées sur Garmin** sont renvoyées avec les nouveaux bpm quand les zones FC
   changent de façon notable.

## Non-objectifs

- La définition des zones (Karvonen, Z2 = 60–70 % de réserve) et la composition des séances par le coach ne
  changent pas.
- La FC max ne change pas.
- Les **stratégies de course** gardent leur base figée (bouton « Actualiser » existant) : elles ne sont pas
  renvoyées automatiquement.
- Pas d'adaptation des zones à la FC repos d'un matin donné : une FC repos haute un jour signale de la
  fatigue, ce n'est pas une raison de courir plus fort.
- Le « temps par zone » des activités (`hr_zones_s`) reste celui de Garmin.

## Anti-objectifs

- Se retrouver sans zones alors qu'on en avait avant : chaque étape a un repli (voir « Calcul »).
- Des renvois à la montre à chaque synchro pour 1 bpm d'écart (écritures Garmin inutiles, risque de
  séances en `sync_error`).
- Laisser des workouts orphelins sur Garmin : le renvoi passe par le mécanisme de remplacement sûr existant.
- Toucher une séance passée, réalisée ou manquée.

## Approches envisagées

- **A. FC repos saisie à la main uniquement** — écartée : précise, mais figée ; ne suit pas l'évolution.
- **B. Moyenne des nuits où la montre était portée** — automatique et suit l'évolution, mais rien pour
  corriger si le filtre se trompe.
- **C. B, plus une saisie manuelle prioritaire** — **retenue (choix de l'athlète)**.

## Calcul de la FC repos (C)

Ordre de priorité, à chaque `refresh_snapshot` :

1. **Saisie manuelle** si elle est renseignée.
2. **Moyenne des nuits portées** sur les **14 derniers jours** (aujourd'hui compris), arrondie, s'il y en a
   **au moins 3**. Une nuit compte si Garmin a enregistré un sommeil pour ce jour-là (durée de sommeil > 0)
   et une FC repos.
3. Sinon, la FC repos du **dernier instantané de provenance `nights`** (on garde une bonne valeur
   automatique plutôt que de retomber sur une valeur Garmin trop haute). *(Choix de Claude)* : seuls les
   instantanés `nights` servent de base, jamais un `manual` ni un `last_good` ; ainsi, vider la saisie
   manuelle rend vraiment la main au calcul automatique, et la valeur reprise ne dérive pas d'un repli à
   l'autre.
4. Sinon, comportement actuel : `lastSevenDaysAvgRestingHeartRate`, puis `restingHeartRate` du jour, puis
   la valeur du dernier instantané.

*(Choix de Claude : 14 jours et 3 nuits minimum.)* Avec 14 jours, la valeur suit l'évolution en deux
semaines environ, et 3 nuits évitent qu'une seule nuit atypique décide des zones.

**Lecture Garmin.** Par jour : FC repos (`get_heart_rates(day)["restingHeartRate"]`) et présence d'un sommeil
(`get_sleep_data(day)`, durée de sommeil du `dailySleepDTO`). Les jours passés ne changent plus : on les met
en cache en base (FC repos du jour et « nuit portée » oui/non), et chaque synchro ne relit que les jours
absents du cache, plus aujourd'hui et hier (Garmin peut finaliser une nuit en retard). Une erreur Garmin sur
un jour fait sauter ce jour pour cette synchro, sans faire échouer la synchro ; il sera relu la fois suivante.

**Provenance.** L'instantané (`AthleteSnapshot`) enregistre, en plus de `hr_rest`, sa provenance :
`manual`, `nights` (avec le nombre de nuits), `last_good` ou `garmin`.

## Saisie manuelle

- Un champ « FC repos » dans les réglages de l'app (interface web ; mobile si les réglages y existent),
  vide par défaut, entre 30 et 100 bpm. Le vider rend la main au calcul automatique.
- Stockée en base (état de l'athlète, `repo.set_state`), pas dans `settings.json` : elle doit suivre les
  données (Turso, mobile).
- À côté du champ : la FC repos retenue et sa provenance, et la valeur automatique (nuits portées) même
  quand la saisie manuelle prime, pour comparer.
- Enregistrer une nouvelle valeur (ou la vider) recalcule les zones tout de suite (nouvel instantané) et
  déclenche le renvoi des séances (section suivante), sans attendre la synchro.

## Renvoi des séances déjà envoyées

**Quelles séances.** Statut `exported`, `scheduled_date > aujourd'hui`, dans n'importe quel cycle actif ;
plus la séance prévue **aujourd'hui** seulement si aucune activité n'est enregistrée aujourd'hui (choix de
l'athlète). La synchro ne rattache jamais d'activité seule : une séance courue ce matin peut rester
`exported`, et la remplacer supprimerait sur Garmin le workout avec lequel il vient de courir.

**Quand.** Après chaque calcul de zones qui peut les changer : à la synchro (après `refresh_snapshot`), et
à l'enregistrement de la saisie manuelle.

**Critère.** Chaque séance exportée retient les zones FC utilisées à son envoi (nouveau champ, ex.
`export_hr_zones_json`, rempli par `export_session`, par `_sync` lors d'un remplacement, et par le renvoi).
Une séance est renvoyée si :
- le workout généré avec les zones actuelles diffère de celui généré avec les zones retenues (une séance
  sans cible FC n'est donc jamais renvoyée), **et**
- au moins une borne de zone FC a bougé de **2 bpm ou plus** *(choix de Claude)*.

Une séance exportée avant ce changement n'a pas de zones retenues : elle est renvoyée une fois (c'est le cas
des séances actuelles, calculées avec une FC repos trop haute).

**Comment.** Par le mécanisme de remplacement existant : `mark_for_cleanup(s, removal=False)` puis
`sync_marked` (upload et planification du nouveau workout à la même date, puis retrait de l'ancien). Une
erreur Garmin laisse la séance en `sync_error` avec le bouton « Réessayer » existant, sans faire échouer la
synchro ni la saisie.

**Retour à l'athlète.** Le résultat de la synchro (et de l'enregistrement de la saisie) indique combien de
séances ont été renvoyées à la montre, ex. « 3 séances mises à jour sur ta montre (FC repos 47) ».

## Conséquences

- Les bpm affichés dans l'app, l'analyse des tours et le prompt du coach suivent déjà les zones courantes :
  rien à changer de ce côté.
- La synchro fait plus d'appels Garmin la première fois (14 jours × 2), puis 2 à 3 jours × 2.

## Laissé au constructeur

- Nom et forme exacts du cache des nuits et du champ des zones retenues sur la séance, migration de schéma
  (SQLite local et Turso).
- Emplacement exact du champ dans les réglages et libellés.
- Vérifier sur une vraie réponse Garmin le champ de durée de sommeil le plus fiable pour « nuit portée ».
- Tests : calcul (priorités, seuil de 3 nuits, replis), cache (relecture d'aujourd'hui et d'hier), critère
  de renvoi (séance sans cible FC, écart < 2 bpm, séance passée, séance du jour avec et sans activité du jour,
  séance sans zones retenues), erreurs Garmin
  pendant la lecture et le renvoi, API et interface de la saisie.
- Mise à jour de `docs/guide` si les zones FC y sont décrites.
