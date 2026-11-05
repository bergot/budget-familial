"""Emplacements des fichiers de l'application."""

from pathlib import Path

from platformdirs import user_data_path

APP_NAME = "budget-familial"


def data_dir() -> Path:
    """Dossier des données utilisateur, créé au besoin.

    Linux : ~/.local/share/budget-familial
    Windows : C:\\Users\\<nom>\\AppData\\Local\\budget-familial
    """
    return user_data_path(APP_NAME, ensure_exists=True)


def database_file() -> Path:
    """Chemin du fichier SQLite."""
    return data_dir() / "budget.sqlite"
