"""Liste des comptes avec leurs soldes (panneau de gauche)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from budget.services.accounts import AccountBalance
from budget.ui.models.account_model import AccountTableModel


class AccountList(QWidget):
    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = AccountTableModel(self)

        self._view = QTableView()
        self._view.setModel(self._model)  # la vue interroge le modèle pour tout affichage
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(True)
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        selection = self._view.selectionModel()
        selection.selectionChanged.connect(lambda *_: self.selection_changed.emit())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def set_balances(self, balances: list[AccountBalance], select_account_id: int | None) -> None:
        """Remplace la liste. Sélectionne `select_account_id`, sinon le premier compte.

        Le signal `selection_changed` est suspendu pendant le remplacement : c'est l'appelant
        qui recharge la suite, une seule fois.
        """
        selection = self._view.selectionModel()
        selection.blockSignals(True)
        try:
            self._model.set_balances(balances)
            row = (
                self._model.row_of_account(select_account_id)
                if select_account_id is not None
                else None
            )
            if row is None and balances:
                row = 0
            if row is not None:
                self._view.selectRow(row)
        finally:
            selection.blockSignals(False)

    def selected_balance(self) -> AccountBalance | None:
        rows = self._view.selectionModel().selectedRows()
        return self._model.balance_at(rows[0].row()) if rows else None

    def selected_account_id(self) -> int | None:
        balance = self.selected_balance()
        return balance.account_id if balance else None
