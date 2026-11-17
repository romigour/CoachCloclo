# Journaux de diagnostic Claude et Garmin — design

## Pourquoi

Diagnostiquer après coup une génération de plan qui échoue (cas actuel :
« Claude n'a pas répondu en 180 s ») ou un appel Garmin qui se passe mal.
Aujourd'hui `coachcloclo.log` ne contient ni les requêtes envoyées à Claude,
ni ses réponses, ni les appels Garmin.

## Objectifs

- Deux interrupteurs indépendants dans Paramètres : « Journal Claude » et
  « Journal Garmin ». Désactivés par défaut.
- Journal Claude : chaque appel avec mode (cli/api), modèle, prompt système
  et prompt complets, réponse complète, durée, tokens/coût, et l'erreur le cas
  échéant (délai dépassé, non connecté, réponse invalide, nouvelle tentative).
- Journal Garmin : chaque appel avec nom de la méthode, paramètres, durée,
  issue (succès, 429 + nouvelle tentative, erreur) et la réponse.
- Un bouton « Ouvrir le dossier des journaux » à côté des interrupteurs.

## Non-objectifs

- Pas d'écran de consultation des journaux dans l'application.
- Pas de stockage en base, pas de synchronisation vers Turso.
- Pas de correction du délai de 180 s dans ce travail (à traiter à part une
  fois les journaux disponibles).

## Anti-objectifs

- Un mot de passe, token Garmin, clé API Anthropic ou token Turso qui apparaît
  dans un journal.
- Le journal qui fait échouer ou ralentit sensiblement une génération ou une
  synchronisation (une erreur d'écriture est avalée, comme pour la consommation
  Claude).

## Approches envisagées

1. **Interrupteurs dans Paramètres + un fichier par catégorie** — retenue.
   Activable en deux clics dans l'application installée.
2. Variable d'environnement `COACH_TRACE=claude,garmin` — simple, mais
   impraticable pour une application lancée depuis le menu Démarrer.
3. Journaux en base + écran de consultation — confortable mais
   disproportionné pour un outil de diagnostic.

## Conception

- **Réglages** : deux champs booléens dans `Settings` (`config.py`),
  `trace_claude` et `trace_garmin`, lus/écrits via une route API et deux
  cases à cocher dans une carte « Diagnostic » de l'écran Paramètres. Effet
  immédiat, sans redémarrage.
- **Fichiers** : `<données>/logs/claude.log` et `<données>/logs/garmin.log`,
  chacun avec `RotatingFileHandler` 5 Mo × 3, encodage UTF-8, via des loggers
  dédiés (`coach.trace.claude`, `coach.trace.garmin`) qui ne propagent pas
  vers `coachcloclo.log`. Fonctionne aussi hors application de bureau
  (`coach start`).
- **Claude** : instrumentation dans `ClaudeCliProvider.complete` et
  `AnthropicApiProvider.complete`. Une entrée « requête » écrite **avant**
  l'appel (horodatage, taille du prompt, modèle, textes), puis une entrée
  « réponse » ou « erreur ». Sur délai dépassé, on consigne la sortie
  partielle que `TimeoutExpired` peut porter (`stdout`/`stderr`). Les
  arguments CLI sont consignés (le prompt système y figure). Un identifiant
  d'appel relie requête et réponse ; la nouvelle tentative de `ask_structured`
  apparaît comme un second appel.
- **Garmin** : instrumentation dans `GarminClient._call` (point de passage de
  toutes les lectures/écritures) et dans `start_login`/`finish_login`/
  `from_tokens` pour l'issue seulement (jamais les identifiants ni le code MFA).
- **Masquage** : filtre appliqué à tout ce qui est écrit — clés connues
  (`password`, `token`, `api_key`, `authorization`, `cookie`, `oauth*`…)
  remplacées par `***`, et valeur littérale de la clé API / token Turso des
  réglages remplacée si elle apparaît dans un texte.

## Mes choix (à vérifier)

- Réponses Garmin tronquées à 20 000 caractères par entrée (certaines
  activités font plusieurs centaines de Ko) ; réponses Claude jamais tronquées.
- Format lisible ligne par ligne : en-tête `horodatage NIVEAU [id] événement`
  puis le contenu JSON indenté.
- Ouverture du dossier : route desktop existante style `os.startfile` sous
  Windows ; le bouton n'apparaît qu'en mode bureau.

## Laissé au constructeur

Le nom exact de la route API, la mise en page de la carte, la liste précise
des clés masquées au-delà de celles ci-dessus.
