# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller de CoachCloclo (mode dossier, sans console).

À lancer depuis la racine du dépôt :
    uv run --group desktop pyinstaller --noconfirm packaging/windows/coachcloclo.spec
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# Les chemins relatifs d'un .spec sont résolus depuis son dossier : on part de la racine
RACINE = os.path.abspath(os.path.join(SPECPATH, "..", ".."))


def racine(*parts):
    return os.path.join(RACINE, *parts)


datas = (
    [
        # Front Svelte construit (npm run build) ; WEB_DIST = coach/web_dist
        (racine("coach", "web_dist"), "coach/web_dist"),
        # Icône de la zone de notification, lue dans sys._MEIPASS
        (racine("packaging", "windows", "coachcloclo.ico"), "."),
    ]
    # app_version() lit importlib.metadata.version("coachcloclo")
    + copy_metadata("coachcloclo")
    # Magasin de certificats pour les appels HTTPS (Garmin, GitHub, Anthropic)
    + collect_data_files("certifi")
)

hiddenimports = (
    # uvicorn choisit ses boucles, protocoles et lifespans par import dynamique
    collect_submodules("uvicorn")
    # Moteur Windows de pystray, choisi à l'exécution
    + ["pystray._win32"]
    # garminconnect importe ses sous-modules (auth, workout...) à la demande
    + collect_submodules("garminconnect")
    # Stockage cloud : pilote libsql (extension compilée) et dialecte SQLAlchemy maison,
    # enregistré par import au moment de créer le moteur distant
    + ["libsql", "coach.storage.libsql_dialect"]
)

a = Analysis(
    [racine("packaging", "windows", "entry.py")],
    pathex=[RACINE],
    datas=datas,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CoachCloclo",
    console=False,
    icon=racine("packaging", "windows", "coachcloclo.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="CoachCloclo")
