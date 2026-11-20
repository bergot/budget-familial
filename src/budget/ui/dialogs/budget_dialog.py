"""Fenêtre du budget : grille catégories x mois, saisie directe des montants prévus."""

import datetime as dt

from PySide6.QtCore import QModelIndex, QTimer
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget.domain.money import parse_amount
from budget.services import budgets as bud
from budget.services.budgets import RowKind
from budget.ui.dialogs.common import run_action, show_error
from budget.ui.models.budget_model import (
    COL_LABEL,
    COL_TOTAL,
    FIRST_MONTH_COL,
    LAST_MONTH_COL,
    MONTH_HEADERS,
    BudgetTableModel,
    ViewMode,
)


class BudgetGridView(QTableView):
    """Tableau où Entrée valide la cellule et descend à la suivante, comme dans un tableur."""

    def closeEditor(
        self,
        editor: QWidget,
        hint: QAbstractItemDelegate.EndEditHint = QAbstractItemDelegate.EndEditHint.NoHint,
    ) -> None:
        super().closeEditor(editor, hint)
        # Entrée (ou perte de focus) : on passe à la ligne du dessous. Échap (annulation) ou
        # Tab (déjà géré par Qt) ne déclenchent pas ce déplacement.
        if hint in (
            QAbstractItemDelegate.EndEditHint.NoHint,
            QAbstractItemDelegate.EndEditHint.SubmitModelCache,
        ):
            current = self.currentIndex()
            below = self.model().index(current.row() + 1, current.column())
            if below.isValid():
                self.setCurrentIndex(below)


class BudgetDialog(QDialog):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        today: dt.date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory = session_factory
        self._today = today or dt.date.today()
        self.setWindowTitle("Budget")
        self.resize(1400, 780)

        self._year = QSpinBox()
        self._year.setRange(bud.MIN_YEAR, bud.MAX_YEAR)
        self._year.setValue(self._today.year)
        self._year.setWrapping(False)
        self._mode = QComboBox()
        for mode in ViewMode:
            self._mode.addItem(mode.value, mode.name)
        self._hide_empty = QCheckBox("Masquer les lignes « sans sous-catégorie » vides")
        self._hide_empty.setChecked(True)

        self._model = BudgetTableModel(self._on_edit, self)
        self._view = BudgetGridView()
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed  # on tape un montant : la saisie démarre
        )
        self._view.verticalHeader().setVisible(False)
        self._view.setColumnWidth(COL_LABEL, 280)
        for column in range(FIRST_MONTH_COL, LAST_MONTH_COL + 1):
            self._view.setColumnWidth(column, 82)
        self._view.setColumnWidth(COL_TOTAL, 105)

        self._fill_right = QPushButton("Recopier vers la droite")
        self._fill_right.setToolTip(
            "Applique le montant de la cellule sélectionnée jusqu'à décembre"
        )
        self._copy_previous = QPushButton("Reprendre l'année précédente")
        self._copy_previous.setToolTip(
            "Copie les montants prévus de l'année précédente dans les cases encore vides"
        )
        close = QPushButton("Fermer")
        self._status = QLabel()
        hint = QLabel(
            "Saisissez les montants prévus en positif : c'est le type de la catégorie "
            "(dépense ou recette) qui donne le sens. Le total d'une catégorie est calculé."
        )
        hint.setStyleSheet("color: gray;")
        hint.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("Année :"))
        top.addWidget(self._year)
        top.addSpacing(16)
        top.addWidget(QLabel("Afficher :"))
        top.addWidget(self._mode)
        top.addSpacing(16)
        top.addWidget(self._hide_empty)
        top.addStretch()
        bottom = QHBoxLayout()
        bottom.addWidget(self._fill_right)
        bottom.addWidget(self._copy_previous)
        bottom.addWidget(self._status, stretch=1)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(hint)
        layout.addWidget(self._view, stretch=1)
        layout.addLayout(bottom)

        self._year.valueChanged.connect(self._reload)
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        self._hide_empty.toggled.connect(self._reload)
        self._fill_right.clicked.connect(self._on_fill_right)
        self._copy_previous.clicked.connect(self._on_copy_previous)
        close.clicked.connect(self.accept)
        self._model.modelReset.connect(self._apply_spans)
        self._view.selectionModel().currentChanged.connect(lambda *_: self._update_buttons())

        self._reload()

    # --- Chargement ----------------------------------------------------------------------

    def year(self) -> int:
        return int(self._year.value())

    def _reload(self) -> None:
        current = self._view.currentIndex()
        with self._factory() as session:
            budget = bud.build_budget(
                session, self.year(), hide_empty_direct=self._hide_empty.isChecked()
            )
        self._model.set_comparable_months(bud.comparable_months(self.year(), self._today))
        self._model.set_budget(budget)
        if current.isValid():
            row = min(current.row(), self._model.rowCount() - 1)
            self._view.setCurrentIndex(self._model.index(row, current.column()))
        self._update_buttons()

    def _apply_spans(self) -> None:
        """Les titres de section (« Recettes », « Dépenses ») occupent toute la largeur."""
        self._view.clearSpans()
        for row in range(self._model.rowCount()):
            if self._model.row_at(row).kind is RowKind.HEADER:
                self._view.setSpan(row, 0, 1, self._model.columnCount())

    def _update_buttons(self) -> None:
        editing = self._model.mode is ViewMode.PLANNED
        self._fill_right.setEnabled(self._model.cell_is_editable(self._view.currentIndex()))
        self._copy_previous.setEnabled(editing)

    def _on_mode_changed(self) -> None:
        self._model.set_mode(ViewMode[self._mode.currentData()])
        self._update_buttons()

    # --- Saisie --------------------------------------------------------------------------

    def _on_edit(self, category_id: int, month: int, text: str) -> bool:
        """Appelée par le modèle quand une cellule est validée."""
        text = text.strip()
        try:
            cents = parse_amount(text) if text else 0
        except ValueError:
            show_error(self, "Ce montant n'est pas valide (exemples : 400 ou 1 250,50).")
            return False

        def save(session: Session) -> bool:
            bud.set_planned(session, category_id, self.year(), month, cents)
            return True

        if run_action(self, self._factory, save) is None:
            return False

        with self._factory() as session:
            budget = bud.build_budget(
                session, self.year(), hide_empty_direct=self._hide_empty.isChecked()
            )
        if self._model.same_structure(budget):
            self._model.set_budget(budget)  # met seulement les montants à jour
        else:
            # Une ligne apparaît ou disparaît : on ne remet pas le modèle à zéro en pleine
            # validation d'une cellule, on attend que Qt ait fini.
            QTimer.singleShot(0, self._reload)
        return True

    def _on_fill_right(self) -> None:
        index = self._view.currentIndex()
        if not self._model.cell_is_editable(index):
            return
        row = self._model.row_at(index.row())
        month = index.column()
        category_id = row.category_id
        if category_id is None:
            return
        cents = row.planned[month - 1]

        def fill(session: Session) -> bool:
            bud.fill_planned(
                session, category_id, self.year(), from_month=month, amount_cents=cents
            )
            return True

        if run_action(self, self._factory, fill) is not None:
            self._reload()
            self._status.setText(f"Montant recopié de {MONTH_HEADERS[month - 1]} à décembre.")

    def _on_copy_previous(self) -> None:
        year = self.year()
        written = run_action(
            self, self._factory, lambda session: bud.copy_planned(session, year - 1, year)
        )
        if written is None:
            return
        self._reload()
        plural = "s" if written > 1 else ""
        self._status.setText(f"{written} montant{plural} repris de {year - 1}.")

    def current_cell(self) -> QModelIndex:
        return self._view.currentIndex()

    def select_cell(self, row: int, column: int) -> None:
        """Sélectionne une cellule (utilisé par les tests)."""
        self._view.setCurrentIndex(self._model.index(row, column))

    def row_of(self, label: str) -> int:
        """Numéro de la ligne portant ce libellé (utilisé par les tests)."""
        for row in range(self._model.rowCount()):
            if self._model.row_at(row).label == label:
                return row
        raise KeyError(label)
