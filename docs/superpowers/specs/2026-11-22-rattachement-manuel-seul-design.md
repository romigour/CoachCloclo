# Rattachement manuel uniquement

## Pourquoi

Le 22/11, au redémarrage après la mise à jour 1.0.3, la synchro a rattaché automatiquement un 10 km couru le dimanche (43 min, FC 162) à la séance « EF 45 minutes » prévue le lundi 23. Le rattachement automatique ne regarde que le sport, la date (±1 jour, avant comme après) et la durée (±30 %). La séance est passée « réalisée » avant même sa date, et Claude a proposé une adaptation sur une base fausse.

Romain préfère rattacher ses sorties lui-même : la synchro ne doit plus jamais rattacher une activité à une séance.

## Objectifs

- La synchro importe les activités sans jamais les rattacher.
- Rattacher une activité à la main reste le seul moyen de passer une séance en « réalisée ».
- Claude continue d'analyser les séances réalisées : celles rattachées à la main depuis la dernière proposition lui sont transmises à la synchro suivante.

## Non-objectifs

- Pas de suggestion de rattachement (« cette activité ressemble à… »).
- Pas de reprise des rattachements automatiques passés (`match_source = "auto"`) : ils restent tels quels, Romain détache à la main si besoin.
- Rien à changer sur le mobile (lecture seule).

## Anti-objectifs

- Une séance rattachée à la main ne doit jamais échapper à l'analyse de Claude.
- Une séance détachée avant la synchro ne doit pas être transmise à Claude comme réalisée.

## Approches envisagées

1. **Suppression seule** : on retire le rattachement de la synchro. Écartée : Claude n'analyserait plus aucune séance réalisée.
2. **Analyse à la synchro suivante** (retenue par Romain) : le rattachement manuel note la séance « à analyser », la synchro suivante transmet toutes les séances notées à Claude en une seule proposition. Ça réutilise le circuit actuel, laisse le temps de corriger une erreur et regroupe plusieurs rattachements.
3. **Analyse immédiate** : un appel à Claude à chaque rattachement. Écartée : attente à chaque clic, et une erreur part directement chez Claude.

## Conception

- **Synchro** (`coach/services/sync.py`) : plus d'appel à `match_activities`. Les séances manquées sont toujours marquées (`mark_missed`, toutes les séances non réalisées). `match_activities` et ses tests sont supprimés.
- **État de synchro** (`SyncState`) : nouveau champ `pending_done: list[int]`, les ids des séances rattachées à la main en attente d'analyse.
- **Rattachement manuel** (`POST /activities/{id}/match`) : quand une séance passe « réalisée », son id est ajouté à `pending_done` (sans doublon). Quand une activité est détachée et que l'ancienne séance n'a plus d'activité, son id est retiré de `pending_done`. Une séance qui était « manquée » et qu'on rattache est ajoutée aussi.
- **Proposition** : `proposal_due` devient vrai s'il y a des séances dans `pending_done` ou des séances manquées. `_propose` reçoit pour `done` les séances de `pending_done` encore « réalisées » avec leur activité rattachée (les autres sont ignorées). `pending_done` est vidé une fois la proposition enregistrée.
- **Cas particuliers** : en arrêt (blessure ouverte), `pending_done` est conservé jusqu'à la reprise, comme `proposal_due`. Cycle clos à la synchro : `pending_done` est vidé.
- **Guide** (`docs/guide/index.html`) : les deux phrases qui annoncent un rattachement automatique disent désormais que tu rattaches ta sortie à la séance, puis que Claude l'analyse à la synchro suivante.

## Laissé au développeur

- Où exactement vider `pending_done` en cas de clôture de cycle.
- Le libellé exact dans le guide.
