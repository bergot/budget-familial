"""Aide pour tester l'interface : répondre aux boîtes de dialogue modales.

Quand le code appelle `dialog.exec()`, le test est bloqué dans la boucle d'événements du
dialogue. On programme donc, avant l'action, une réponse (`answer_next_dialog`) qui s'exécute
dès que le dialogue est affiché : elle remplit les champs, puis valide ou annule.

Deux pièges évités ici :
- une exception levée dans cette réponse est interceptée par Qt, qui se contente de l'afficher :
  le test réussirait à tort. On la consigne donc, et la fixture de `conftest.py` fait échouer
  le test à la fin ;
- une réponse programmée mais jamais jouée (l'action n'a ouvert aucun dialogue) est signalée
  de la même façon, au lieu de se déclencher par surprise pendant un autre test.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QMessageBox, QWidget

_timers: list[QTimer] = []
_answers: list[_Answer] = []
_problems: list[str] = []


@dataclass
class _Answer:
    description: str
    played: bool = False


def front_dialog() -> QDialog | None:
    """La boîte modale au premier plan : la plus « profonde » quand plusieurs sont ouvertes.

    Avec des dialogues imbriqués (l'écran des échéances et son formulaire, par exemple), les deux
    sont modaux et visibles. `topLevelWidgets()` les liste dans un ordre quelconque : on garde
    celle qui n'est le parent d'aucune autre, c'est-à-dire celle ouverte en dernier.
    """
    candidates = [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, QDialog) and widget.isVisible() and widget.isModal()
    ]
    innermost = [
        dialog
        for dialog in candidates
        if not any(other is not dialog and _is_ancestor(dialog, other) for other in candidates)
    ]
    return innermost[0] if innermost else None


def _is_ancestor(ancestor: QWidget, widget: QWidget) -> bool:
    """`ancestor` est-il un parent (direct ou non) de `widget` ?

    On remonte la chaîne des parents nous-mêmes : `QWidget.isAncestorOf` s'arrête aux fenêtres,
    et un `QDialog` en est une, même quand il a un parent.
    """
    parent = widget.parentWidget()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.parentWidget()
    return False


def _start_timer(delay_ms: int, callback: Callable[[], object]) -> None:
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(delay_ms)
    _timers.append(timer)  # gardé en vie, et arrêtable en fin de test


def answer_next_dialog(fill: Callable[[QDialog], None]) -> None:
    """Appelle `fill(dialog)` sur la prochaine boîte modale affichée, puis la ferme si besoin."""
    answer = _Answer(description=getattr(fill, "__qualname__", repr(fill)))
    _answers.append(answer)

    def handler() -> None:
        answer.played = True
        dialog = front_dialog()
        if dialog is None:
            _problems.append(f"{answer.description} : aucune boîte modale n'était affichée")
            return
        try:
            fill(dialog)
        except BaseException as error:  # noqa: BLE001 - on consigne tout, y compris AssertionError
            _problems.append(f"{answer.description} : {type(error).__name__}: {error}")
        finally:
            if dialog.isVisible():
                dialog.reject()

    _start_timer(0, handler)

    # Filet de sécurité : si rien ne répond, on ferme plutôt que de bloquer toute la suite.
    def watchdog() -> None:
        dialog = front_dialog()
        if dialog is not None:
            _problems.append(f"{answer.description} : dialogue resté ouvert (blocage évité)")
            dialog.reject()

    _start_timer(4000, watchdog)


def click_button(box: QMessageBox, text: str) -> None:
    buttons: list[QAbstractButton] = [b for b in box.buttons() if b.text() == text]
    assert buttons, f"bouton {text!r} introuvable parmi {[b.text() for b in box.buttons()]}"
    buttons[0].click()


def finish_test() -> list[str]:
    """Fin de test : arrête les minuteries, et retourne les problèmes consignés."""
    for timer in _timers:
        timer.stop()
    _timers.clear()
    for answer in _answers:
        if not answer.played:
            _problems.append(f"{answer.description} : réponse programmée mais jamais jouée")
    _answers.clear()
    problems = list(_problems)
    _problems.clear()
    return problems
