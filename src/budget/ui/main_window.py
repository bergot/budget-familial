"""Fenêtre principale (squelette de l'étape 0)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow

from budget import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Budget familial")
        self.resize(900, 600)

        label = QLabel(f"Budget familial, version {__version__}")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(label)
