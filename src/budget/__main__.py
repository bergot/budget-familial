"""Point d'entrée : `python -m budget` ou la commande `budget-familial`."""

import argparse
import sys
from pathlib import Path

from budget import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="budget-familial", description="Budget familial")
    parser.add_argument(
        "--base",
        type=Path,
        metavar="FICHIER",
        help="fichier SQLite à utiliser (par défaut : le dossier de données de l'utilisateur)",
    )
    parser.add_argument("--version", action="version", version=f"Budget familial {__version__}")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="démarre, vérifie que tout fonctionne puis quitte (utilisé par la CI)",
    )
    args = parser.parse_args()

    from budget.ui.app import run  # import tardif : `--help` et `--version` restent instantanés

    sys.exit(run(args.base, smoke_test=args.smoke_test))


if __name__ == "__main__":
    main()
