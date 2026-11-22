# Historique long dans les prompts de Claude — conception

## Intention

Aujourd'hui, Claude ne voit que les 8 dernières semaines d'activités, récupérées en direct chez Garmin
(`recent_history`, `HISTORY_DAYS = 56`, au plus 60 lignes). Il juge donc la forme récente, mais pas le
niveau de fond : volume encaissé sur l'année, coupures, courses déjà réussies. Or tout l'historique est
déjà en base (import de la page Stats), ainsi que les compétitions saisies et les records Garmin.
L'objectif est de donner ce recul à Claude sans alourdir beaucoup le prompt.

## Objectifs / non-objectifs

- Objectif : un bloc « historique long » ajouté au prompt de génération **et** au prompt d'ajustement,
  lu dans la base, sans appel Garmin supplémentaire.
- Le détail des 8 dernières semaines reste inchangé (même source, même format).
- Non-objectif : donner un outil à Claude, changer les schémas de réponse, modifier l'interface.
- Anti-objectif : un prompt qui gonfle de façon notable (cible : environ 30 lignes de plus au maximum),
  ou une génération qui échoue parce que la base est vide ou incomplète.

## Approches envisagées

- **A. Élargir la fenêtre détaillée** (16 à 26 semaines, une ligne par activité) : trivial, mais le
  prompt grossit vite et on n'a toujours pas de vision sur l'année.
- **B. Deux niveaux de détail** — **retenue** : 8 semaines détaillées comme aujourd'hui, plus un résumé
  mensuel sur 12 mois, les compétitions passées et les records, lus en base. Bon rapport recul/coût.
- **C. Outil de consultation de l'historique pour Claude** : écartée, contraire au principe « Python
  prépare le contexte, Claude n'a aucun outil », plus coûteuse.

## Conception (B)

Nouvelle fonction de texte dans `coach/llm/prompts.py` (par exemple `_long_history_text`), appelée par
`build_generation_prompt` et `build_adjustment_prompt` juste après le bloc d'historique récent. Les
données sont lues par les services (`plans.py`, `adjust.py`) depuis le `Repo` et passées en paramètre,
comme `history` aujourd'hui ; `prompts.py` reste sans accès à la base.

Contenu du bloc, dans cet ordre :

1. **Volume mensuel sur les 12 derniers mois** (mois en cours compris), une ligne par mois, du plus
   récent au plus ancien. Course à pied (familles `run` et `trail` de `coach/stats/normalize.py`) :
   nombre de sorties, km, heures, D+, plus longue sortie (km). Autres sports : heures totales, si non
   nulles. Les mois sans aucune course sont gardés (« aucune course ») : ils montrent les coupures.
2. **Compétitions passées** : les courses saisies (`repo.races()`, hors `excluded`), les plus récentes
   d'abord, au plus 15 : date, nom si connu, distance, D+, temps officiel (sinon la durée de
   l'activité), classement général si connu.
3. **Records personnels Garmin** (`repo.records()`) : 5 km, 10 km, semi, marathon, plus longue sortie,
   avec leur date.

Une partie sans données est omise. Si la base ne contient aucune activité (`has_activities()` faux,
import pas encore fait), le bloc entier est omis et le prompt est identique à celui d'aujourd'hui.

Une phrase d'en-tête indique à Claude l'usage attendu : situer le niveau de fond et la capacité de
charge ; la forme actuelle reste donnée par les 8 dernières semaines.

## Laissé au constructeur

- Le format exact des lignes (rester compact, à l'image de `_activity_line`).
- Le nom des fonctions et l'endroit où agréger (un petit module pur dans `coach/analysis/` est
  bienvenu, testable sans base).
- Les tests : agrégation mensuelle (mois vide, autres sports), plafonds, bloc omis sans données,
  présence du bloc dans les deux prompts.
