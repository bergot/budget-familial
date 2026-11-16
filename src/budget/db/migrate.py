"""Application des migrations de schéma au démarrage de l'application."""

import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class MigrationError(Exception):
    """La base n'est pas dans un état cohérent après une migration."""


def _config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _database_file(engine: Engine) -> Path | None:
    name = engine.url.database
    return Path(name) if name and name != ":memory:" else None


def _backup_before_upgrade(engine: Engine, config: Config, revision: str) -> Path | None:
    """Copie le fichier de base à côté de lui avant d'appliquer des migrations en attente.

    SQLite n'annule pas proprement une migration qui échoue en cours de route : une copie
    est la seule vraie protection. Retourne le chemin de la copie, ou None si inutile
    (base neuve, en mémoire, ou déjà à jour).
    """
    path = _database_file(engine)
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None

    script = ScriptDirectory.from_config(config)
    target = script.get_current_head() if revision == "head" else script.get_revision(revision)
    target_id = target if isinstance(target, str) else (target.revision if target else None)

    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current is None or current == target_id:
        return None  # base neuve (rien à protéger) ou déjà à jour

    backup = path.with_name(f"{path.name}.avant-{target_id}.bak")
    shutil.copy2(path, backup)
    return backup


def upgrade_to_head(engine: Engine, revision: str = "head") -> None:
    """Amène la base à la dernière version du schéma.

    `revision` permet de s'arrêter à une version précise (utile aux tests de migration).

    Base neuve : crée toutes les tables. Base existante : sauvegarde le fichier, puis
    n'applique que les migrations manquantes, sans toucher aux données.
    """
    config = _config()
    _backup_before_upgrade(engine, config, revision)

    with engine.connect() as connection:
        # Pour modifier une table, SQLite oblige Alembic à la recréer (supprimer puis
        # renommer). Avec les clés étrangères actives, la suppression déclenche leurs
        # actions (par exemple « ON DELETE SET NULL ») et fait perdre des liens en silence.
        # On les désactive donc le temps de la migration, puis on vérifie l'intégrité.
        # (Ce PRAGMA n'a d'effet qu'en dehors d'une transaction : c'est le cas ici.)
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
            connection.commit()
            problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    if problems:
        raise MigrationError(f"Clés étrangères invalides après migration : {problems}")
