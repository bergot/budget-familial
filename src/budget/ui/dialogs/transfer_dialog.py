"""Formulaire de saisie d'un virement entre deux comptes."""

import datetime as dt

from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QVBoxLayout, QWidget

from budget.services.choices import Choices
from budget.services.transactions import RegisterLine, TransferData
from budget.ui.dialogs.common import (
    date_value,
    make_amount_edit,
    make_button_box,
    make_choice_combo,
    make_date_edit,
    positive_amount,
    show_error,
)


class TransferDialog(QDialog):
    def __init__(
        self,
        choices: Choices,
        *,
        from_account_id: int | None = None,
        initial: RegisterLine | None = None,
        today: dt.date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modifier le virement" if initial else "Nouveau virement")
        self.setMinimumWidth(420)
        self._data: TransferData | None = None

        source_id, target_id = from_account_id, None
        if initial is not None:
            # Le virement est affiché depuis l'une de ses deux moitiés : le signe indique le sens.
            outgoing = initial.amount_cents < 0
            source_id = initial.account_id if outgoing else initial.transfer_account_id
            target_id = initial.transfer_account_id if outgoing else initial.account_id

        self._from = make_choice_combo(choices.accounts, current_id=source_id)
        self._to = make_choice_combo(choices.accounts, current_id=target_id)
        if initial is None and self._to.count() > 1 and self._to.currentIndex() == 0:
            # Évite de proposer d'emblée le même compte des deux côtés.
            self._to.setCurrentIndex(1 if self._from.currentIndex() == 0 else 0)

        self._date = make_date_edit(initial.date if initial else (today or dt.date.today()))
        self._amount = make_amount_edit(abs(initial.amount_cents) if initial else None)
        self._method = make_choice_combo(
            choices.payment_methods,
            none_label="(aucun)",
            current_id=initial.payment_method_id if initial else None,
        )
        self._notes = QLineEdit(initial.notes if initial else "")

        form = QFormLayout()
        form.addRow("Depuis le compte :", self._from)
        form.addRow("Vers le compte :", self._to)
        form.addRow("Date :", self._date)
        form.addRow("Montant (€) :", self._amount)
        form.addRow("Moyen de paiement :", self._method)
        form.addRow("Notes :", self._notes)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._amount.setFocus()

    def accept(self) -> None:
        source, target = self._from.currentData(), self._to.currentData()
        if source is None or target is None:
            show_error(self, "Un virement nécessite deux comptes ouverts.")
            return
        if source == target:
            show_error(self, "Choisissez deux comptes différents.")
            return
        try:
            cents = positive_amount(self._amount)
        except ValueError as error:
            show_error(self, error)
            return
        self._data = TransferData(
            from_account_id=source,
            to_account_id=target,
            date=date_value(self._date),
            amount_cents=cents,
            payment_method_id=self._method.currentData(),
            notes=self._notes.text().strip(),
        )
        super().accept()

    def values(self) -> TransferData:
        assert self._data is not None, "values() n'est valable qu'après validation du dialogue"
        return self._data
