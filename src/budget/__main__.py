"""Point d'entrée : `python -m budget` ou la commande `budget-familial`."""

import sys

from budget.ui.app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
