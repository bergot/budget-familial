import os

# Qt sans écran (CI, serveur) : doit être défini avant l'import de PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from budget.ui.main_window import MainWindow  # noqa: E402


def test_main_window_opens() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()

    assert window.windowTitle() == "Budget familial"
    assert window.isVisible()

    window.close()
    del app
