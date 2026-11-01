"""Point d'entrée de l'exécutable PyInstaller."""

import sys

from coach.desktop.launcher import main

# main() ne lit pas sys.argv lui-même : on lui transmet les arguments (--smoke).
raise SystemExit(main(sys.argv[1:]))
