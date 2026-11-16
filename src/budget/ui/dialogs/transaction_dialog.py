"""Formulaire de saisie d'une opération (dépense ou recette)."""

import datetime as dt
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from budget.services.choices import Choices
from budget.services.transactions import RegisterLine
from budget.ui.dialogs.common import (
    date_value,
    make_amount_edit,
    make_button_box,
    make_choice_combo,
    make_date_edit,
    positive_amount,
    show_error,
)


@dataclass(frozen=True, slots=True)
class TransactionInput:
    """Ce que l'utilisateur a saisi. Le tiers est un nom : il sera créé s'il est nouveau."""

    account_id: int
    date: dt.date
    amount_cents: int  # signé : < 0 dépense, > 0 recette
    payee_name: str
    category_id: int | None
    payment_method_id: int | None
    notes: str


class TransactionDialog(QDialog):
    def __init__(
        self,
        choices: Choices,
        *,
        account_id: int | None = None,
        initial: RegisterLine | None = None,
        today: dt.date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modifier l'opération" if initial else "Nouvelle opération")
        self.setMinimumWidth(460)
        self._input: TransactionInput | None = None

        current_account = initial.account_id if initial else account_id
        self._account = make_choice_combo(choices.accounts, current_id=current_account)
        self._date = make_date_edit(initial.date if initial else (today or dt.date.today()))

        self._payee = QComboBox()
        self._payee.setEditable(True)
        self._payee.addItems(choices.payee_names)
        self._payee.setCurrentText(initial.payee_name if initial else "")
        self._payee.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = self._payee.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        self._expense = QRadioButton("Dépense")
        self._income = QRadioButton("Recette")
        is_income = initial is not None and initial.amount_cents > 0
        self._income.setChecked(is_income)
        self._expense.setChecked(not is_income)
        kind = QHBoxLayout()
        kind.addWidget(self._expense)
        kind.addWidget(self._income)
        kind.addStretch()

        self._amount = make_amount_edit(abs(initial.amount_cents) if initial else None)
        self._category = make_choice_combo(
            choices.categories,
            none_label="(aucune)",
            current_id=initial.category_id if initial else None,
        )
        self._method = make_choice_combo(
            choices.payment_methods,
            none_label="(aucun)",
            current_id=initial.payment_method_id if initial else None,
        )
        self._notes = QLineEdit(initial.notes if initial else "")

        form = QFormLayout()
        form.addRow("Compte :", self._account)
        form.addRow("Date :", self._date)
        form.addRow("Tiers :", self._payee)
        form.addRow("Sens :", kind)
        form.addRow("Montant (€) :", self._amount)
        form.addRow("Catégorie :", self._category)
        form.addRow("Moyen de paiement :", self._method)
        form.addRow("Notes :", self._notes)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        # Pour une nouvelle opération, on commence la saisie par le tiers.
        (self._payee if initial is None else self._amount).setFocus()

    def accept(self) -> None:
        account_id = self._account.currentData()
        if account_id is None:
            show_error(self, "Aucun compte ouvert : créez d'abord un compte.")
            return
        try:
            cents = positive_amount(self._amount)
        except ValueError as error:
            show_error(self, error)
            return
        self._input = TransactionInput(
            account_id=account_id,
            date=date_value(self._date),
            amount_cents=-cents if self._expense.isChecked() else cents,
            payee_name=self._payee.currentText().strip(),
            category_id=self._category.currentData(),
            payment_method_id=self._method.currentData(),
            notes=self._notes.text().strip(),
        )
        super().accept()

    def values(self) -> TransactionInput:
        assert self._input is not None, "values() n'est valable qu'après validation du dialogue"
        return self._input
