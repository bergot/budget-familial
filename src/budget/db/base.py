"""Base déclarative, moteur SQLite et sessions."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


class Base(DeclarativeBase):
    """Classe mère de tous les modèles (tables)."""


def _enable_foreign_keys(dbapi_connection: SQLiteConnection, _record: ConnectionPoolEntry) -> None:
    # SQLite ignore les clés étrangères tant qu'on ne l'a pas demandé, connexion par connexion.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(database: Path | None = None) -> Engine:
    """Crée le moteur SQLite.

    `database=None` donne une base en mémoire (utile pour les tests) ; sinon
    c'est le chemin du fichier SQLite.
    """
    url = "sqlite://" if database is None else f"sqlite:///{database}"
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def init_schema(engine: Engine) -> None:
    """Crée les tables qui n'existent pas encore.

    Les modèles doivent être importés pour être connus de `Base.metadata`.
    """
    from budget.db import models  # noqa: F401  (l'import enregistre les tables)

    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Fabrique de sessions liée au moteur."""
    return sessionmaker(engine)


@contextmanager
def unit_of_work(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Ouvre une session et une transaction : validée à la sortie, annulée sur exception.

    Usage :
        with unit_of_work(factory) as session:
            accounts.create_account(session, "SG")
    """
    with factory() as session, session.begin():
        yield session
