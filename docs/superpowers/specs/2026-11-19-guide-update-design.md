# Mise à jour du guide de présentation — design

Date : 2026-11-19 · Taille : petite modification (design court)

## Intention

`docs/guide/index.html` (publié sur GitHub Pages) n'a plus été mis à jour sur le fond depuis le 10 novembre. Ses captures datent de la v0.7.3 alors que l'appli est en 0.13.0. Ce guide s'adresse aux **nouveaux utilisateurs**, et son but est de **leur donner envie d'essayer**. C'est une vitrine, pas une notice.

## Objectifs

- Décrire l'appli telle qu'elle est en 0.13.0 : l'écran « Ma semaine », les cycles à plusieurs objectifs avec priorités, les courses rapprochées et les blocs, la clôture du cycle et la préparation du suivant, le stockage cloud et la consommation Claude.
- Refaire les captures avec les **vraies données de l'utilisateur**. C'est son choix, en sachant qu'elles seront publiques sur GitHub Pages.
- Corriger la phrase devenue fausse : « l'appli ne parle qu'à Garmin et à Claude ».

## Non-objectifs

- Le README, la documentation Turso et la page de la version mobile.
- La carte Diagnostic, qui ne donne pas envie.
- Une refonte visuelle.

## Anti-objectif

Une page qui ressemble à une notice technique. Le contenu technique (Turso, coûts) reste discret.

## Approches

1. **Garder la page et en refaire le contenu (choisie).** Le design actuel reprend déjà les couleurs de l'appli et fonctionne en clair, en sombre et sur mobile. C'est la voie la plus rapide.
2. **Refondre la page.** Plus long, sans gain pour l'objectif.
3. **Mettre à jour le texte sans nouvelles captures.** Écartée par l'utilisateur, car une vitrine sans images à jour donne moins envie.

## Design

- **Accroche et étapes :** l'accroche parle de « ta saison » plutôt que de « ta prochaine course ». L'étape 02 devient « Fixe tes objectifs » (plusieurs courses, avec une priorité chacune).
- **Image d'en-tête :** « Ma semaine » remplace l'écran Aujourd'hui.
- **Nouvelle section « Ta saison »**, après Statistiques, avec une ou deux captures de la page Objectifs. Elle présente la course principale, les courses de préparation, les courses rapprochées et les blocs (avec l'avertissement), et la préparation du cycle suivant. La navigation du haut gagne une entrée vers cette section.
- **Section Plan :** recentrée sur « Ma semaine » (séance du jour, programme, envoi sur la montre).
- **Ajustements, Jour J, Apparence :** le texte est conservé et les captures sont refaites.
- **Partie téléphone :** les explications sur le LAN et la version mobile sont conservées. Une ligne ajoutée présente le stockage cloud Turso, qui permet aussi de partager la base entre deux PC.
- **Consommation Claude :** une courte mention pour rassurer sur le coût.
- **Pied de page :** « tes données restent chez toi, ou dans ta propre base Turso si tu l'actives ». Les captures sont indiquées en version 0.13.0.
- **Captures :** l'appli tourne sur la base de l'utilisateur et les captures sont prises dans le navigateur intégré, en clair et en version mobile. Elles sont enregistrées en JPG compressé, comme les actuelles. Les images qui ne servent plus sont supprimées.

## Laissé au réalisateur

- Le choix exact des écrans et des cadrages pour chaque capture.
- La formulation des textes, en tutoyant comme dans l'existant.
- S'il n'y a pas de cycle à plusieurs objectifs dans la base, prévenir l'utilisateur avant de faire les captures de « Ta saison ».
