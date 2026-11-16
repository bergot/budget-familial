"""Modèle Qt du registre d'un compte (la liste de ses opérations)."""

import datetime as dt
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from budget.domain.money import format_cents
from budget.services.transactions import RegisterLine

_ROOT = QModelIndex()
_GREY = QBrush(QColor("gray"))
_RED = QBrush(QColor("#c0392b"))

HEADERS = ("Date", "Tiers", "Catégorie", "Moyen", "Notes", "Débit", "Crédit", "Solde")
COL_DATE, COL_PAYEE, COL_CATEGORY, COL_METHOD, COL_NOTES, COL_DEBIT, COL_CREDIT, COL_BALANCE = (
    range(8)
)
_RIGHT_ALIGNED = {COL_DEBIT, COL_CREDIT, COL_BALANCE}


def payee_text(line: RegisterLine) -> str:
    """Texte de la colonne « Tiers » : le nom du tiers, ou le sens du virement."""
    if line.is_transfer:
        direction = "vers" if line.amount_cents < 0 else "depuis"
        return f"Virement {direction} {line.transfer_account_name}"
    return line.payee_name


class RegisterTableModel(QAbstractTableModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lines: list[RegisterLine] = []
        self._today = dt.date.today()
        self._italic = QFont()
        self._italic.setItalic(True)

    # --- Remplissage -------------------------------------------------------------------

    def set_lines(self, lines: list[RegisterLine], today: dt.date) -> None:
        self.beginResetModel()
        self._lines = list(lines)
        self._today = today
        self.endResetModel()

    def line_at(self, row: int) -> RegisterLine:
        return self._lines[row]

    def row_of_transaction(self, transaction_id: int) -> int | None:
        for row, line in enumerate(self._lines):
            if line.transaction_id == transaction_id:
                return row
        return None

    def last_past_row(self) -> int | None:
        """Dernière ligne datée d'aujourd'hui ou avant (pour faire défiler jusqu'à elle)."""
        for row in range(len(self._lines) - 1, -1, -1):
            if self._lines[row].date <= self._today:
                return row
        return None

    # --- Les méthodes que Qt appelle ---------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._lines)

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
        line = self._lines[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(line, column)

        if role == Qt.ItemDataRole.TextAlignmentRole and column in _RIGHT_ALIGNED:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        is_future = line.date > self._today
        if role == Qt.ItemDataRole.ForegroundRole:
            if is_future:
                return _GREY
            if column == COL_BALANCE and line.balance_cents < 0:
                return _RED
        if role == Qt.ItemDataRole.FontRole and is_future:
            return self._italic  # opérations à venir : en italique et grisées
        return None

    @staticmethod
    def _text(line: RegisterLine, column: int) -> str:
        if column == COL_DATE:
            return line.date.strftime("%d/%m/%Y")
        if column == COL_PAYEE:
            return payee_text(line)
        if column == COL_CATEGORY:
            return line.category_name
        if column == COL_METHOD:
            return line.payment_method_name
        if column == COL_NOTES:
            return line.notes
        if column == COL_DEBIT:
            return format_cents(-line.amount_cents, symbol=False) if line.amount_cents < 0 else ""
        if column == COL_CREDIT:
            return format_cents(line.amount_cents, symbol=False) if line.amount_cents > 0 else ""
        return format_cents(line.balance_cents)
