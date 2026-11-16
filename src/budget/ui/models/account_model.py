"""Modèle Qt de la liste des comptes.

Rappel du principe modèle/vue : le `QTableView` ne contient aucune donnée. Il pose des
questions au modèle (« combien de lignes ? », « que faut-il afficher en ligne 2,
colonne 1 ? ») et le modèle répond depuis ses propres données.
"""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from budget.domain.money import format_cents
from budget.services.accounts import AccountBalance

_ROOT = QModelIndex()  # « pas de parent » : un tableau plat n'a que des lignes racine
_GREY = QBrush(QColor("gray"))
_RED = QBrush(QColor("#c0392b"))

HEADERS = ("Compte", "Solde actuel", "Solde prévisionnel")


class AccountTableModel(QAbstractTableModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._balances: list[AccountBalance] = []

    # --- Remplissage -------------------------------------------------------------------

    def set_balances(self, balances: list[AccountBalance]) -> None:
        # begin/endResetModel préviennent les vues que tout a changé : elles se redessinent.
        self.beginResetModel()
        self._balances = list(balances)
        self.endResetModel()

    def balance_at(self, row: int) -> AccountBalance:
        return self._balances[row]

    def row_of_account(self, account_id: int) -> int | None:
        for row, balance in enumerate(self._balances):
            if balance.account_id == account_id:
                return row
        return None

    # --- Les cinq méthodes que Qt appelle ---------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._balances)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return HEADERS[section]
        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        balance = self._balances[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return f"{balance.name} (clôturé)" if balance.closed else balance.name
            return format_cents(balance.current_cents if column == 1 else balance.forecast_cents)

        if role == Qt.ItemDataRole.TextAlignmentRole and column > 0:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if balance.closed:
                return _GREY
            if (
                column > 0
                and (balance.current_cents if column == 1 else balance.forecast_cents) < 0
            ):
                return _RED
        return None
