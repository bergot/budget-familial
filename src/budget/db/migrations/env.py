"""Environnement Alembic.

Deux usages :
- par l'application, via `budget.db.migrate.upgrade_to_head`, qui fournit une connexion
  déjà ouverte (`config.attributes["connection"]`) ;
- en développement, via la commande `alembic` (voir `alembic.ini`), pour créer de
  nouvelles migrations.
"""

from alembic import context
from sqlalchemy import create_engine

from budget.db import models  # noqa: F401  (enregistre les tables dans Base.metadata)
from budget.db.base import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite sait peu modifier une table existante : le mode « batch » recrée la table.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return
    # Mode développement : l'URL vient de alembic.ini.
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "")
    with engine.connect() as connection:
        _configure_and_run(connection)
        connection.commit()


run_migrations_online()
