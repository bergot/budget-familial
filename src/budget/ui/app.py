"""Création de l'application Qt, ouverture de la base et boucle d'événements."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from budget.db.base import create_db_engine, make_session_factory, unit_of_work
from budget.db.migrate import upgrade_to_head
from budget.paths import database_file
from budget.services.lookups import ensure_default_payment_methods
from budget.ui.i18n import install_french
from budget.ui.main_window import MainWindow


def run(database: Path | None = None) -> int:
    """Lance l'application. `database` : fichier SQLite (par défaut, l'emplacement standard)."""
    app = QApplication(sys.argv)
    app.setApplicationName("Budget familial")
    install_french(app)

    engine = create_db_engine(database or database_file())
    upgrade_to_head(engine)  # crée la base au premier lancement, la met à jour ensuite
    factory = make_session_factory(engine)
    with unit_of_work(factory) as session:
        ensure_default_payment_methods(session)

    window = MainWindow(factory)
    window.show()
    return app.exec()  # bloque jusqu'à la fermeture de la fenêtre
