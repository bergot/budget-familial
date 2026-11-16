"""Écran de rapprochement : pointer les opérations du registre face au relevé de la banque."""

import dataclasses
import datetime as dt

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget.domain.enums import ReconciliationStatus
from budget.domain.money import format_cents, parse_amount
from budget.services import accounts
from budget.services import reconciliation as rec
from budget.services.transactions import RegisterLine
from budget.ui.dialogs.common import (
    confirm,
    date_value,
    make_amount_edit,
    make_date_edit,
    run_action,
)
from budget.ui.models.pointing_model import COL_NOTES, PointingTableModel

_RED = "color: #c0392b; font-weight: bold;"
_GREEN = "color: #1e8449; font-weight: bold;"


class ReconciliationDialog(QDialog):
    """Rapprochement d'un compte.

    Le pointage est enregistré à chaque case cochée : on peut fermer la fenêtre et reprendre
    plus tard. Le bouton « Valider » n'est actif que si l'écart est nul.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        account_id: int,
        *,
        today: dt.date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory = session_factory
        self._account_id = account_id
        self._all_lines: list[RegisterLine] = []
        self._state = rec.ReconciliationState(0, 0, 0)
        self.setWindowTitle("Rapprochement")
        self.resize(940, 680)

        with session_factory() as session:
            account = accounts.get_account(session, account_id)
            last = rec.last_reconciliation(session, account_id)
            account_name = account.name
        last_text = (
            f"Dernier rapprochement : {last.statement_date.strftime('%d/%m/%Y')}, "
            f"solde {format_cents(last.statement_balance_cents)}"
            if last
            else "Ce compte n'a encore jamais été rapproché."
        )

        # --- En-tête : le relevé de la banque ------------------------------------------------
        title = QLabel(f"<b>{account_name}</b><br>{last_text}")
        self._date = make_date_edit(today or dt.date.today())
        self._balance = make_amount_edit()
        self._balance.setPlaceholderText("solde indiqué sur le relevé")
        statement = QFormLayout()
        statement.addRow("Date du relevé :", self._date)
        statement.addRow("Solde du relevé (€) :", self._balance)
        self._show_later = QCheckBox("Afficher les opérations postérieures à la date du relevé")

        # --- Tableau des opérations à pointer -----------------------------------------------------
        self._model = PointingTableModel(self._on_toggle, self)
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
        self._view.doubleClicked.connect(self._on_double_click)

        # --- Contrôle : l'écart ---------------------------------------------------------------
        self._previous = QLabel()
        self._pointed = QLabel()
        self._pointed_balance = QLabel()
        self._statement_balance = QLabel()
        self._gap = QLabel()
        for label in (
            self._previous,
            self._pointed,
            self._pointed_balance,
            self._statement_balance,
            self._gap,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        control = QFormLayout()
        control.addRow("Solde rapproché précédent :", self._previous)
        control.addRow("Opérations pointées :", self._pointed)
        control.addRow("Solde pointé :", self._pointed_balance)
        control.addRow("Solde du relevé :", self._statement_balance)
        control.addRow("<b>Écart :</b>", self._gap)
        box = QGroupBox("Contrôle")
        box.setLayout(control)

        # --- Boutons -------------------------------------------------------------------------
        self._clear = QPushButton("Tout dépointer")
        close = QPushButton("Fermer")
        self._validate = QPushButton("Valider le rapprochement")
        self._validate.setDefault(True)
        self._clear.clicked.connect(self._on_clear)
        close.clicked.connect(self.reject)
        self._validate.clicked.connect(self._on_validate)
        buttons = QHBoxLayout()
        buttons.addWidget(self._clear)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self._validate)

        top = QHBoxLayout()
        top.addWidget(title, stretch=1)
        top.addLayout(statement)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._show_later)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(box)
        layout.addLayout(buttons)

        self._balance.textChanged.connect(self._refresh_summary)
        self._date.dateChanged.connect(self._apply_filter)
        self._show_later.toggled.connect(self._apply_filter)

        self._reload()
        self._balance.setFocus()

    # --- Chargement ----------------------------------------------------------------------------

    def _reload(self) -> None:
        with self._factory() as session:
            self._all_lines = rec.pointable_lines(session, self._account_id)
            self._state = rec.reconciliation_state(session, self._account_id)
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Affiche les opérations jusqu'à la date du relevé, plus toutes celles déjà pointées."""
        statement_date = date_value(self._date)
        show_later = self._show_later.isChecked()
        visible = [
            line
            for line in self._all_lines
            if show_later
            or line.date <= statement_date
            or line.status is ReconciliationStatus.POINTED
        ]
        self._model.set_lines(visible)
        self._refresh_summary()

    def _statement_balance_cents(self) -> int | None:
        text = self._balance.text().strip()
        if not text:
            return None
        try:
            return parse_amount(text)
        except ValueError:
            return None

    def _refresh_summary(self) -> None:
        state = self._state
        statement = self._statement_balance_cents()

        self._previous.setText(format_cents(state.reconciled_balance_cents))
        self._pointed.setText(
            f"{state.pointed_count} (total {format_cents(state.pointed_total_cents)})"
        )
        self._pointed_balance.setText(
            format_cents(state.reconciled_balance_cents + state.pointed_total_cents)
        )

        if statement is None:
            self._statement_balance.setText("—")
            self._gap.setText("—")
            self._gap.setStyleSheet("")
            self._validate.setEnabled(False)
        else:
            gap = state.gap_cents(statement)
            self._statement_balance.setText(format_cents(statement))
            self._gap.setText(format_cents(gap))
            self._gap.setStyleSheet(_GREEN if gap == 0 else _RED)
            self._validate.setEnabled(gap == 0 and state.pointed_count > 0)
        self._clear.setEnabled(state.pointed_count > 0)

    # --- Actions -------------------------------------------------------------------------------

    def _on_toggle(self, transaction_id: int, pointed: bool) -> bool:
        """Appelée par le modèle quand l'utilisateur coche ou décoche une ligne."""

        def point(session: Session) -> bool:
            rec.set_pointed(session, transaction_id, pointed=pointed)
            return True

        if run_action(self, self._factory, point) is None:
            return False  # l'erreur a été affichée ; la case ne change pas
        status = ReconciliationStatus.POINTED if pointed else ReconciliationStatus.NONE
        self._all_lines = [
            dataclasses.replace(line, status=status)
            if line.transaction_id == transaction_id
            else line
            for line in self._all_lines
        ]
        with self._factory() as session:
            self._state = rec.reconciliation_state(session, self._account_id)
        self._refresh_summary()
        return True

    def _on_double_click(self, index: QModelIndex) -> None:
        self._model.toggle_row(index.row())

    def _on_clear(self) -> None:
        if not confirm(
            self,
            "Tout dépointer",
            "Retirer le pointage de toutes les opérations pointées ?",
            "Tout dépointer",
        ):
            return
        cleared = run_action(
            self, self._factory, lambda session: rec.clear_pointing(session, self._account_id)
        )
        if cleared is not None:
            self._reload()

    def _on_validate(self) -> None:
        statement = self._statement_balance_cents()
        if statement is None:
            return
        statement_date = date_value(self._date)
        summary = run_action(
            self,
            self._factory,
            lambda session: rec.complete_reconciliation(
                session,
                self._account_id,
                statement_date=statement_date,
                statement_balance_cents=statement,
            ),
        )
        if summary is not None:
            self.accept()
