"""Modèle Qt de la liste des échéances."""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from budget.domain.money import format_cents
from budget.services.schedules import ScheduleLine

_ROOT = QModelIndex()
_GREY = QBrush(QColor("gray"))

HEADERS = ("Compte", "Description", "Fréquence", "Montant", "Catégorie", "Prochaine", "Fin")
COL_ACCOUNT, COL_LABEL, COL_FREQUENCY, COL_AMOUNT, COL_CATEGORY, COL_NEXT, COL_END = range(7)


def _date_text(day: object) -> str:
    return day.strftime("%d/%m/%Y") if hasattr(day, "strftime") else ""


class ScheduleTableModel(QAbstractTableModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lines: list[ScheduleLine] = []

    def set_lines(self, lines: list[ScheduleLine]) -> None:
        self.beginResetModel()
        self._lines = list(lines)
        self.endResetModel()

    def line_at(self, row: int) -> ScheduleLine:
        return self._lines[row]

    def row_of_schedule(self, schedule_id: int) -> int | None:
        for row, line in enumerate(self._lines):
            if line.id == schedule_id:
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
        if role == Qt.ItemDataRole.TextAlignmentRole and column == COL_AMOUNT:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and line.next_date is None:
            return _GREY  # échéance terminée
        return None

    @staticmethod
    def _text(line: ScheduleLine, column: int) -> str:
        if column == COL_ACCOUNT:
            return line.account_name
        if column == COL_LABEL:
            return line.label
        if column == COL_FREQUENCY:
            return line.frequency.label
        if column == COL_AMOUNT:
            return format_cents(line.signed_amount_cents)
        if column == COL_CATEGORY:
            return line.category_name
        if column == COL_NEXT:
            return _date_text(line.next_date) if line.next_date else "Terminée"
        return _date_text(line.end_date)
