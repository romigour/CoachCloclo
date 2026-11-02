# Roadmap CoachCloclo

Idées d'amélioration, dans l'ordre où elles ont été notées.

## Fait

- [x] Renommer l'application en CoachCloclo
- [x] Mettre le projet sur GitHub ([romigour/CoachCloclo](https://github.com/romigour/CoachCloclo))
- [x] Installation facile sans cloner le projet : les scripts d'installation récupèrent la wheel de la dernière release GitHub (il reste à publier la première release, voir « Publier une version » dans le README)
- [x] Page de statistiques globales sur l'ensemble de mes données, avec filtres. Elle doit être belle mais surtout utile. Ajouter mes records sur les distances, les temps de course officiels et les classements si possible
- [x] Installateur Windows avec mise à jour intégrée (lancement sans terminal, écran d'accueil, mode LAN dans les Réglages)
- [x] Demander des idées de fonctionnalités pour la suite de l'application (ajoutées ci-dessous)
- [x] Stratégie du jour J : prédiction de temps, allure ou temps par segment à partir du GPX (montées, descentes), plan de ravitaillement et barrières horaires en trail, export sur la montre
- [x] Icône des Réglages en engrenage
- [x] Choix du thème Auto / Clair / Sombre dans les Réglages
- [x] Nouveau logo (« C » en virage de piste) décliné en favicon, PWA et icône Windows
- [x] Allure min/km (ou plage de FC en bpm) à côté des zones dans le détail des séances

## À faire

- [ ] Publier une page statique avec mon programme d'entraînement (GitHub Pages ?)
- [ ] Demander un avis lors de la récupération d'une séance effectuée : séance non effectuée, trop difficile, bien, trop facile. L'avis doit agir très légèrement sur la suite du programme
- [ ] Se renseigner : est-il possible de renommer une activité Garmin exportée vers Strava, pour reprendre dans Strava le bon titre et la bonne description de l'activité Garmin ?
- [ ] README avec des captures d'écran de l'application
- [ ] Audit de sécurité
- [ ] Comparer le prévu et le réalisé étape par étape : rapprocher les tours (laps) Garmin des étapes du workout, l'afficher dans le détail de la séance et le transmettre à Claude pour l'ajustement (aujourd'hui il ne voit que le résumé global de l'activité)
- [ ] Forme et fatigue dans le contexte de Claude : charge aiguë/chronique (ATL/CTL), statut d'entraînement Garmin, VFC, sommeil, Body Battery ; graphe « forme / fatigue » dans Stats
- [ ] Indisponibilités : vacances, blessure, jours impossibles (« pas dispo le mardi ») qui déclenchent une proposition de replanification
- [ ] Valider les hypothèses sur les données Garmin réelles : fixtures de test synthétiques à remplacer, unité de la vitesse seuil, identifiant de planification, format des workouts (voir « Données réelles à vérifier » dans le README)
- [ ] Stratégie du jour J, version hybride : en plus des calculs, Claude rédige un court texte de stratégie (« pars prudemment jusqu'au km 12, la montée 3 est la clé… »)
- [ ] Stratégie du jour J, calibration sur l'historique : ajuster le modèle de prédiction avec mes sorties trail passées (vitesse ascensionnelle réelle, allure en descente)
- [ ] Bilan de fin de préparation à l'archivage de l'objectif : prévu contre réalisé, progression des métriques, temps visé contre temps réel ; contexte réutilisé pour la préparation suivante
- [ ] Discuter avec le coach : question libre avec le contexte du plan, la réponse pouvant proposer un ajustement à valider
- [ ] Rappel de la séance du jour par une notification Windows (icône près de l'horloge)
- [ ] Vérifier le fonctionnement des propositions de Claude : comment sont construites et appliquées ses mises à jour du programme ?
- [ ] Revoir le design pour éviter le défilement sur PC
- [ ] Ajouter des objectifs secondaires
