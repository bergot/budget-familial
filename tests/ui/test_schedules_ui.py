"""Tests de l'écran des échéances, de son intégration, et du démarrage de l'application."""

import datetime as dt
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import unit_of_work
from budget.domain.enums import Frequency
from budget.services import accounts, categories, lookups
from budget.services import schedules as sch
from budget.services import transactions as tx
from budget.services.choices import Choice, Choices, load_choices
from budget.services.schedules import ScheduleData, ScheduleLine
from budget.ui import main_window as main_window_module
from budget.ui.app import open_database
from budget.ui.dialogs.schedule_form_dialog import ScheduleFormDialog
from budget.ui.dialogs.schedules_dialog import SchedulesDialog
from budget.ui.main_window import MainWindow
from budget.ui.models.register_model import COL_DATE
from budget.ui.models.schedule_model import (
    COL_AMOUNT,
    COL_END,
    COL_FREQUENCY,
    COL_LABEL,
    COL_NEXT,
    ScheduleTableModel,
)
from tests.ui.conftest import TODAY
from tests.ui.helpers import answer_next_dialog, click_button

Factory = sessionmaker[Session]
D = dt.date
CHOICES = Choices(
    accounts=(Choice(1, "SG"), Choice(2, "Boursorama")),
    categories=(Choice(10, "Logement"),),
    payment_methods=(Choice(20, "Virement"),),
    payee_names=("Agence",),
)


def make_line(**overrides) -> ScheduleLine:  # type: ignore[no-untyped-def]
    values = {
        "id": 1,
        "account_id": 1,
        "account_name": "SG",
        "label": "Agence",
        "signed_amount_cents": -65_000,
        "frequency": Frequency.MONTHLY,
        "start_date": D(2026, 3, 5),
        "end_date": None,
        "generated_count": 0,
        "next_date": D(2026, 3, 5),
        "amount_cents": -65_000,
        "payee_id": None,
        "payee_name": "Agence",
        "category_id": 10,
        "category_name": "Logement",
        "payment_method_id": None,
        "payment_method_name": "",
        "notes": "Loyer",
        "transfer_account_id": None,
    }
    values.update(overrides)
    return ScheduleLine(**values)  # type: ignore[arg-type]


def make_accounts(factory: Factory) -> tuple[int, int]:
    with unit_of_work(factory) as session:
        sg = accounts.create_account(session, "SG", initial_balance_cents=100_000).id
        bourso = accounts.create_account(session, "Boursorama").id
    return sg, bourso


def schedule_lines(factory: Factory) -> list[ScheduleLine]:
    with factory() as session:
        return sch.list_schedule_lines(session)


# --- Modèle ---------------------------------------------------------------------------------


def test_model_texts(qapp) -> None:  # type: ignore[no-untyped-def]
    model = ScheduleTableModel()
    model.set_lines([make_line(end_date=D(2027, 1, 1))])
    text = lambda column: model.data(model.index(0, column))  # noqa: E731
    assert text(COL_LABEL) == "Agence"
    assert text(COL_FREQUENCY) == "Mensuelle"
    assert text(COL_AMOUNT) == "-650,00\u00a0€"
    assert text(COL_NEXT) == "05/03/2026"
    assert text(COL_END) == "01/01/2027"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Description"


def test_model_ended_schedule_is_greyed(qapp) -> None:  # type: ignore[no-untyped-def]
    model = ScheduleTableModel()
    model.set_lines([make_line(next_date=None, end_date=D(2026, 7, 1)), make_line(id=2)])
    assert model.data(model.index(0, COL_NEXT)) == "Terminée"
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) is not None
    assert model.data(model.index(1, 0), Qt.ItemDataRole.ForegroundRole) is None
    assert model.data(model.index(1, COL_END)) == ""  # pas de date de fin


def test_model_row_lookup(qapp) -> None:  # type: ignore[no-untyped-def]
    model = ScheduleTableModel()
    model.set_lines([make_line(id=4), make_line(id=9)])
    assert model.row_of_schedule(9) == 1
    assert model.row_of_schedule(123) is None


# --- Formulaire -----------------------------------------------------------------------------


def test_form_builds_an_expense_schedule(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES, today=D(2026, 3, 15))
    dialog._payee.setCurrentText(" Agence ")
    dialog._amount.setText("650")
    dialog._category.setCurrentIndex(dialog._category.findData(10))
    dialog._frequency.setCurrentIndex(dialog._frequency.findData(Frequency.QUARTERLY.value))
    dialog._notes.setText("Loyer")
    dialog.accept()

    values = dialog.values()
    assert values.amount_cents == -65_000
    assert values.frequency is Frequency.QUARTERLY
    assert values.start_date == D(2026, 3, 15)
    assert values.end_date is None  # « sans date de fin » par défaut
    assert (values.payee_name, values.category_id, values.notes) == ("Agence", 10, "Loyer")
    assert values.transfer_account_id is None


def test_form_income(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES)
    dialog._income.setChecked(True)
    dialog._amount.setText("1 200")
    dialog.accept()
    assert dialog.values().amount_cents == 120_000


def test_form_transfer_ignores_the_operation_fields(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES)
    dialog._payee.setCurrentText("Quelqu'un")  # saisi avant de basculer en virement
    dialog._category.setCurrentIndex(dialog._category.findData(10))
    dialog._kind_transfer.setChecked(True)
    dialog._account.setCurrentIndex(dialog._account.findData(1))
    dialog._target.setCurrentIndex(dialog._target.findData(2))
    dialog._amount.setText("400")
    dialog.accept()

    values = dialog.values()
    assert values.amount_cents == 40_000  # positif : le sens est « compte -> destination »
    assert (values.account_id, values.transfer_account_id) == (1, 2)
    assert values.payee_name == "" and values.category_id is None


def test_form_shows_the_fields_matching_the_nature(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES)
    dialog.show()
    assert dialog._payee.isVisible() and not dialog._target.isVisible()
    dialog._kind_transfer.setChecked(True)
    assert dialog._target.isVisible() and not dialog._payee.isVisible()
    assert not dialog._category.isVisible()
    assert dialog._account_label.text() == "Depuis le compte :"


def test_form_end_date(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES, today=D(2026, 3, 15))
    assert not dialog._end.isEnabled()
    dialog._no_end.setChecked(False)
    assert dialog._end.isEnabled()
    dialog._end.setDate(D(2026, 12, 31))
    dialog._amount.setText("10")
    dialog.accept()
    assert dialog.values().end_date == D(2026, 12, 31)


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from budget.ui.dialogs import schedule_form_dialog

    messages: list[str] = []
    monkeypatch.setattr(
        schedule_form_dialog, "show_error", lambda _parent, error: messages.append(str(error))
    )
    return messages


def test_form_rejects_invalid_input(qapp, errors: list[str]) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES, today=D(2026, 3, 15))
    dialog._amount.setText("abc")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._amount.setText("10")
    dialog._no_end.setChecked(False)
    dialog._end.setDate(D(2026, 1, 1))  # avant le début
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert len(errors) == 2 and "fin" in errors[1]

    dialog._kind_transfer.setChecked(True)
    dialog._no_end.setChecked(True)
    dialog._target.setCurrentIndex(dialog._target.findData(1))
    dialog._account.setCurrentIndex(dialog._account.findData(1))
    dialog.accept()
    assert "différents" in errors[2]


def test_form_prefill_and_lock(qapp) -> None:  # type: ignore[no-untyped-def]
    line = make_line(generated_count=4, frequency=Frequency.YEARLY, end_date=D(2030, 1, 1))
    dialog = ScheduleFormDialog(CHOICES, initial=line, today=D(2026, 3, 15))
    assert dialog._payee.currentText() == "Agence"
    assert dialog._amount.text() == "650,00"
    assert dialog._expense.isChecked()
    assert Frequency(dialog._frequency.currentData()) is Frequency.YEARLY
    assert dialog._start.date().toPython() == D(2026, 3, 5)
    assert not dialog._no_end.isChecked() and dialog._end.date().toPython() == D(2030, 1, 1)
    # Des opérations existent déjà : rythme et début verrouillés.
    assert not dialog._frequency.isEnabled() and not dialog._start.isEnabled()
    assert "déjà été générées" in dialog._frequency.toolTip()
    assert "passées" not in dialog._hint.text()  # pas d'avertissement quand c'est verrouillé


def test_form_unlocked_when_nothing_was_generated(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES, initial=make_line(generated_count=0), today=D(2026, 3, 1))
    assert dialog._frequency.isEnabled() and dialog._start.isEnabled()


def test_form_prefill_transfer(qapp) -> None:  # type: ignore[no-untyped-def]
    line = make_line(
        account_id=1,
        transfer_account_id=2,
        amount_cents=40_000,
        signed_amount_cents=-40_000,
        label="Virement vers Boursorama",
        payee_name="",
        category_id=None,
    )
    dialog = ScheduleFormDialog(CHOICES, initial=line)
    assert dialog._kind_transfer.isChecked()
    assert (dialog._account.currentData(), dialog._target.currentData()) == (1, 2)
    assert dialog._amount.text() == "400,00"


def test_form_warns_about_a_past_start_date(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = ScheduleFormDialog(CHOICES, today=D(2026, 3, 15))
    assert "passée" not in dialog._hint.text()
    dialog._start.setDate(D(2026, 1, 1))
    assert "créées immédiatement" in dialog._hint.text()


# --- Écran de gestion -----------------------------------------------------------------------


def fill_new_rent(account_id: int):  # type: ignore[no-untyped-def]
    def fill(form: QDialog) -> None:
        assert isinstance(form, ScheduleFormDialog)
        form._account.setCurrentIndex(form._account.findData(account_id))
        form._payee.setCurrentText("Agence")
        form._amount.setText("650")
        form._start.setDate(D(2026, 3, 5))
        form.accept()

    return fill


def test_creating_a_schedule_generates_its_operations(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)  # 15 mars 2026 : horizon 15 juin
    assert dialog._model.rowCount() == 0 and not dialog._edit.isEnabled()

    answer_next_dialog(fill_new_rent(sg))
    dialog._new.click()

    assert dialog._model.rowCount() == 1
    assert dialog._selected_line() is not None  # la nouvelle échéance est sélectionnée
    assert dialog._status.text() == "4 opérations générées."
    assert dialog._edit.isEnabled() and dialog._delete.isEnabled()
    with factory() as session:
        dates = [t.date for t in tx.list_transactions(session, sg)]
        assert dates == [D(2026, 3, 5), D(2026, 4, 5), D(2026, 5, 5), D(2026, 6, 5)]
        assert [p.name for p in lookups.list_payees(session)] == ["Agence"]  # tiers créé


def test_editing_a_schedule_keeps_generated_operations(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)
    answer_next_dialog(fill_new_rent(sg))
    dialog._new.click()

    def change(form: QDialog) -> None:
        assert isinstance(form, ScheduleFormDialog)
        assert not form._frequency.isEnabled()  # verrouillée : des opérations existent
        form._amount.setText("700")
        form._no_end.setChecked(False)
        form._end.setDate(D(2026, 4, 30))
        form.accept()

    answer_next_dialog(change)
    dialog._edit.click()

    (line,) = schedule_lines(factory)
    assert line.amount_cents == -70_000 and line.end_date == D(2026, 4, 30)
    with factory() as session:
        amounts = {t.amount_cents for t in tx.list_transactions(session, sg)}
    assert amounts == {-65_000}  # les opérations générées n'ont pas bougé


def test_business_error_is_shown_and_nothing_is_created(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    with unit_of_work(factory) as session:
        sch.create_schedule(session, ScheduleData(sg, -100, Frequency.MONTHLY, D(2026, 3, 5)))
        sch.generate_due_transactions(session, today=TODAY)
    dialog = SchedulesDialog(factory, today=TODAY)
    dialog._view.selectRow(0)
    messages: list[str] = []

    def error_box(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        messages.append(box.text())
        box.accept()

    def change_rhythm(form: QDialog) -> None:
        assert isinstance(form, ScheduleFormDialog)
        form._frequency.setEnabled(True)  # on force : le service doit refuser quand même
        form._frequency.setCurrentIndex(form._frequency.findData(Frequency.YEARLY.value))
        form._amount.setText("100")
        answer_next_dialog(error_box)
        form.accept()

    answer_next_dialog(change_rhythm)
    dialog._edit.click()

    assert "déjà été générées" in messages[0]
    assert schedule_lines(factory)[0].frequency is Frequency.MONTHLY


def test_deleting_a_schedule_asks_for_confirmation(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)
    answer_next_dialog(fill_new_rent(sg))
    dialog._new.click()

    answer_next_dialog(lambda box: click_button(box, "Annuler"))  # type: ignore[arg-type]
    dialog._delete.click()
    assert len(schedule_lines(factory)) == 1

    def confirm(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        assert "conservées" in box.text()
        click_button(box, "Supprimer")

    answer_next_dialog(confirm)
    dialog._delete.click()

    assert schedule_lines(factory) == []
    assert dialog._model.rowCount() == 0
    with factory() as session:  # les opérations déjà générées sont conservées
        assert len(tx.list_transactions(session, sg)) == 4


def test_a_scheduled_transfer_from_the_screen(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, bourso = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)

    def fill(form: QDialog) -> None:
        assert isinstance(form, ScheduleFormDialog)
        form._kind_transfer.setChecked(True)
        form._account.setCurrentIndex(form._account.findData(sg))
        form._target.setCurrentIndex(form._target.findData(bourso))
        form._amount.setText("400")
        form._start.setDate(D(2026, 3, 1))
        form.accept()

    answer_next_dialog(fill)
    dialog._new.click()

    assert dialog._model.line_at(0).label == "Virement vers Boursorama"
    with factory() as session:
        assert accounts.forecast_balance(session, bourso) == 4 * 40_000


def test_double_click_opens_the_edit_form(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)
    answer_next_dialog(fill_new_rent(sg))
    dialog._new.click()
    opened: list[str] = []

    def peek(form: QDialog) -> None:
        assert isinstance(form, ScheduleFormDialog)
        opened.append(form.windowTitle())

    answer_next_dialog(peek)
    dialog._view.doubleClicked.emit(dialog._model.index(0, 0))
    assert opened == ["Modifier l'échéance"]


def test_skipped_schedules_are_reported_in_the_status_line(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    sg, _ = make_accounts(factory)
    dialog = SchedulesDialog(factory, today=TODAY)
    skipped = sch.SkippedSchedule(1, "Loyer (SG)", "Le compte « SG » est clôturé")
    dialog._report(sch.GenerationResult(created=0, skipped=(skipped,)))
    assert "0 opération générée" in dialog._status.text()
    assert "Loyer (SG)" in dialog._status.text() and "clôturé" in dialog._status.text()


# --- Fenêtre principale ---------------------------------------------------------------------


@pytest.fixture
def window(qapp, factory: Factory):  # type: ignore[no-untyped-def]
    w = MainWindow(factory, today=lambda: TODAY)
    w.show()
    yield w
    w.close()


def test_schedules_menu_opens_the_screen_and_refreshes_the_register(
    window: MainWindow, factory: Factory
) -> None:
    sg, _ = make_accounts(factory)
    window.refresh(select_account_id=sg)  # sinon, Boursorama (ordre alphabétique) serait affiché
    assert window._register._model.rowCount() == 0

    def manage(dialog: QDialog) -> None:
        assert isinstance(dialog, SchedulesDialog)
        answer_next_dialog(fill_new_rent(sg))
        dialog._new.click()
        dialog.accept()

    answer_next_dialog(manage)
    window.act_schedules.trigger()

    model = window._register._model
    assert model.rowCount() == 4
    tip = model.data(model.index(0, COL_DATE), Qt.ItemDataRole.ToolTipRole)
    assert tip == "Opération générée par une échéance"
    # Les opérations à venir comptent dans le solde prévisionnel, pas dans le solde actuel.
    balance = window._accounts.selected_balance()
    assert balance is not None
    assert balance.forecast_cents == 100_000 - 4 * 65_000
    assert balance.current_cents == 100_000 - 65_000


def test_manual_operations_have_no_schedule_tooltip(window: MainWindow, factory: Factory) -> None:
    sg, _ = make_accounts(factory)
    with unit_of_work(factory) as session:
        tx.add_transaction(
            session, tx.TransactionData(account_id=sg, date=TODAY, amount_cents=-100)
        )
    window.refresh()
    model = window._register._model
    assert model.data(model.index(0, COL_DATE), Qt.ItemDataRole.ToolTipRole) is None


def test_report_generation_tells_the_user(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window_module,
        "show_error",
        lambda _parent, text, title="Erreur": shown.append((title, str(text))),
    )

    window.report_generation(sch.GenerationResult(created=0))  # rien à dire
    assert shown == [] and window.statusBar().currentMessage() == ""

    window.report_generation(sch.GenerationResult(created=3))
    assert "3 opérations créées" in window.statusBar().currentMessage()

    skipped = sch.SkippedSchedule(7, "Loyer (SG)", "Le compte « SG » est clôturé")
    window.report_generation(sch.GenerationResult(created=1, skipped=(skipped,)))
    assert "1 opération créée" in window.statusBar().currentMessage()
    (title, text) = shown[0]
    assert title == "Échéances ignorées"
    assert "Loyer (SG)" in text and "clôturé" in text


# --- Démarrage ------------------------------------------------------------------------------


def test_startup_generates_schedules_without_duplicates(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, first = open_database(database, today=TODAY)
    assert first.created == 0  # base neuve : aucune échéance

    with unit_of_work(factory) as session:
        sg = accounts.create_account(session, "SG").id
        categories.create_category(session, "Logement")
        sch.create_schedule(session, ScheduleData(sg, -65_000, Frequency.MONTHLY, D(2026, 3, 5)))

    # Deuxième lancement, le même jour : les opérations sont créées.
    factory, second = open_database(database, today=TODAY)
    assert second.created == 4
    # Troisième lancement, le même jour : rien de plus.
    factory, third = open_database(database, today=TODAY)
    assert third.created == 0
    # Un lancement plus tard dans l'année rattrape le retard.
    factory, later = open_database(database, today=D(2026, 6, 20))
    assert later.created == 3  # horizon au 20 septembre : juillet, août et septembre
    with factory() as session:
        assert len(tx.list_transactions(session, sg)) == 4 + later.created


def test_startup_reports_skipped_schedules(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        sg = accounts.create_account(session, "SG").id
        sch.create_schedule(session, ScheduleData(sg, -100, Frequency.MONTHLY, D(2026, 3, 5)))
        accounts.set_account_closed(session, sg, closed=True)

    _, result = open_database(database, today=TODAY)

    assert result.created == 0
    assert len(result.skipped) == 1 and "clôturé" in result.skipped[0].reason


def test_choices_are_available_for_the_form(factory: Factory) -> None:
    make_accounts(factory)
    with factory() as session:
        choices = load_choices(session)
    assert [c.label for c in choices.accounts] == ["Boursorama", "SG"]
