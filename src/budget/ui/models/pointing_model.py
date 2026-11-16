"""Modèle Qt de l'écran de rapprochement : les opérations à pointer, avec une case à cocher.

Nouveauté par rapport aux modèles en lecture seule : ici une cellule est **modifiable**.
Pour cela le modèle ajoute trois choses :
- `flags()` déclare la cellule cochable (`ItemIsUserCheckable`) ;
- `data()` répond au rôle `CheckStateRole` (case cochée ou non) ;
- `setData()` est appelée par Qt quand l'utilisateur clique : le modèle décide s'il accepte.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt

from budget.domain.enums import ReconciliationStatus
from budget.domain.money import format_cents
from budget.services.transactions import RegisterLine
from budget.ui.models.register_model import payee_text

_ROOT = QModelIndex()

HEADERS = ("Pt", "Date", "Tiers", "Catégorie", "Notes", "Débit", "Crédit")
COL_CHECK, COL_DATE, COL_PAYEE, COL_CATEGORY, COL_NOTES, COL_DEBIT, COL_CREDIT = range(7)

# Fonction fournie par le dialogue : (id de l'opération, pointée ?) -> succès ?
ToggleCallback = Callable[[int, bool], bool]


class PointingTableModel(QAbstractTableModel):
    def __init__(self, on_toggle: ToggleCallback, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_toggle = on_toggle
        self._lines: list[RegisterLine] = []

    def set_lines(self, lines: list[RegisterLine]) -> None:
        self.beginResetModel()
        self._lines = list(lines)
        self.endResetModel()

    def line_at(self, row: int) -> RegisterLine:
        return self._lines[row]

    def is_pointed(self, row: int) -> bool:
        return self._lines[row].status is ReconciliationStatus.POINTED

    def toggle_row(self, row: int) -> bool:
        """Inverse la case de la ligne. Retourne False si le changement a été refusé."""
        wanted = Qt.CheckState.Unchecked if self.is_pointed(row) else Qt.CheckState.Checked
        return self.setData(self.index(row, COL_CHECK), wanted, Qt.ItemDataRole.CheckStateRole)

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

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        line = self._lines[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.CheckStateRole and column == COL_CHECK:
            return (
                Qt.CheckState.Checked if self.is_pointed(index.row()) else Qt.CheckState.Unchecked
            )

        if role == Qt.ItemDataRole.TextAlignmentRole and column in (COL_DEBIT, COL_CREDIT):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_DATE:
                return line.date.strftime("%d/%m/%Y")
            if column == COL_PAYEE:
                return payee_text(line)
            if column == COL_CATEGORY:
                return line.category_name
            if column == COL_NOTES:
                return line.notes
            if column == COL_DEBIT and line.amount_cents < 0:
                return format_cents(-line.amount_cents, symbol=False)
            if column == COL_CREDIT and line.amount_cents > 0:
                return format_cents(line.amount_cents, symbol=False)
        return None

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or index.column() != COL_CHECK:
            return False
        if role != Qt.ItemDataRole.CheckStateRole:
            return False

        row = index.row()
        wanted = Qt.CheckState(value) == Qt.CheckState.Checked
        if wanted == self.is_pointed(row):
            return True  # rien à changer

        line = self._lines[row]
        if not self._on_toggle(line.transaction_id, wanted):
            return False  # refusé (le dialogue a déjà affiché l'erreur) : la case ne bouge pas

        status = ReconciliationStatus.POINTED if wanted else ReconciliationStatus.NONE
        self._lines[row] = dataclasses.replace(line, status=status)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True
