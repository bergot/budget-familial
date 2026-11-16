"""Éléments communs aux boîtes de dialogue."""

import datetime as dt
from collections.abc import Iterable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from budget.domain.money import format_cents, parse_amount
from budget.services.choices import Choice


def make_button_box(ok_text: str = "Enregistrer") -> QDialogButtonBox:
    """Boutons « Enregistrer » / « Annuler », avec des libellés français explicites."""
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    save = box.button(QDialogButtonBox.StandardButton.Save)
    cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
    assert save is not None and cancel is not None
    save.setText(ok_text)
    cancel.setText("Annuler")
    return box


def make_date_edit(value: dt.date) -> QDateEdit:
    edit = QDateEdit(QDate(value.year, value.month, value.day))
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd/MM/yyyy")
    return edit


def date_value(edit: QDateEdit) -> dt.date:
    value = edit.date().toPython()
    assert isinstance(value, dt.date)  # toPython() est typé `object` par PySide6
    return value


def make_amount_edit(cents: int | None = None) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText("0,00")
    edit.setAlignment(Qt.AlignmentFlag.AlignRight)
    if cents is not None:
        edit.setText(format_cents(cents, symbol=False))
    return edit


def positive_amount(edit: QLineEdit, label: str = "Le montant") -> int:
    """Lit un montant strictement positif ; lève `ValueError` avec un message lisible."""
    try:
        cents = parse_amount(edit.text())
    except ValueError:
        raise ValueError(f"{label} n'est pas valide (exemple : 12,50).") from None
    if cents <= 0:
        raise ValueError(f"{label} doit être supérieur à zéro.")
    return cents


def make_choice_combo(
    choices: Iterable[Choice], *, none_label: str | None = None, current_id: int | None = None
) -> QComboBox:
    """Liste déroulante dont chaque entrée porte l'identifiant (`currentData()`).

    `none_label` ajoute une première entrée « vide » (par exemple « (aucune) ») dont
    l'identifiant est None.
    """
    combo = QComboBox()
    if none_label is not None:
        combo.addItem(none_label, None)
    for choice in choices:
        combo.addItem(choice.label, choice.id)
    if current_id is not None:
        index = combo.findData(current_id)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo


def show_error(parent: QWidget | None, error: BaseException | str, title: str = "Erreur") -> None:
    QMessageBox.warning(parent, title, str(error))


def confirm(parent: QWidget | None, title: str, text: str, action_label: str) -> bool:
    """Demande une confirmation, avec un bouton d'action nommé et un bouton « Annuler »."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    action = box.addButton(action_label, QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is action
