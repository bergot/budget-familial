"""Création de l'application Qt, ouverture de la base et boucle d'événements."""

import datetime as dt
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import create_db_engine, make_session_factory, unit_of_work
from budget.db.migrate import upgrade_to_head
from budget.paths import database_file
from budget.services.lookups import ensure_default_payment_methods
from budget.services.schedules import GenerationResult, generate_due_transactions
from budget.ui.i18n import install_french
from budget.ui.main_window import MainWindow


def open_database(
    database: Path | None = None, *, today: dt.date | None = None
) -> tuple[sessionmaker[Session], GenerationResult]:
    """Prépare la base au lancement : migrations, valeurs par défaut, génération des échéances.

    Retourne la fabrique de sessions et le résultat de la génération (à signaler à
    l'utilisateur). Séparée de `run` pour pouvoir être testée sans interface.
    """
    engine = create_db_engine(database or database_file())
    upgrade_to_head(engine)  # crée la base au premier lancement, la met à jour ensuite
    factory = make_session_factory(engine)
    with unit_of_work(factory) as session:
        ensure_default_payment_methods(session)
        # Crée les opérations des échéances (rattrape aussi les lancements manqués).
        generation = generate_due_transactions(session, today=today or dt.date.today())
    return factory, generation


def run(database: Path | None = None) -> int:
    """Lance l'application. `database` : fichier SQLite (par défaut, l'emplacement standard)."""
    app = QApplication(sys.argv)
    app.setApplicationName("Budget familial")
    install_french(app)

    factory, generation = open_database(database)
    window = MainWindow(factory)
    window.show()
    window.report_generation(generation)
    return app.exec()  # bloque jusqu'à la fermeture de la fenêtre
