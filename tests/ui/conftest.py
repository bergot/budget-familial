"""Fixtures Qt. Qt tourne sans écran (plugin « offscreen »), y compris en CI."""

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path

# Doit être défini avant la création de la QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
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
def database(tmp_path: Path) -> Path:
    """Chemin du fichier de données de test."""
    return tmp_path / "budget.sqlite"


@pytest.fixture
def factory(database: Path) -> Iterator[sessionmaker]:  # type: ignore[type-arg]
    """Base de données de fichier, migrée comme au vrai démarrage."""
    engine = create_db_engine(database)
    upgrade_to_head(engine)
    session_factory = make_session_factory(engine)
    with unit_of_work(session_factory) as session:
        ensure_default_payment_methods(session)
    yield session_factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _ui_hygiene(qapp: QApplication) -> Iterator[None]:
    """Après chaque test : détruit les fenêtres, et fait échouer le test si une réponse a échoué.

    Sans ce nettoyage, des fenêtres survivent jusqu'à la fin du processus : PySide détruit alors
    l'application Qt avant elles et le processus plante en sortie (segfault ou corruption de
    mémoire, selon l'ordre de destruction). Tous les tests passent, mais le code de retour est
    non nul, et la CI devient rouge.
    """
    yield
    from tests.ui.helpers import finish_test

    problems = finish_test()
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    # Les `deleteLater` ne sont exécutés que par la boucle d'événements : on la sollicite.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    if problems:
        pytest.fail("Réponses de dialogue en échec :\n- " + "\n- ".join(problems), pytrace=False)
