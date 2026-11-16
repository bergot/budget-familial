"""Application des migrations de schéma au démarrage de l'application."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def upgrade_to_head(engine: Engine) -> None:
    """Amène la base à la dernière version du schéma.

    Base neuve : crée toutes les tables. Base existante : n'applique que les migrations
    manquantes, sans toucher aux données.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
