"""Textes du guide de course : conseils par phase, principe de nutrition, préparation et matin. Textes seulement."""

# Conseil de chaque phase, selon (trail, tranche de distance, phase).
# Route : allure et placement. Trail : effort, zone FC, montées et descentes.
PHASE_ADVICE: dict[tuple[bool, str, str], str] = {
    # Route, 5–10 km
    (False, "court", "Départ"): (
        "Ne te laisse pas emporter par le peloton. Cale-toi sur ton allure dès les premières centaines de mètres. "
        "Quelques secondes de trop ici se paient cher à la fin."
    ),
    (False, "court", "Cœur de course"): (
        "Tiens ton allure, kilomètre après kilomètre. C'est dur mais contrôlé : respiration rapide, foulée stable. "
        "Accroche-toi à un coureur de ton niveau."
    ),
    (False, "court", "Final"): (
        "Accélère progressivement, sans attendre la ligne. Relâche les épaules et pousse sur les bras. "
        "Garde le sprint pour les 200 derniers mètres."
    ),
    # Route, semi
    (False, "semi", "Départ"): (
        "Pars un peu moins vite que ton allure moyenne. Laisse le peloton s'étirer et trouve ta place. "
        "Tu ne gagnes rien à aller vite ici, tu peux tout perdre."
    ),
    (False, "semi", "Installation"): (
        "Cale-toi sur ton allure et n'en bouge plus. Respiration régulière, foulée souple. "
        "Si tu es en avance sur tes passages, ne creuse pas l'écart."
    ),
    (False, "semi", "Cœur de course"): (
        "C'est ici que la course se joue. L'effort monte alors que l'allure reste la même : c'est normal. "
        "Pense à ta posture et prends tes gels à l'heure prévue."
    ),
    (False, "semi", "Final"): (
        "Si tu te sens bien, accélère un peu. Sinon, tiens simplement ton allure. "
        "Va chercher les coureurs devant toi, un par un."
    ),
    # Route, marathon
    (False, "marathon", "Départ"): (
        "Pars moins vite que ton allure cible, même si ça paraît trop facile. "
        "Une minute gagnée ici peut en coûter dix en fin de course. Reste dans ta bulle."
    ),
    (False, "marathon", "Installation"): (
        "Trouve ton rythme et ne le quitte plus. Tu dois pouvoir dire quelques mots. "
        "Commence à boire et à manger tôt, avant d'en ressentir le besoin."
    ),
    (False, "marathon", "Cœur de course"): (
        "Économise-toi : pas d'à-coups, abrite-toi du vent derrière un groupe. "
        "Prends tes gels à l'heure, même sans faim. La vraie course commence vers le 30e km."
    ),
    (False, "marathon", "Final"): (
        "Les jambes deviennent lourdes : c'est le moment de tenir. Raccourcis la foulée et garde une cadence vive. "
        "S'il te reste du jus dans les derniers kilomètres, lâche-toi."
    ),
    # Route, au-delà du marathon
    (False, "ultra", "Départ"): (
        "Pars très lentement, tu as toute la journée. Si l'allure te semble ridicule, c'est la bonne. "
        "Commence à boire et à manger tôt."
    ),
    (False, "ultra", "Installation"): (
        "Installe ta routine : boire souvent, manger à heures fixes. "
        "Marche quelques pas aux ravitos si ça t'aide à manger. L'effort doit rester facile."
    ),
    (False, "ultra", "Cœur de course"): (
        "Les coups de moins bien arrivent et repartent. Quand ça va mal, ralentis, mange et bois : souvent, ça revient. "
        "Avance d'un ravito à l'autre, sans penser à l'arrivée."
    ),
    (False, "ultra", "Final"): (
        "Reste régulier, foulée courte et tête dans la course. "
        "Continue à manger et à boire jusqu'au bout : une fringale peut encore tout gâcher."
    ),
    # Trail, court
    (True, "court", "Départ"): (
        "Ne suis pas le peloton dans la première montée. Reste sous ta zone FC le temps de te chauffer. "
        "Un bouchon sur le premier sentier ne vaut pas un sprint pour l'éviter."
    ),
    (True, "court", "Cœur de course"): (
        "Pilote à la FC, pas à l'allure. En montée, raccourcis le pas et marche dès que c'est trop raide pour courir "
        "sans te mettre dans le rouge. En descente, regarde loin devant et relâche."
    ),
    (True, "court", "Final"): (
        "Lâche ce qu'il te reste sur les parties roulantes. "
        "Garde de la lucidité pour la dernière descente : la fatigue fait chuter."
    ),
    # Trail, 12–25 km
    (True, "semi", "Départ"): (
        "Laisse partir les autres. Marche dans la première côte si ta FC s'emballe. "
        "Le départ doit te sembler trop facile."
    ),
    (True, "semi", "Installation"): (
        "Trouve ton rythme dans ta zone FC. Marche tôt dans les montées raides, avant d'être dans le rouge. "
        "Commence à boire et à manger avant d'avoir faim ou soif."
    ),
    (True, "semi", "Cœur de course"): (
        "Gère l'effort, pas le chrono. En montée raide, marche vite, mains sur les cuisses. "
        "Mange à heures fixes, même sans faim."
    ),
    (True, "semi", "Final"): (
        "Garde du jus pour les descentes de fin : c'est là que les jambes lâchent. "
        "Reste concentré sur tes appuis. S'il te reste de l'énergie, relance sur le plat."
    ),
    # Trail, 25–45 km
    (True, "marathon", "Départ"): (
        "Ne suis pas le peloton : ceux qui partent vite marcheront plus tard. "
        "Reste sous ta zone FC et marche dès la première vraie montée."
    ),
    (True, "marathon", "Installation"): (
        "Installe ta routine : quelques gorgées souvent, de quoi manger toutes les 30 à 40 minutes. "
        "Marche tôt dans les montées, cours souple sur le plat. Au ravito, remplis tes flasques avant de manger."
    ),
    (True, "marathon", "Cœur de course"): (
        "Mange avant d'avoir faim, bois avant d'avoir soif. Garde ta FC dans la zone, même si d'autres te doublent. "
        "Ménage tes cuisses dans les descentes : petits pas, appuis légers."
    ),
    (True, "marathon", "Final"): (
        "Tu as gardé du jus : c'est le moment de t'en servir. Relance dès que le terrain le permet. "
        "Reste prudent en descente, les chutes arrivent avec la fatigue."
    ),
    # Trail, au-delà de 45 km
    (True, "ultra", "Départ"): (
        "Pars lentement, très lentement. La course commence vraiment après plusieurs heures. "
        "Marche les montées dès le début, même celles qui semblent faciles."
    ),
    (True, "ultra", "Installation"): (
        "Mange et bois dès la première heure, à heures fixes. Alterne sucré et salé. "
        "Sois efficace aux ravitos : remplis, mange, repars."
    ),
    (True, "ultra", "Cœur de course"): (
        "Il y aura des passages à vide. Quand ça va mal, ralentis, mange et bois : la plupart passent. "
        "Avance d'un ravito à l'autre, sans penser à l'arrivée."
    ),
    (True, "ultra", "Final"): (
        "Garde du jus pour les dernières descentes : les cuisses sont à bout. "
        "Reste lucide sur le balisage et tes appuis. Continue à manger jusqu'au bout."
    ),
}

# Ajouté au conseil d'une phase route qui contient une montée notable.
ROAD_CLIMB_HINT = "Dans les côtes, garde l'effort, pas l'allure : tu reprendras le temps sur le plat et en descente."

# Principe de nutrition selon (trail, palier de durée prévue).
PRINCIPLE: dict[tuple[bool, str], str] = {
    (False, "court"): (
        "Moins de 1 h 15 de course : tes réserves suffisent, pas besoin de glucides pendant l'effort. "
        "L'eau est facultative : quelques gorgées au ravito si tu as soif."
    ),
    (False, "moyen"): (
        "Entre 1 h 15 et 2 h 30, 30 à 60 g de glucides par heure t'aident à tenir l'allure jusqu'au bout. "
        "Prends tes gels à l'heure prévue, avec quelques gorgées d'eau. Bois à ta soif aux ravitos."
    ),
    (False, "long"): (
        "Au-delà de 2 h 30, tes réserves ne suffisent plus : vise 60 à 90 g de glucides par heure. "
        "Prends tes gels à l'heure, même sans faim, toujours avec un peu d'eau. "
        "Bois à chaque ravito, sans te forcer au-delà de ta soif. N'utilise que des gels testés à l'entraînement."
    ),
    (True, "court"): (
        "Moins de 1 h 15 d'effort : pas besoin de manger. "
        "Emporte quand même un peu d'eau, surtout s'il fait chaud, et un gel de secours."
    ),
    (True, "moyen"): (
        "Entre 1 h 15 et 2 h 30, vise 30 à 60 g de glucides par heure. Commence tôt, avant d'avoir faim : "
        "les montées en marchant sont le bon moment pour manger. Bois quelques gorgées souvent. "
        "Le tableau par tronçon dit quoi emporter."
    ),
    (True, "long"): (
        "Au-delà de 2 h 30, la nutrition décide de ta course : vise 60 à 90 g de glucides par heure. "
        "Mange dès la première heure, peu à la fois et souvent. Alterne sucré et salé, et bois à ta soif. "
        "Le tableau par tronçon dit quoi emporter entre deux ravitos."
    ),
}

# Matin de course : libellés des étapes ; l'échauffement dépend de la tranche de distance.
MORNING_BREAKFAST = "Petit-déjeuner : un repas connu, riche en glucides, pauvre en fibres et en graisses"
MORNING_ARRIVAL = "Arrivée sur place : toilettes, dépôt du sac, dernier coup d'œil au départ"
MORNING_WARMUP = "Échauffement : {}"
MORNING_START = "Départ"
WARMUP: dict[str, str] = {
    "court": "15–20 min de footing + 3 accélérations",
    "semi": "10 min de footing",
    "marathon": "5 min de mobilité",
    "ultra": "5 min de mobilité",
}

# Préparation : blocs communs, puis ajouts par tranche de distance et par type.
_WEEK_COMMON = [
    "Ne change rien : mêmes chaussures, mêmes repas, mêmes gels qu'à l'entraînement.",
    "Dors bien toute la semaine. La nuit de l'avant-veille compte plus que la dernière.",
]
_WEEK_TAPER = {
    "court": "Allège l'entraînement : une ou deux séances courtes avec quelques accélérations à allure course.",
    "semi": "Réduis le volume d'environ un tiers. Garde une courte séance à allure semi en début de semaine.",
    "marathon": (
        "Tu es en affûtage : volume réduit, quelques rappels à allure marathon. "
        "La forme est là : tu ne peux plus la gagner, seulement la perdre."
    ),
    "ultra": (
        "Tu es en affûtage : sorties courtes et faciles. "
        "La forme est là : tu ne peux plus la gagner, seulement la perdre."
    ),
}
_WEEK_CARBS = (
    "Les 2 derniers jours, mange plus de glucides à chaque repas : pâtes, riz, pain, pommes de terre. "
    "Réduis les fibres et les graisses pour garder le ventre léger."
)
_WEEK_TRAIL = [
    "Regarde le profil : repère les grandes montées, les longues descentes et les ravitos.",
    "Vérifie le matériel obligatoire et fais une sortie avec ton sac chargé.",
    "Consulte la météo du parcours, en altitude aussi, et adapte tes affaires.",
]
_WEEK_ULTRA_TRAIL = "Prépare ta frontale et des piles de rechange si tu cours de nuit."

_EVE_COMMON = [
    "Prépare ton sac : dossard, épingles, tenue, chaussures, montre chargée.",
    "Repère l'accès au départ : trajet, parking ou transports, heure à laquelle partir.",
    "Dîner habituel, riche en glucides, pas trop tard. Évite l'alcool et les plats nouveaux.",
    "Couche-toi à l'heure habituelle. Si tu dors mal, ce n'est pas grave.",
]
_EVE_RUN = {
    "court": "Fais un footing très court avec 2 ou 3 accélérations, ou repose-toi.",
    "semi": "Fais un footing très court avec 2 ou 3 accélérations, ou repose-toi.",
    "marathon": "Repos, ou 15 à 20 min de footing très facile.",
    "ultra": "Repos, ou 15 à 20 min de footing très facile.",
}
_EVE_ROAD_LONG = "Prépare tes gels, comptés pour toute la course, et de quoi les porter."
_EVE_TRAIL = (
    "Prépare ton sac de course : matériel obligatoire, flasques, nourriture, coupe-vent. Charge montre et téléphone."
)

_MORNING_COMMON = [
    "Rien de nouveau aujourd'hui : ni chaussures, ni tenue, ni gels.",
    "Bois quelques gorgées d'eau jusqu'à une heure avant le départ, puis passe aux toilettes.",
]
_MORNING_COLD = "S'il fait froid, garde un vieux haut à jeter dans le sas de départ."
_MORNING_CHAFING = "Mets de la crème anti-frottements aux endroits sensibles : pieds, aisselles, entrejambe."
_MORNING_TRAIL = "Vérifie ton sac une dernière fois : matériel obligatoire, eau, nourriture."


def _preparation(trail: bool, band: str) -> dict[str, list[str]]:
    long = band in ("marathon", "ultra")
    week = [_WEEK_TAPER[band], *_WEEK_COMMON]
    if long:
        week.append(_WEEK_CARBS)
    if trail:
        week += _WEEK_TRAIL
        if band == "ultra":
            week.append(_WEEK_ULTRA_TRAIL)
    eve = [*_EVE_COMMON, _EVE_RUN[band]]
    if trail:
        eve.append(_EVE_TRAIL)
    elif long:
        eve.append(_EVE_ROAD_LONG)
    morning = list(_MORNING_COMMON)
    if trail:
        morning.append(_MORNING_TRAIL)
    else:
        morning.append(_MORNING_COLD)
    if long:
        morning.append(_MORNING_CHAFING)
    return {"La semaine d'avant": week, "La veille": eve, "Le matin": morning}


# Préparation selon (trail, tranche de distance).
PREPARATION: dict[tuple[bool, str], dict[str, list[str]]] = {
    (trail, band): _preparation(trail, band)
    for trail in (False, True)
    for band in ("court", "semi", "marathon", "ultra")
}
