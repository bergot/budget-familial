"""Aide pour tester l'interface : répondre aux boîtes de dialogue modales.

Quand le code appelle `dialog.exec()`, le test est bloqué dans la boucle d'événements du
dialogue. On programme donc, avant l'action, une réponse (`answer_next_dialog`) qui s'exécute
dès que le dialogue est affiché : elle remplit les champs, puis valide ou annule.
"""

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QMessageBox

_watchdogs: list[QTimer] = []


def front_dialog() -> QDialog | None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QDialog) and widget.isVisible() and widget.isModal():
            return widget
    return None


def answer_next_dialog(fill: Callable[[QDialog], None]) -> None:
    """Appelle `fill(dialog)` sur la prochaine boîte modale affichée, puis la ferme si besoin."""

    def handler() -> None:
        dialog = front_dialog()
        if dialog is None:
            return
        try:
            fill(dialog)
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, handler)

    # Filet de sécurité : si aucune réponse n'aboutit, on ferme tout plutôt que de bloquer.
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: (d := front_dialog()) and d.reject())
    watchdog.start(4000)
    _watchdogs.append(watchdog)


def stop_watchdogs() -> None:
    for watchdog in _watchdogs:
        watchdog.stop()
    _watchdogs.clear()


def click_button(box: QMessageBox, text: str) -> None:
    buttons: list[QAbstractButton] = [b for b in box.buttons() if b.text() == text]
    assert buttons, f"bouton {text!r} introuvable parmi {[b.text() for b in box.buttons()]}"
    buttons[0].click()
