# Consommation Claude dans les Paramètres — design

Date : 2026-11-15 · Taille : petit chantier (design court)

## Intention

Savoir combien coûte une génération de plan (et, accessoirement, un ajustement), avec un
minimum de suivi visible dans la page Paramètres. Unité : coût approximatif en euros.

## Objectifs / non-objectifs

- **Objectifs** : enregistrer chaque action Claude (génération de plan, ajustement) avec son coût
  estimé ; afficher dans Paramètres le coût moyen d'une génération, le total du mois et les
  10 dernières actions.
- **Non-objectifs** : graphiques, filtres, export ; affichage sur la version mobile ; historique
  antérieur à la fonctionnalité (rien n'est enregistré aujourd'hui).
- **Anti-objectifs** : afficher une part de quota d'abonnement inventée (`claude -p` ne la fournit
  pas) ; laisser croire que le montant affiché est ce que l'utilisateur paie en mode abonnement.

## Approches considérées

- **A. Table dans la base CoachCloclo** — *retenue*. L'historique vit avec les plans et suit le
  stockage cloud (Turso). Coût : montée de `SCHEMA_VERSION`.
- **B. Fichier journal local (JSONL)** — plus simple, mais reste sur un seul PC et ne suit pas le cloud.
- **C. Rattacher le coût aux données existantes (Proposal)** — écartée : une génération de plan n'a
  pas d'enregistrement propre.

## Ce qui a été décidé

- **Capture** : les fournisseurs remontent l'usage en plus du texte.
  - CLI : l'enveloppe JSON de `claude -p --output-format json` fournit `total_cost_usd`,
    `duration_ms` et `usage` (tokens entrée/sortie/cache) — noms de champs à vérifier sur une
    sortie réelle.
  - API : `msg.usage` (tokens) ; coût calculé via une petite table de tarifs par modèle (tarifs
    officiels Anthropic au moment de l'implémentation), durée mesurée localement.
- **Agrégation** : une action = une ligne, même si `ask_structured` a fait 2 essais ; on cumule
  tokens, coût et durée des essais et on garde le nombre d'essais. Une action en échec
  (réponse invalide après 2 essais, limite, timeout…) est enregistrée avec ce qui a été consommé
  et un statut `failed`.
- **Stockage** : nouvelle table SQLModel (ex. `LlmUsage`) : `created_at`, `kind`
  (`generation` | `adjustment`), `mode` (`cli` | `api`), `model`, `attempts`, `input_tokens`,
  `output_tokens`, `cost_usd`, `duration_ms`, `status` (`ok` | `failed`). Le coût est stocké en
  dollars ; la conversion en euros se fait à l'affichage.
- **Euro** : taux fixe dans le code (≈ 0,92 €/$), montants affichés précédés de « ≈ ».
- **Affichage** : carte « Consommation Claude » sous « Mode Claude » dans `Setup.svelte` :
  ```
  Ce mois-ci : 4 générations · 3 ajustements · ≈ 2,10 €
  Coût moyen d'une génération de plan : ≈ 0,38 €
  Dernières actions (10) : date · type · ≈ coût · « 2 essais » / « échec »
  (tokens et durée en détail dépliable ou au survol)
  Note : estimation équivalent API, ≈ 0,92 €/$ ; en abonnement ce n'est pas ce que tu paies.
  ```
  Le coût moyen porte sur les générations réussies. Si aucune donnée : un message court
  (« Aucune génération enregistrée pour l'instant »).

## Laissé au constructeur

- Forme du retour d'usage côté fournisseur (objet résultat ou attribut `last_usage`) — en
  gardant `FakeLLMProvider` simple pour les tests.
- Où enregistrer la ligne (dans `ask_structured` avec un `kind` passé par les services, ou dans
  les services) — l'enregistrement en échec doit fonctionner dans les deux cas.
- Route API (lecture seule, ex. `GET /api/llm-usage`) et forme du JSON ; masquage en mode mobile.
- Impact de la montée de `SCHEMA_VERSION` sur la PWA mobile lisant Turso.
- Tests : backend (capture CLI/API, cumul des essais, échec enregistré, agrégats) et composant Svelte.
