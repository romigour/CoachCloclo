# Rapprochement des tours : plan

**Spec :** docs/superpowers/specs/2026-11-24-rapprochement-tours-fit-design.md. Exécution directe.

1. Tests en échec : `flat_steps` → `[1, 2, 3, 2, 3, 2, 3, 5]` ; deux blocs de répétitions ; séance 8 × 1 min
   avec tour final ; tours finaux sur séance simple ; aucun tour avec étape → dégradé ; sans étape au milieu → dégradé.
   Fixture `activity_splits.json` et tests existants alignés sur l'ordre FIT.
2. `coach/export/garmin_workout.py` : `flat_steps` numérote dans l'ordre FIT, export inchangé.
3. `coach/analysis/laps.py` : `_group_laps` retire les tours de fin sans étape.
4. Commentaires « provisoire » retirés (`client.py`, `port.py`) ; suite `pytest` complète.
