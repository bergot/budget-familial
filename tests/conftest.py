"""Fixtures partagées : une base SQLite en mémoire, neuve pour chaque test."""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from budget.db.base import create_db_engine, init_schema
from budget.db.models import Account
from budget.services import accounts


@pytest.fixture
def engine() -> Engine:
    engine = create_db_engine()  # None => base en mémoire
    init_schema(engine)
    return engine


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
        session.rollback()  # rien n'est jamais conservé d'un test à l'autre


@pytest.fixture
def sg(session: Session) -> Account:
    """Compte Société Générale avec 1 000,00 EUR de solde initial."""
    return accounts.create_account(
        session, "SG courant", bank="Société Générale", initial_balance_cents=100_000
    )


@pytest.fixture
def bourso(session: Session) -> Account:
    """Compte Boursorama, solde initial nul."""
    return accounts.create_account(session, "Boursorama", bank="Boursorama")


@pytest.fixture
def day() -> dt.date:
    """Une date de référence fixe pour les tests."""
    return dt.date(2026, 3, 15)
