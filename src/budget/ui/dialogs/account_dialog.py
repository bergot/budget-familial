"""Création et modification d'un compte."""

from dataclasses import dataclass

from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QVBoxLayout, QWidget

from budget.domain.money import parse_amount
from budget.ui.dialogs.common import make_amount_edit, make_button_box, show_error


@dataclass(frozen=True, slots=True)
class AccountInput:
    name: str
    bank: str | None
    initial_balance_cents: int


class AccountDialog(QDialog):
    def __init__(
        self, *, initial: AccountInput | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modifier le compte" if initial else "Nouveau compte")
        self.setMinimumWidth(380)

        self._name = QLineEdit(initial.name if initial else "")
        self._bank = QLineEdit(initial.bank or "" if initial else "")
        self._balance = make_amount_edit(initial.initial_balance_cents if initial else 0)
        self._input: AccountInput | None = None

        form = QFormLayout()
        form.addRow("Nom :", self._name)
        form.addRow("Banque :", self._bank)
        form.addRow("Solde initial (€) :", self._balance)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            show_error(self, "Le nom du compte est obligatoire.")
            return
        try:
            balance = parse_amount(self._balance.text() or "0")
        except ValueError:
            show_error(self, "Le solde initial n'est pas valide (exemple : 1 250,00).")
            return
        self._input = AccountInput(name, self._bank.text().strip() or None, balance)
        super().accept()

    def values(self) -> AccountInput:
        assert self._input is not None, "values() n'est valable qu'après validation du dialogue"
        return self._input
