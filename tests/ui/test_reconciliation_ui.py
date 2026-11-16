"""Tests de l'écran de rapprochement et de son intégration dans la fenêtre principale."""

import datetime as dt

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import unit_of_work
from budget.domain.enums import ReconciliationStatus as Status
from budget.domain.money import NBSP
from budget.services import accounts
from budget.services import reconciliation as rec
from budget.services import transactions as tx
from budget.services.transactions import RegisterLine, TransactionData
from budget.ui.dialogs.reconciliation_dialog import ReconciliationDialog
from budget.ui.main_window import MainWindow
from budget.ui.models.pointing_model import COL_CHECK, COL_DEBIT, PointingTableModel
from budget.ui.models.register_model import COL_STATUS
from tests.ui.conftest import TODAY
from tests.ui.helpers import answer_next_dialog, click_button

Factory = sessionmaker[Session]
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
CHECK_ROLE = Qt.ItemDataRole.CheckStateRole


def make_line(**overrides) -> RegisterLine:  # type: ignore[no-untyped-def]
    values = {
        "transaction_id": 1,
        "account_id": 1,
        "date": dt.date(2026, 3, 1),
        "amount_cents": -2000,
        "balance_cents": 0,
        "payee_name": "Carrefour",
        "category_id": None,
        "category_name": "",
        "payment_method_id": None,
        "payment_method_name": "",
        "notes": "",
        "transfer_account_id": None,
        "transfer_account_name": "",
    }
    values.update(overrides)
    return RegisterLine(**values)  # type: ignore[arg-type]


# --- Modèle à cases à cocher ----------------------------------------------------------------


def test_pointing_model_is_checkable_only_in_first_column(qapp) -> None:  # type: ignore[no-untyped-def]
    model = PointingTableModel(lambda _id, _pointed: True)
    model.set_lines([make_line()])
    assert model.flags(model.index(0, COL_CHECK)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not model.flags(model.index(0, COL_DEBIT)) & Qt.ItemFlag.ItemIsUserCheckable


def test_pointing_model_reports_check_state(qapp) -> None:  # type: ignore[no-untyped-def]
    model = PointingTableModel(lambda _id, _pointed: True)
    model.set_lines(
        [make_line(transaction_id=1), make_line(transaction_id=2, status=Status.POINTED)]
    )
    assert model.data(model.index(0, COL_CHECK), CHECK_ROLE) == UNCHECKED
    assert model.data(model.index(1, COL_CHECK), CHECK_ROLE) == CHECKED
    assert model.data(model.index(0, COL_DEBIT)) == "20,00"


def test_checking_a_row_calls_back_and_updates(qapp) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[int, bool]] = []
    model = PointingTableModel(lambda tid, pointed: calls.append((tid, pointed)) is None)
    model.set_lines([make_line(transaction_id=7)])
    changed: list[object] = []
    model.dataChanged.connect(lambda *args: changed.append(args))

    assert model.setData(model.index(0, COL_CHECK), CHECKED, CHECK_ROLE) is True

    assert calls == [(7, True)]
    assert model.is_pointed(0)
    assert len(changed) == 1  # la vue est prévenue : elle redessine la case


def test_refused_toggle_leaves_the_row_unchanged(qapp) -> None:  # type: ignore[no-untyped-def]
    model = PointingTableModel(lambda _id, _pointed: False)
    model.set_lines([make_line()])
    assert model.setData(model.index(0, COL_CHECK), CHECKED, CHECK_ROLE) is False
    assert not model.is_pointed(0)


def test_unchanged_state_does_not_call_back(qapp) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    model = PointingTableModel(lambda tid, _pointed: calls.append(tid) is None)
    model.set_lines([make_line()])
    model.setData(model.index(0, COL_CHECK), UNCHECKED, CHECK_ROLE)
    assert calls == []


def test_only_the_check_column_is_editable(qapp) -> None:  # type: ignore[no-untyped-def]
    model = PointingTableModel(lambda _id, _pointed: True)
    model.set_lines([make_line()])
    assert model.setData(model.index(0, COL_DEBIT), "x", Qt.ItemDataRole.EditRole) is False
    assert model.setData(QModelIndex(), CHECKED, CHECK_ROLE) is False


def test_toggle_row(qapp) -> None:  # type: ignore[no-untyped-def]
    model = PointingTableModel(lambda _id, _pointed: True)
    model.set_lines([make_line()])
    model.toggle_row(0)
    assert model.is_pointed(0)
    model.toggle_row(0)
    assert not model.is_pointed(0)


# --- Dialogue -------------------------------------------------------------------------------


@pytest.fixture
def sg_with_ops(factory: Factory) -> tuple[int, list[int]]:
    """Compte SG (1 000,00 €) avec -20,00 (1er mars), -30,00 (2 mars), +50,00 (3 mars)."""
    with unit_of_work(factory) as session:
        account_id = accounts.create_account(session, "SG", initial_balance_cents=100_000).id
        ids = [
            tx.add_transaction(
                session,
                TransactionData(
                    account_id=account_id, date=dt.date(2026, 3, day), amount_cents=cents
                ),
            ).id
            for day, cents in [(1, -2_000), (2, -3_000), (3, 5_000)]
        ]
    return account_id, ids


def statuses(factory: Factory, ids: list[int]) -> list[Status]:
    with factory() as session:
        return [tx.get_transaction(session, i).status for i in ids]


def test_dialog_starts_without_a_statement_balance(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)

    assert dialog._model.rowCount() == 3
    assert dialog._gap.text() == "—"
    assert not dialog._validate.isEnabled()
    assert dialog._previous.text() == f"1{chr(0x202F)}000,00{NBSP}€"


def test_gap_follows_the_pointing(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    dialog._balance.setText("1030")  # le relevé : 1 000 - 20 + 50

    dialog._model.toggle_row(0)  # -20 pointé : solde pointé 980, écart +50
    assert dialog._gap.text().startswith("50,00")
    assert "c0392b" in dialog._gap.styleSheet()  # rouge
    assert not dialog._validate.isEnabled()

    dialog._model.toggle_row(2)  # +50 pointé : écart nul
    assert dialog._gap.text().startswith("0,00")
    assert "1e8449" in dialog._gap.styleSheet()  # vert
    assert dialog._validate.isEnabled()

    dialog._model.toggle_row(2)  # on retire : l'écart revient
    assert not dialog._validate.isEnabled()


def test_invalid_statement_balance_disables_validation(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    dialog._model.toggle_row(0)
    dialog._balance.setText("abc")
    assert dialog._gap.text() == "—"
    assert not dialog._validate.isEnabled()


def test_validate_reconciles_in_the_database(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, ids = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=dt.date(2026, 3, 31))
    dialog._balance.setText("1 030,00")
    dialog._model.toggle_row(0)
    dialog._model.toggle_row(2)

    dialog._validate.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert statuses(factory, ids) == [Status.RECONCILED, Status.NONE, Status.RECONCILED]
    with factory() as session:
        last = rec.last_reconciliation(session, account_id)
        assert last is not None and last.statement_date == dt.date(2026, 3, 31)


def test_pointing_is_saved_immediately_and_survives_closing(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, ids = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    dialog._model.toggle_row(1)
    assert statuses(factory, ids) == [Status.NONE, Status.POINTED, Status.NONE]
    dialog.reject()  # on ferme sans valider

    reopened = ReconciliationDialog(factory, account_id, today=TODAY)
    assert reopened._model.is_pointed(1)
    assert reopened._pointed.text().startswith("1 ")


def test_later_operations_are_hidden_unless_requested_or_pointed(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=dt.date(2026, 3, 2))
    assert dialog._model.rowCount() == 2  # l'opération du 3 mars est postérieure au relevé

    dialog._show_later.setChecked(True)
    assert dialog._model.rowCount() == 3

    dialog._show_later.setChecked(False)
    assert dialog._model.rowCount() == 2


def test_changing_the_statement_date_refilters(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=dt.date(2026, 3, 1))
    assert dialog._model.rowCount() == 1
    dialog._date.setDate(dialog._date.date().addDays(2))  # 3 mars
    assert dialog._model.rowCount() == 3


def test_a_pointed_operation_stays_visible_after_the_date_moves_back(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=dt.date(2026, 3, 3))
    dialog._model.toggle_row(2)  # pointe l'opération du 3 mars
    dialog._date.setDate(dt.date(2026, 3, 1))  # recule la date du relevé
    assert dialog._model.rowCount() == 2  # celle du 1er mars + la pointée du 3
    assert any(dialog._model.is_pointed(row) for row in range(dialog._model.rowCount()))


def test_clear_pointing_asks_for_confirmation(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, ids = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    dialog._model.toggle_row(0)
    dialog._model.toggle_row(1)

    answer_next_dialog(lambda box: click_button(box, "Annuler"))  # type: ignore[arg-type]
    dialog._clear.click()
    assert statuses(factory, ids).count(Status.POINTED) == 2  # annulé : rien n'a changé

    answer_next_dialog(lambda box: click_button(box, "Tout dépointer"))  # type: ignore[arg-type]
    dialog._clear.click()
    assert statuses(factory, ids) == [Status.NONE] * 3
    assert not dialog._clear.isEnabled()


def test_a_failing_toggle_shows_the_error_and_keeps_the_box_unchecked(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, ids = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    # L'opération est rapprochée « ailleurs » pendant que le dialogue est ouvert.
    with unit_of_work(factory) as session:
        rec.set_pointed(session, ids[0], pointed=True)
        rec.complete_reconciliation(
            session, account_id, statement_date=TODAY, statement_balance_cents=98_000
        )
    messages: list[str] = []

    def error_box(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        messages.append(box.text())
        box.accept()

    answer_next_dialog(error_box)
    assert dialog._model.toggle_row(0) is False
    assert "déjà rapprochée" in messages[0]
    assert not dialog._model.is_pointed(0)


def test_double_click_toggles_the_row(
    qapp,
    factory: Factory,
    sg_with_ops: tuple[int, list[int]],  # type: ignore[no-untyped-def]
) -> None:
    account_id, _ = sg_with_ops
    dialog = ReconciliationDialog(factory, account_id, today=TODAY)
    dialog._view.doubleClicked.emit(dialog._model.index(0, 1))
    assert dialog._model.is_pointed(0)


# --- Fenêtre principale ---------------------------------------------------------------------


@pytest.fixture
def window(qapp, factory: Factory, sg_with_ops):  # type: ignore[no-untyped-def]
    w = MainWindow(factory, today=lambda: dt.date(2026, 3, 31))
    w.show()
    yield w
    w.close()


def lines_of(window: MainWindow) -> list[RegisterLine]:
    model = window._register._model
    return [model.line_at(row) for row in range(model.rowCount())]


def reconcile_through_the_dialog(window: MainWindow, rows: list[int], balance: str) -> None:
    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, ReconciliationDialog)
        dialog._balance.setText(balance)
        for row in rows:
            dialog._model.toggle_row(row)
        dialog._validate.click()

    answer_next_dialog(fill)
    window.act_reconcile.trigger()


def test_window_shows_the_never_reconciled_state(window: MainWindow) -> None:
    assert window._subtitle.text() == "Jamais rapproché"
    assert window.act_reconcile.isEnabled()
    assert not window.act_undo_reconcile.isEnabled()


def test_reconcile_from_the_window(window: MainWindow) -> None:
    reconcile_through_the_dialog(window, rows=[0, 2], balance="1030")

    assert window._subtitle.text().startswith("Rapproché au 31/03/2026")
    assert [line.status for line in lines_of(window)] == [
        Status.RECONCILED,
        Status.NONE,
        Status.RECONCILED,
    ]
    model = window._register._model
    assert model.data(model.index(0, COL_STATUS)) == "✓"
    assert window.act_undo_reconcile.isEnabled()


def test_pointing_in_progress_is_shown_in_the_subtitle(window: MainWindow) -> None:
    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, ReconciliationDialog)
        dialog._model.toggle_row(0)
        dialog._model.toggle_row(1)  # puis on ferme sans valider

    answer_next_dialog(fill)
    window.act_reconcile.trigger()

    assert "2 opérations pointées en cours" in window._subtitle.text()
    assert [line.status for line in lines_of(window)][:2] == [Status.POINTED, Status.POINTED]
    assert not window.act_undo_reconcile.isEnabled()  # rien de validé


def test_reconciled_line_cannot_be_edited_or_deleted(window: MainWindow) -> None:
    reconcile_through_the_dialog(window, rows=[0, 2], balance="1030")
    window._register._view.selectRow(0)  # une opération rapprochée
    assert not window.act_edit_transaction.isEnabled()
    assert not window.act_delete_transaction.isEnabled()

    messages: list[str] = []

    def error_box(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        messages.append(box.text())
        box.accept()

    answer_next_dialog(error_box)
    window._register.activated.emit()  # un double-clic reste possible : il explique
    assert "rapprochée" in messages[0]

    window._register._view.selectRow(1)  # une opération libre
    assert window.act_edit_transaction.isEnabled()
    assert window.act_delete_transaction.isEnabled()


def test_undo_reconciliation_from_the_window(window: MainWindow) -> None:
    reconcile_through_the_dialog(window, rows=[0, 2], balance="1030")

    def confirm(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        assert "31/03/2026" in box.text() and "2 opérations" in box.text()
        click_button(box, "Annuler le rapprochement")

    answer_next_dialog(confirm)
    window.act_undo_reconcile.trigger()

    assert window._subtitle.text() == "Jamais rapproché"
    assert {line.status for line in lines_of(window)} == {Status.NONE}
    assert not window.act_undo_reconcile.isEnabled()
    window._register._view.selectRow(0)
    assert window.act_edit_transaction.isEnabled()  # de nouveau modifiable


def test_undo_can_be_cancelled(window: MainWindow) -> None:
    reconcile_through_the_dialog(window, rows=[0, 2], balance="1030")
    answer_next_dialog(lambda box: click_button(box, "Annuler"))  # type: ignore[arg-type]
    window.act_undo_reconcile.trigger()
    assert window._subtitle.text().startswith("Rapproché au")
