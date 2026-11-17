"""Formulaire de création et de modification d'une échéance."""

import datetime as dt
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from budget.domain.enums import Frequency
from budget.services.choices import Choices
from budget.services.schedules import ScheduleLine
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
class ScheduleInput:
    """Ce que l'utilisateur a saisi. Le tiers est un nom : il sera créé s'il est nouveau."""

    account_id: int
    amount_cents: int  # opération : signé ; virement : positif
    frequency: Frequency
    start_date: dt.date
    end_date: dt.date | None
    payee_name: str
    category_id: int | None
    payment_method_id: int | None
    notes: str
    transfer_account_id: int | None


class ScheduleFormDialog(QDialog):
    def __init__(
        self,
        choices: Choices,
        *,
        initial: ScheduleLine | None = None,
        today: dt.date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modifier l'échéance" if initial else "Nouvelle échéance")
        self.setMinimumWidth(500)
        self._today = today or dt.date.today()
        self._input: ScheduleInput | None = None

        is_transfer = initial.is_transfer if initial else False
        locked = initial is not None and initial.generated_count > 0

        # --- Nature : opération ou virement -------------------------------------------------
        self._kind_operation = QRadioButton("Opération")
        self._kind_transfer = QRadioButton("Virement entre comptes")
        self._kind_transfer.setChecked(is_transfer)
        self._kind_operation.setChecked(not is_transfer)
        kind = QHBoxLayout()
        kind.addWidget(self._kind_operation)
        kind.addWidget(self._kind_transfer)
        kind.addStretch()

        # --- Champs communs -----------------------------------------------------------------
        self._account = make_choice_combo(
            choices.accounts, current_id=initial.account_id if initial else None
        )
        self._account_label = QLabel()
        self._amount = make_amount_edit(abs(initial.amount_cents) if initial else None)
        self._method = make_choice_combo(
            choices.payment_methods,
            none_label="(aucun)",
            current_id=initial.payment_method_id if initial else None,
        )
        self._notes = QLineEdit(initial.notes if initial else "")

        # --- Champs d'une opération ---------------------------------------------------------
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
        is_income = initial is not None and not is_transfer and initial.amount_cents > 0
        self._income.setChecked(is_income)
        self._expense.setChecked(not is_income)
        sign = QWidget()
        sign_layout = QHBoxLayout(sign)
        sign_layout.setContentsMargins(0, 0, 0, 0)
        sign_layout.addWidget(self._expense)
        sign_layout.addWidget(self._income)
        sign_layout.addStretch()
        self._sign = sign
        self._category = make_choice_combo(
            choices.categories,
            none_label="(aucune)",
            current_id=initial.category_id if initial else None,
        )

        # --- Champ d'un virement ------------------------------------------------------------
        self._target = make_choice_combo(
            choices.accounts, current_id=initial.transfer_account_id if initial else None
        )
        if initial is None and self._target.count() > 1:
            self._target.setCurrentIndex(1 if self._account.currentIndex() == 0 else 0)

        # --- Rythme -------------------------------------------------------------------------
        self._frequency = QComboBox()
        for frequency in Frequency:
            # Qt ne garde que la valeur texte : on la reconvertit en `Frequency` à la lecture.
            self._frequency.addItem(frequency.label, frequency.value)
        if initial:
            self._frequency.setCurrentIndex(self._frequency.findData(initial.frequency.value))
        self._start = make_date_edit(initial.start_date if initial else self._today)
        self._no_end = QCheckBox("Sans date de fin")
        self._no_end.setChecked(initial is None or initial.end_date is None)
        self._end = make_date_edit(
            initial.end_date
            if initial and initial.end_date
            else self._today.replace(year=self._today.year + 1)
        )
        self._end.setEnabled(not self._no_end.isChecked())
        end_row = QHBoxLayout()
        end_row.addWidget(self._no_end)
        end_row.addWidget(self._end)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")

        # --- Assemblage ---------------------------------------------------------------------
        self._form = QFormLayout()
        form = self._form
        form.addRow("Nature :", kind)
        form.addRow(self._account_label, self._account)
        form.addRow("Vers le compte :", self._target)
        form.addRow("Tiers :", self._payee)
        form.addRow("Sens :", self._sign)
        form.addRow("Montant (€) :", self._amount)
        form.addRow("Catégorie :", self._category)
        form.addRow("Moyen de paiement :", self._method)
        form.addRow("Notes :", self._notes)
        form.addRow("Fréquence :", self._frequency)
        form.addRow("Première échéance :", self._start)
        form.addRow("Dernière échéance :", end_row)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        if locked:
            # Des opérations existent déjà : changer le rythme fausserait le décompte.
            for widget in (self._frequency, self._start):
                widget.setEnabled(False)
                widget.setToolTip(
                    "Des opérations ont déjà été générées : pour changer de rythme, terminez "
                    "cette échéance (date de fin) et créez-en une nouvelle."
                )
        self._locked = locked

        self._kind_transfer.toggled.connect(self._update_visibility)
        self._no_end.toggled.connect(lambda checked: self._end.setEnabled(not checked))
        self._start.dateChanged.connect(self._update_hint)
        self._update_visibility()
        self._update_hint()
        self._amount.setFocus()

    # --- Affichage selon la nature ---------------------------------------------------------

    def _update_visibility(self) -> None:
        transfer = self._kind_transfer.isChecked()
        self._account_label.setText("Depuis le compte :" if transfer else "Compte :")
        self._form.setRowVisible(self._target, transfer)
        for widget in (self._payee, self._sign, self._category):
            self._form.setRowVisible(widget, not transfer)

    def _update_hint(self) -> None:
        text = "Les opérations déjà générées ne sont jamais modifiées par une échéance."
        if not self._locked and date_value(self._start) < self._today:
            text = (
                "La date de début est passée : les occurrences passées seront créées "
                "immédiatement. " + text
            )
        self._hint.setText(text)

    # --- Validation ------------------------------------------------------------------------

    def accept(self) -> None:
        account_id = self._account.currentData()
        if account_id is None:
            show_error(self, "Aucun compte ouvert : créez d'abord un compte.")
            return
        transfer = self._kind_transfer.isChecked()
        target_id = self._target.currentData() if transfer else None
        if transfer and (target_id is None or target_id == account_id):
            show_error(self, "Choisissez deux comptes différents.")
            return
        try:
            cents = positive_amount(self._amount)
        except ValueError as error:
            show_error(self, error)
            return

        start = date_value(self._start)
        end = None if self._no_end.isChecked() else date_value(self._end)
        if end is not None and end < start:
            show_error(self, "La date de fin ne peut pas précéder la date de début.")
            return

        self._input = ScheduleInput(
            account_id=account_id,
            amount_cents=cents if transfer or self._income.isChecked() else -cents,
            frequency=Frequency(self._frequency.currentData()),
            start_date=start,
            end_date=end,
            payee_name="" if transfer else self._payee.currentText().strip(),
            category_id=None if transfer else self._category.currentData(),
            payment_method_id=self._method.currentData(),
            notes=self._notes.text().strip(),
            transfer_account_id=target_id,
        )
        super().accept()

    def values(self) -> ScheduleInput:
        assert self._input is not None, "values() n'est valable qu'après validation du dialogue"
        return self._input
