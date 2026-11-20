"""Modèle Qt de la grille du budget : catégories en lignes, mois en colonnes.

Une même grille peut montrer trois choses, au choix (`ViewMode`) : le **prévu** (modifiable,
saisi directement dans les cellules comme dans un tableur), le **réalisé** (calculé à partir des
opérations) ou l'**écart** entre les deux. Seul le prévu est modifiable.
"""

from collections.abc import Callable
from enum import Enum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from budget.domain.money import format_cents
from budget.services.budgets import Budget, BudgetRow, RowKind

_ROOT = QModelIndex()

MONTH_HEADERS = (
    "Janv.",
    "Févr.",
    "Mars",
    "Avr.",
    "Mai",
    "Juin",
    "Juil.",
    "Août",
    "Sept.",
    "Oct.",
    "Nov.",
    "Déc.",
)
HEADERS = ("Catégorie", *MONTH_HEADERS, "Total")
COL_LABEL = 0
FIRST_MONTH_COL, LAST_MONTH_COL = 1, 12
COL_TOTAL = 13

_RED = QBrush(QColor("#c0392b"))
_GREEN = QBrush(QColor("#1e8449"))
_GREY = QBrush(QColor("gray"))
_SHADE = QBrush(QColor(128, 128, 128, 45))  # translucide : lisible en thème clair comme sombre
_BOLD_ROWS = {RowKind.HEADER, RowKind.PARENT_TOTAL, RowKind.SECTION_TOTAL, RowKind.BALANCE}
_SHADED_ROWS = {RowKind.HEADER, RowKind.SECTION_TOTAL, RowKind.BALANCE}

# Fonction fournie par la fenêtre : (id de catégorie, mois 1-12, texte saisi) -> accepté ?
EditCallback = Callable[[int, int, str], bool]


class ViewMode(Enum):
    PLANNED = "Prévu (saisie)"
    ACTUAL = "Réalisé"
    VARIANCE = "Écart"


class BudgetTableModel(QAbstractTableModel):
    def __init__(self, on_edit: EditCallback, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_edit = on_edit
        self._rows: tuple[BudgetRow, ...] = ()
        self._mode = ViewMode.PLANNED
        self._comparable = 12  # nombre de mois dont l'écart est affiché (voir `comparable_months`)
        self._bold = QFont()
        self._bold.setBold(True)
        self._italic = QFont()
        self._italic.setItalic(True)

    # --- Contenu et mode ---------------------------------------------------------------

    @property
    def mode(self) -> ViewMode:
        return self._mode

    def row_at(self, row: int) -> BudgetRow:
        return self._rows[row]

    def same_structure(self, budget: Budget) -> bool:
        """Les lignes sont-elles les mêmes (seuls les montants ont pu changer) ?"""
        return len(budget.rows) == len(self._rows) and all(
            (new.kind, new.label, new.category_id) == (old.kind, old.label, old.category_id)
            for new, old in zip(budget.rows, self._rows, strict=True)
        )

    def set_budget(self, budget: Budget) -> None:
        """Remplace le contenu. Si la structure est inchangée, met seulement les valeurs à jour :
        pas de remise à zéro, donc la sélection et l'édition en cours ne sont pas perturbées."""
        if self._rows and self.same_structure(budget):
            self._rows = budget.rows
            self._emit_all_changed()
            return
        self.beginResetModel()
        self._rows = budget.rows
        self.endResetModel()

    def set_mode(self, mode: ViewMode) -> None:
        if mode is not self._mode:
            self._mode = mode
            self._emit_all_changed()

    def set_comparable_months(self, count: int) -> None:
        """Limite l'écart aux `count` premiers mois : les mois à venir restent vides."""
        if count != self._comparable:
            self._comparable = count
            self._emit_all_changed()

    def _emit_all_changed(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, COL_TOTAL))

    def cell_is_editable(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        return (
            self._mode is ViewMode.PLANNED
            and index.isValid()
            and FIRST_MONTH_COL <= index.column() <= LAST_MONTH_COL
            and self._rows[index.row()].editable
        )

    def _value(self, row: BudgetRow, column: int) -> int | None:
        """Montant (en centimes) de la cellule selon le mode ; None = cellule vide."""
        if self._mode is ViewMode.VARIANCE:
            if column == COL_TOTAL:
                if self._comparable == 0:
                    return None
                return sum(row.variance(month) for month in range(self._comparable))
            month = column - FIRST_MONTH_COL
            return row.variance(month) if month < self._comparable else None
        if column == COL_TOTAL:
            return row.planned_total if self._mode is ViewMode.PLANNED else row.actual_total
        month = column - FIRST_MONTH_COL
        return row.planned[month] if self._mode is ViewMode.PLANNED else row.actual[month]

    # --- Les méthodes que Qt appelle ---------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

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
        if self.cell_is_editable(index):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, column)
        if role == Qt.ItemDataRole.EditRole and self.cell_is_editable(index):
            cents = self._value(row, column)
            return format_cents(cents, symbol=False) if cents else ""
        if role == Qt.ItemDataRole.TextAlignmentRole and column != COL_LABEL:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.FontRole:
            if row.kind in _BOLD_ROWS or column == COL_TOTAL:
                return self._bold
            if row.kind is RowKind.UNCATEGORIZED:
                return self._italic
        if role == Qt.ItemDataRole.BackgroundRole and row.kind in _SHADED_ROWS:
            return _SHADE
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row, column)
        return None

    def _display(self, row: BudgetRow, column: int) -> str | None:
        if column == COL_LABEL:
            return ("      " if row.depth else "") + row.label
        if row.kind is RowKind.HEADER:
            return None
        cents = self._value(row, column)
        return format_cents(cents, symbol=False) if cents else ""

    def _foreground(self, row: BudgetRow, column: int) -> QBrush | None:
        if row.kind is RowKind.UNCATEGORIZED and column == COL_LABEL:
            return _GREY
        if column == COL_LABEL or row.kind is RowKind.HEADER:
            return None
        cents = self._value(row, column)
        if cents is None:
            return None
        if self._mode is ViewMode.VARIANCE:
            return _RED if cents < 0 else (_GREEN if cents > 0 else None)
        if row.kind is RowKind.BALANCE and cents < 0:
            return _RED  # un solde négatif est toujours à signaler
        return None

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Appelée par Qt quand l'utilisateur valide une cellule : on enregistre le montant."""
        if role != Qt.ItemDataRole.EditRole or not self.cell_is_editable(index):
            return False
        row = self._rows[index.row()]
        if row.category_id is None:
            return False
        return self._on_edit(row.category_id, index.column(), str(value))
