# Bilan de la semaine : kilomètres et D+ prévus

**Pourquoi** : donner, à titre indicatif, une idée de la semaine et de la charge à venir.

## Objectifs
- Bloc « Bilan de la semaine », sous la durée : `≈ 36 km · ≈ 450 m D+`.
- D+ : somme de ce que Claude prescrit par séance. Programme sans D+ (route plate) : pas de D+ affiché.
- Même affichage sur le bureau et la PWA mobile.

Non-objectifs : D+ envoyé à Garmin, réalisé vs prévu, calendrier du programme, nouvelle zone sur la carte de séance.
Anti-objectif : afficher un D+ inventé, ou un total de km qui oublie en silence une séance de course.

## Approches pour le D+
- A. Estimer depuis les sorties récentes : immédiat, mais ne suit pas le programme.
- **B. Donnée structurée fixée par Claude (retenue par l'utilisateur)** : le D+ vient du programme et suit sa
  progression ; vide pour les séances déjà créées.
- C. Le lire dans le texte des descriptions : fragile (« 2 × 300 m », fourchettes), écarté.

## D+ (B)
- `SessionSpec.d_plus_m: int | None` (≥ 0, défaut `None`), colonne `session.d_plus_m INTEGER` ajoutée par migration ;
  `SCHEMA_VERSION` et `KNOWN_SCHEMA` (PWA) passent à 4.
- Copié par `from_spec`, `to_spec` et l'application d'un `modify` ; présent dans l'API `plan` et la lecture Turso.
- Prompts de génération et d'ajustement, si un objectif du cycle a du D+ : renseigner `d_plus_m` pour les séances
  qui travaillent le dénivelé (surtout sorties longues et côtes), de façon progressive, et le mentionner dans la
  description ; `null` sinon. Sans D+ au programme : laisser `null`. `_session_line` indique le D+ existant.
- Affichage : somme des séances de course de la semaine, masquée si elle est nulle ou absente.
- Pas d'échec de validation si Claude ne renseigne rien.

## Kilomètres
- Calculés dans l'interface, répétitions dépliées, vélo exclu, arrondis au km ; toutes les séances de la semaine
  comptent, faites ou non, comme la durée.
- Étape en distance : valeur exacte. En durée : durée ÷ milieu de la zone d'allure ; FC Z1–Z5 assimilées à récup, EF,
  marathon, seuil, VMA ; sans zone : récup pour `recovery`, EF sinon.
- Séance en FC avec un D+ prévu : allure moyenne (distance totale / temps total) des sorties trail des
  8 dernières semaines s'il y en a, sinon l'allure de zone. (Choix proposé.)
- Zones d'allure absentes : km masqués si une étape en dépend.

## Laissé au réalisateur
Découpage des fonctions, formulation exacte du prompt, tests (Python, Svelte, Turso).
