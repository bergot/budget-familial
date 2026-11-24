"""Création de l'application Qt, ouverture de la base et boucle d'événements."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from budget import __version__
from budget.paths import database_file, settings_file
from budget.settings import SettingsStore
from budget.startup import open_database
from budget.ui.i18n import install_french
from budget.ui.icons import load_app_icon
from budget.ui.main_window import MainWindow

EXIT_MISSING_ICON = 3


def _finish_smoke_test(app: QApplication, icon: QIcon) -> int:
    """Fin du test de fumée : l'application a démarré, on vérifie l'icône puis on quitte."""
    if icon.isNull():
        print(
            "Test de fumée : l'icône est introuvable (fichiers de données absents ?)",
            file=sys.stderr,
        )
        return EXIT_MISSING_ICON
    QTimer.singleShot(300, app.quit)  # laisse à la fenêtre le temps de s'afficher vraiment
    return int(app.exec())


def run(database: Path | None = None, *, smoke_test: bool = False) -> int:
    """Lance l'application. `database` : fichier SQLite (par défaut, l'emplacement standard).

    `smoke_test` démarre, ouvre la base et la fenêtre, vérifie l'icône puis quitte tout de
    suite, sans rien écrire dans les réglages de l'utilisateur : la CI s'en sert pour
    contrôler qu'un exécutable construit fonctionne vraiment.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("Budget familial")
    app.setApplicationVersion(__version__)
    icon = load_app_icon()
    app.setWindowIcon(icon)
    install_french(app)

    store = SettingsStore() if smoke_test else SettingsStore.load(settings_file())
    path = database or database_file()
    factory, report = open_database(path, settings=store.settings)

    window = MainWindow(factory, store=store, database=path)
    window.show()
    if smoke_test:
        return _finish_smoke_test(app, icon)
    window.report_startup(report)
    return int(app.exec())  # bloque jusqu'à la fermeture de la fenêtre
