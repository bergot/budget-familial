"""Point d'entrée : `python -m budget` ou la commande `budget-familial`."""

import argparse
import sys
from pathlib import Path

from budget.ui.app import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="budget-familial", description="Budget familial")
    parser.add_argument(
        "--base",
        type=Path,
        metavar="FICHIER",
        help="fichier SQLite à utiliser (par défaut : le dossier de données de l'utilisateur)",
    )
    args = parser.parse_args()
    sys.exit(run(args.base))


if __name__ == "__main__":
    main()
