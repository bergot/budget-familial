"""Registre d'un compte : le tableau de ses opérations (panneau de droite)."""

import datetime as dt

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from budget.services.transactions import RegisterLine
from budget.ui.models.register_model import COL_NOTES, RegisterTableModel


class RegisterView(QWidget):
    selection_changed = Signal()
    activated = Signal()  # double-clic sur une ligne : l'appelant ouvre la modification

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = RegisterTableModel(self)

        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(True)
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NOTES, QHeaderView.ResizeMode.Stretch)

        self._view.selectionModel().selectionChanged.connect(
            lambda *_: self.selection_changed.emit()
        )
        self._view.doubleClicked.connect(self._on_double_click)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def _on_double_click(self, _index: QModelIndex) -> None:
        self.activated.emit()

    def set_lines(
        self,
        lines: list[RegisterLine],
        today: dt.date,
        select_transaction_id: int | None = None,
    ) -> None:
        """Remplace le contenu. Conserve la sélection, ou sélectionne l'opération demandée.

        À défaut de sélection, fait défiler jusqu'à la dernière opération passée : les
        opérations à venir restent en dessous.
        """
        if select_transaction_id is None:
            current = self.selected_line()
            select_transaction_id = current.transaction_id if current else None

        self._model.set_lines(lines, today)

        row = (
            self._model.row_of_transaction(select_transaction_id)
            if select_transaction_id is not None
            else None
        )
        if row is not None:
            self._view.selectRow(row)
            self._view.scrollTo(self._model.index(row, 0))
            return
        last_past = self._model.last_past_row()
        if last_past is not None:
            self._view.scrollTo(self._model.index(last_past, 0))

    def selected_line(self) -> RegisterLine | None:
        rows = self._view.selectionModel().selectedRows()
        return self._model.line_at(rows[0].row()) if rows else None
