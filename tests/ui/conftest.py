"""Fixtures Qt. Qt tourne sans écran (plugin « offscreen »), y compris en CI."""

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path

# Doit être défini avant la création de la QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from budget.db.base import create_db_engine, make_session_factory, unit_of_work  # noqa: E402
from budget.db.migrate import upgrade_to_head  # noqa: E402
from budget.services.lookups import ensure_default_payment_methods  # noqa: E402

TODAY = dt.date(2026, 3, 15)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker]:  # type: ignore[type-arg]
    """Base de données de fichier, migrée comme au vrai démarrage."""
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)
    session_factory = make_session_factory(engine)
    with unit_of_work(session_factory) as session:
        ensure_default_payment_methods(session)
    yield session_factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _stop_watchdogs() -> Iterator[None]:
    yield
    from tests.ui.helpers import stop_watchdogs

    stop_watchdogs()
