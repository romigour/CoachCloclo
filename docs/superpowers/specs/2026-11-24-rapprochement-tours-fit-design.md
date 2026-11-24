# Rapprochement des tours : numérotation FIT et tours de fin

Approuvé le 2026-11-24 (petit changement).

**Pourquoi.** Une VMA 8 × 1 min exécutée exactement comme prévu n'était pas reconnue par « Prévu / réalisé ».

**Constat** (activité réelle) : échauffement 1, (actif 2, récup 3) × 8, retour au calme 5 (`wktStepIndex` + 1),
puis un tour sans étape, couru après la fin du workout.

- Garmin numérote les étapes exécutées dans l'ordre du fichier FIT : le groupe de répétition occupe un rang
  *après* ses enfants. Le `stepOrder` de l'export le place *avant*. La base 1 est confirmée.
- Le tour final sans étape faisait rejeter toute la séance, répétitions ou non.

**Changement.**

- `flat_steps` numérote dans l'ordre FIT ; l'export (`stepOrder`) est inchangé.
- Les tours sans étape en fin d'activité sont ignorés pour le rapprochement, mais restent dans `laps`.
  Sans étape au milieu : toujours ambigu, donc mode dégradé. Aucun tour avec étape : mode dégradé.

**Hors périmètre.** Bornes de zones sans tolérance ; format des tours enregistrés (rien à relire chez Garmin).

**Approches.** Retenue : numérotation FIT. Écartées : rapprochement par durée (faux dès qu'une étape est
raccourcie) ; conversion dans le client Garmin (il ne connaît pas la séance).
