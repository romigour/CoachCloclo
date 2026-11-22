# Détacher une activité d'une séance

## Pourquoi

Une séance peut afficher « Activité : rattachée » sans détail : l'activité rattachée date d'une autre semaine (ex. le 10 km du dimanche 22/11 rattaché automatiquement à l'EF du lundi 23). La carte ne connaît que les activités datées de la semaine affichée, elle ne retrouve donc pas l'activité, et le bouton « Aucune » de « Corriger » (seul moyen de détacher) n'apparaît pas. Romain ne peut pas retirer ce rattachement.

## Objectifs

- La carte d'une séance retrouve toujours son activité rattachée, même datée d'une autre semaine, et l'affiche en détail.
- Un bouton **Détacher**, visible à côté de la ligne « Activité : … », remplace le bouton « Aucune » caché dans « Corriger ».

## Non-objectifs

- Pas de nouveau circuit de détachement côté serveur : `POST /activities/{id}/match` avec `session_id` nul fait déjà tout (statut repassé « à faire » / « envoyée », retrait de `pending_done`).
- Rien sur le mobile (lecture seule) au-delà de l'affichage du détail. Le mobile lit la base directement (`web/src/lib/turso/reads.ts`) : sa lecture des activités de la semaine reçoit le même ajout que l'API, vérifié par les fixtures de parité.

## Anti-objectifs

- La « dernière activité » de la semaine en cours (`Week.svelte`) ne doit pas afficher une activité datée d'une autre semaine.

## Approches envisagées

1. **La semaine renvoie aussi les activités rattachées à ses séances** (retenue) : petit changement, réutilise le détachement existant.
2. **Détacher par séance** : nouvel endpoint, bouton affiché dès que la séance est « réalisée ». Écartée : la carte resterait sur « rattachée » sans détail, on détache à l'aveugle.
3. **Chaque séance transporte son activité** : modifie le format des séances partout (mobile compris). Écartée : trop large pour le besoin.

## Conception

- **`GET /activities?week=N`** (`coach/api/app.py`) : renvoie les activités datées du lundi au dimanche de la semaine, plus celles rattachées à une séance du cycle actif dont `week_index == N`, sans doublon, triées par date.
- **`Week.svelte`** : le calcul de la « dernière activité » de la semaine en cours ne retient que les activités datées entre le lundi et le dimanche de la semaine.
- **`SessionCard.svelte`** : quand une activité est rattachée (`matched`), un bouton « Détacher » s'affiche à côté de « Corriger », sur la ligne « Activité : … ». Même action que l'ancien « Aucune » : `api.match(matched.id, null)`, puis rafraîchissement. Le bouton « Aucune » disparaît de la liste de « Corriger ». Pas de confirmation : on peut rattacher à nouveau en deux clics.
- **Tests** : test API pour une activité rattachée datée de la semaine précédente ; test du composant : « Détacher » présent avec une activité rattachée, absent sinon, et plus de « Aucune ».

## Laissé au développeur

- Requête exacte côté repo (méthode dédiée ou filtre dans l'endpoint).
