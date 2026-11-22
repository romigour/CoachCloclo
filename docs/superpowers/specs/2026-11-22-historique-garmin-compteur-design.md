# Compteur « Historique Garmin » dans les Réglages — design court

## Intention

Réglages > Données affiche « 0 activités importées » alors que la base contient 777 activités.
Ce chiffre est `HistoryState.imported`, c'est-à-dire le nombre d'activités **ajoutées** lors du
dernier import (`store_summaries` saute celles déjà en base). Après une réimportation sans
nouveauté, il vaut donc 0. L'écran doit montrer ce que l'utilisateur cherche : le total d'activités
en base, puis ce qu'a apporté le dernier import.

## Objectifs / non-objectifs

- Objectif : au repos, afficher le total réel d'activités en base et, s'il existe, la date du
  dernier import avec son nombre de nouvelles activités.
- Objectif : pendant un import, présenter le compteur comme « nouvelles » et non comme un total.
- Non-objectif : modifier la logique d'import (pagination, verrou, reprise).
- Anti-objectif : un compteur qui retombe à 0 alors que la base est pleine.

## Approches

1. **Total en base + infos du dernier import (retenue).** `/api/status` expose en plus un total
   compté en base et `finished_at`. Le chiffre affiché est toujours vrai, quel que soit l'import.
2. Renommer seulement le libellé (« 0 nouvelles activités ») : exact, mais le total disparaît.
3. Faire suivre le total par l'import lui-même : mélange « vu » et « ajouté », et reste faux si des
   activités arrivent par une autre voie (synchronisation de la semaine).

## Design

- `Repo.count_activities() -> int` (requête `count` sur `Activity`).
- `/api/status` : `history` gagne `total: int` et `finished_at: str | None` (ISO). Dans la branche
  « base cloud indisponible », `total: 0` et `finished_at: None`.
- Type `Status` côté web mis à jour en conséquence.
- `Setup.svelte`, section Historique Garmin :
  - `running` : « Import en cours… ({imported} nouvelles) » ;
  - `error` : inchangé ;
  - sinon : « {total} activités » et, si `finished_at`, « · dernier import le {date courte},
    {imported} nouvelle(s) ». Accords singulier/pluriel gérés.
- Tests : un test API couvre une réimportation sans nouveauté (`imported` = 0, `total` = nombre en
  base) ; un test repo couvre `count_activities`.

## Laissé à l'implémenteur

Le format exact de la date (cohérent avec le reste de l'écran) et la mise en forme de la seconde
ligne.
