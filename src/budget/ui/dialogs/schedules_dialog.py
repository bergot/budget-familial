"""Écran de gestion des échéances : liste, création, modification, suppression."""

import datetime as dt

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget.services import lookups
from budget.services import schedules as sch
from budget.services.choices import load_choices
from budget.ui.dialogs.common import confirm, run_action
from budget.ui.dialogs.schedule_form_dialog import ScheduleFormDialog, ScheduleInput
from budget.ui.models.schedule_model import COL_LABEL, ScheduleTableModel


class SchedulesDialog(QDialog):
    """Gestion des échéances.

    Chaque création ou modification est suivie d'une génération des opérations dues : on voit
    tout de suite leur effet dans le registre et le solde prévisionnel.
    """

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
        self.setWindowTitle("Échéances")
        self.resize(960, 460)

        self._model = ScheduleTableModel(self)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(True)
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_LABEL, QHeaderView.ResizeMode.Stretch)
        self._view.doubleClicked.connect(self._on_double_click)
        self._view.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())

        self._status = QLabel()
        self._new = QPushButton("Nouvelle échéance…")
        self._edit = QPushButton("Modifier…")
        self._delete = QPushButton("Supprimer")
        close = QPushButton("Fermer")
        self._new.clicked.connect(self._on_new)
        self._edit.clicked.connect(self._on_edit)
        self._delete.clicked.connect(self._on_delete)
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._new)
        buttons.addWidget(self._edit)
        buttons.addWidget(self._delete)
        buttons.addStretch()
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        self._reload()

    # --- Affichage -------------------------------------------------------------------------

    def _reload(self, select_id: int | None = None) -> None:
        with self._factory() as session:
            lines = sch.list_schedule_lines(session)
        self._model.set_lines(lines)
        row = self._model.row_of_schedule(select_id) if select_id is not None else None
        if row is not None:
            self._view.selectRow(row)
        self._update_buttons()

    def _selected_line(self) -> sch.ScheduleLine | None:
        rows = self._view.selectionModel().selectedRows()
        return self._model.line_at(rows[0].row()) if rows else None

    def _update_buttons(self) -> None:
        selected = self._selected_line() is not None
        self._edit.setEnabled(selected)
        self._delete.setEnabled(selected)

    def _report(self, result: sch.GenerationResult) -> None:
        count = result.created
        text = f"{count} opération{'s' if count > 1 else ''} générée{'s' if count > 1 else ''}."
        if result.skipped:
            text += f" {len(result.skipped)} échéance(s) ignorée(s) : " + "; ".join(
                f"{s.description} ({s.reason})" for s in result.skipped
            )
        self._status.setText(text)

    # --- Actions ---------------------------------------------------------------------------

    def _save(
        self, session: Session, schedule_id: int | None, form: ScheduleInput
    ) -> tuple[int, sch.GenerationResult]:
        """Crée ou modifie l'échéance, puis génère les opérations dues (une seule transaction)."""
        payee_id = (
            lookups.get_or_create_payee(session, form.payee_name).id if form.payee_name else None
        )
        data = sch.ScheduleData(
            account_id=form.account_id,
            amount_cents=form.amount_cents,
            frequency=form.frequency,
            start_date=form.start_date,
            end_date=form.end_date,
            payee_id=payee_id,
            category_id=form.category_id,
            payment_method_id=form.payment_method_id,
            notes=form.notes,
            transfer_account_id=form.transfer_account_id,
        )
        if schedule_id is None:
            schedule = sch.create_schedule(session, data)
        else:
            schedule = sch.update_schedule(session, schedule_id, data)
        result = sch.generate_due_transactions(session, today=self._today)
        return schedule.id, result

    def _on_new(self) -> None:
        with self._factory() as session:
            choices = load_choices(session)
        form_dialog = ScheduleFormDialog(choices, today=self._today, parent=self)
        if form_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        form = form_dialog.values()
        outcome = run_action(self, self._factory, lambda session: self._save(session, None, form))
        if outcome is not None:
            schedule_id, result = outcome
            self._report(result)
            self._reload(select_id=schedule_id)

    def _on_edit(self) -> None:
        line = self._selected_line()
        if line is None:
            return
        with self._factory() as session:
            choices = load_choices(session)
        form_dialog = ScheduleFormDialog(choices, initial=line, today=self._today, parent=self)
        if form_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        form = form_dialog.values()
        outcome = run_action(
            self, self._factory, lambda session: self._save(session, line.id, form)
        )
        if outcome is not None:
            schedule_id, result = outcome
            self._report(result)
            self._reload(select_id=schedule_id)

    def _on_double_click(self, _index: QModelIndex) -> None:
        self._on_edit()

    def _on_delete(self) -> None:
        line = self._selected_line()
        if line is None:
            return
        if not confirm(
            self,
            "Supprimer l'échéance",
            f"Supprimer l'échéance « {line.label or line.notes or line.account_name} » ?\n\n"
            "Les opérations déjà générées sont conservées ; aucune nouvelle ne sera créée.",
            "Supprimer",
        ):
            return

        def delete(session: Session) -> bool:
            sch.delete_schedule(session, line.id)
            return True

        if run_action(self, self._factory, delete) is not None:
            self._status.setText("Échéance supprimée.")
            self._reload()
