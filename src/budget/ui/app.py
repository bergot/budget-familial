"""Création de l'application Qt et boucle d'événements."""

import sys

from PySide6.QtWidgets import QApplication

from budget.ui.main_window import MainWindow


def run() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()  # bloque jusqu'à la fermeture de la fenêtre
