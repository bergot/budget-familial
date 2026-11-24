"""Emplacements des fichiers de l'application."""

from pathlib import Path

from platformdirs import user_config_path, user_data_path

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


def config_dir() -> Path:
    """Dossier des réglages de l'utilisateur, créé au besoin.

    Linux : ~/.config/budget-familial
    Windows : C:\\Users\\<nom>\\AppData\\Local\\budget-familial
    """
    return user_config_path(APP_NAME, ensure_exists=True)


def settings_file() -> Path:
    """Chemin du fichier de réglages."""
    return config_dir() / "settings.json"
