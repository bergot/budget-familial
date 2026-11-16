"""Tests de la fenêtre principale : on simule les actions de l'utilisateur."""

import pytest
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import unit_of_work
from budget.services import accounts, categories, lookups
from budget.services import transactions as tx
from budget.services.transactions import TransactionData
from budget.ui.dialogs.account_dialog import AccountDialog
from budget.ui.dialogs.categories_dialog import CategoriesDialog
from budget.ui.dialogs.transaction_dialog import TransactionDialog
from budget.ui.dialogs.transfer_dialog import TransferDialog
from budget.ui.main_window import MainWindow
from tests.ui.conftest import TODAY
from tests.ui.helpers import answer_next_dialog, click_button

Factory = sessionmaker[Session]


@pytest.fixture
def window(qapp, factory: Factory):  # type: ignore[no-untyped-def]
    w = MainWindow(factory, today=lambda: TODAY)
    w.show()
    yield w
    w.close()


def make_account(factory: Factory, name: str, cents: int = 0) -> int:
    with unit_of_work(factory) as session:
        return accounts.create_account(session, name, initial_balance_cents=cents).id


def lines(window: MainWindow):  # type: ignore[no-untyped-def]
    model = window._register._model
    return [model.line_at(row) for row in range(model.rowCount())]


def select_account(window: MainWindow, account_id: int) -> None:
    window._accounts._view.selectRow(window._accounts._model.row_of_account(account_id))


# --- Démarrage ------------------------------------------------------------------------------


def test_window_opens_on_an_empty_database(window: MainWindow) -> None:
    assert window.windowTitle() == "Budget familial"
    assert window.isVisible()
    assert "Aucun compte" in window._title.text()
    assert not window.act_new_transaction.isEnabled()
    assert not window.act_new_transfer.isEnabled()
    assert window.act_new_account.isEnabled()


def test_window_lists_accounts_and_selects_the_first(window: MainWindow, factory: Factory) -> None:
    make_account(factory, "SG", 100_000)
    make_account(factory, "Boursorama")
    window.refresh()
    assert window._accounts._model.rowCount() == 2
    assert window._accounts.selected_balance().name == "Boursorama"  # ordre alphabétique
    assert window.act_new_transaction.isEnabled()


# --- Comptes --------------------------------------------------------------------------------


def test_create_account_through_the_dialog(window: MainWindow) -> None:
    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, AccountDialog)
        dialog._name.setText("Livret A")
        dialog._bank.setText("SG")
        dialog._balance.setText("1 500,00")
        dialog.accept()

    answer_next_dialog(fill)
    window.act_new_account.trigger()

    balance = window._accounts.selected_balance()
    assert balance.name == "Livret A"
    assert balance.current_cents == 150_000
    assert "Livret A" in window._title.text()
    assert "(SG)" in window._title.text()


def test_duplicate_account_shows_an_error_and_keeps_going(
    window: MainWindow, factory: Factory
) -> None:
    make_account(factory, "SG")
    window.refresh()
    messages: list[str] = []

    def error_box(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        messages.append(box.text())
        box.accept()

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, AccountDialog)
        dialog._name.setText("sg")
        answer_next_dialog(error_box)  # le service refuse : une boîte d'erreur s'affichera
        dialog.accept()

    answer_next_dialog(fill)
    window.act_new_account.trigger()

    assert len(messages) == 1 and "existe déjà" in messages[0]
    assert window._accounts._model.rowCount() == 1


def test_edit_account(window: MainWindow, factory: Factory) -> None:
    account_id = make_account(factory, "SG", 1000)
    window.refresh()

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, AccountDialog)
        assert dialog._name.text() == "SG"  # le formulaire est prérempli
        dialog._name.setText("SG joint")
        dialog._balance.setText("20")
        dialog.accept()

    answer_next_dialog(fill)
    window.act_edit_account.trigger()

    balance = window._accounts.selected_balance()
    assert (balance.account_id, balance.name, balance.current_cents) == (
        account_id,
        "SG joint",
        2000,
    )


def test_close_and_reopen_account(window: MainWindow, factory: Factory) -> None:
    make_account(factory, "SG")
    other = make_account(factory, "Zèbre")
    window.refresh(select_account_id=other)

    answer_next_dialog(lambda box: click_button(box, "Clôturer"))  # type: ignore[arg-type]
    window.act_toggle_closed.trigger()

    assert [window._accounts._model.balance_at(r).name for r in range(1)] == ["SG"]
    assert window._accounts._model.rowCount() == 1  # le compte clôturé est masqué

    window.act_show_closed.setChecked(True)
    assert window._accounts._model.rowCount() == 2
    select_account(window, other)
    assert not window.act_new_transaction.isEnabled()  # on ne saisit plus sur un compte clôturé
    assert window.act_toggle_closed.text() == "&Rouvrir le compte"

    window.act_toggle_closed.trigger()  # rouvrir : pas de confirmation
    assert window.act_new_transaction.isEnabled()


# --- Opérations -----------------------------------------------------------------------------


def test_new_transaction_through_the_dialog(window: MainWindow, factory: Factory) -> None:
    account_id = make_account(factory, "SG", 100_000)
    with unit_of_work(factory) as session:
        # On lit l'identifiant *dans* le bloc : après le commit, l'objet est expiré et détaché.
        category_id = categories.create_category(session, "Courses").id
    window.refresh()

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, TransactionDialog)
        assert dialog._account.currentData() == account_id  # compte courant présélectionné
        dialog._payee.setCurrentText("Carrefour")
        dialog._amount.setText("42,50")
        dialog._category.setCurrentIndex(dialog._category.findData(category_id))
        dialog.accept()

    answer_next_dialog(fill)
    window.act_new_transaction.trigger()

    (line,) = lines(window)
    assert line.payee_name == "Carrefour"
    assert line.amount_cents == -4250
    assert line.balance_cents == 100_000 - 4250
    assert line.date == TODAY
    assert window._register.selected_line().transaction_id == line.transaction_id
    assert window._accounts.selected_balance().current_cents == 95_750
    with factory() as session:  # le tiers a bien été créé en base
        assert [p.name for p in lookups.list_payees(session)] == ["Carrefour"]


def test_future_transaction_changes_forecast_only(window: MainWindow, factory: Factory) -> None:
    make_account(factory, "SG", 100_000)
    window.refresh()

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, TransactionDialog)
        dialog._date.setDate(dialog._date.date().addMonths(1))
        dialog._amount.setText("10")
        dialog.accept()

    answer_next_dialog(fill)
    window.act_new_transaction.trigger()

    balance = window._accounts.selected_balance()
    assert balance.current_cents == 100_000
    assert balance.forecast_cents == 99_000


def test_new_transfer_through_the_dialog(window: MainWindow, factory: Factory) -> None:
    sg = make_account(factory, "SG", 100_000)
    bourso = make_account(factory, "Boursorama")
    window.refresh(select_account_id=sg)

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, TransferDialog)
        assert dialog._from.currentData() == sg
        dialog._to.setCurrentIndex(dialog._to.findData(bourso))
        dialog._amount.setText("300")
        dialog.accept()

    answer_next_dialog(fill)
    window.act_new_transfer.trigger()

    (line,) = lines(window)  # registre de SG
    assert line.amount_cents == -30_000 and line.transfer_account_name == "Boursorama"
    assert window._register.selected_line().transaction_id == line.transaction_id
    select_account(window, bourso)
    (other,) = lines(window)
    assert other.amount_cents == 30_000 and other.transfer_account_name == "SG"


def test_edit_transaction_by_double_click_signal(window: MainWindow, factory: Factory) -> None:
    account_id = make_account(factory, "SG", 100_000)
    with unit_of_work(factory) as session:
        tx.add_transaction(
            session, TransactionData(account_id=account_id, date=TODAY, amount_cents=-1000)
        )
    window.refresh()
    window._register._view.selectRow(0)

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, TransactionDialog)
        assert dialog._amount.text() == "10,00"
        dialog._income.setChecked(True)
        dialog._amount.setText("25")
        dialog.accept()

    answer_next_dialog(fill)
    window._register.activated.emit()  # ce que fait un double-clic

    (line,) = lines(window)
    assert line.amount_cents == 2500
    assert line.balance_cents == 102_500


def test_edit_transfer_updates_both_accounts(window: MainWindow, factory: Factory) -> None:
    sg = make_account(factory, "SG", 100_000)
    bourso = make_account(factory, "Boursorama")
    with unit_of_work(factory) as session:
        tx.create_transfer(
            session,
            tx.TransferData(
                from_account_id=sg, to_account_id=bourso, date=TODAY, amount_cents=10_000
            ),
        )
    window.refresh(select_account_id=sg)
    window._register._view.selectRow(0)

    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, TransferDialog)
        dialog._amount.setText("45")
        dialog.accept()

    answer_next_dialog(fill)
    window.act_edit_transaction.trigger()

    assert lines(window)[0].amount_cents == -4500
    select_account(window, bourso)
    assert lines(window)[0].amount_cents == 4500


def test_delete_transaction_needs_confirmation(window: MainWindow, factory: Factory) -> None:
    account_id = make_account(factory, "SG")
    with unit_of_work(factory) as session:
        tx.add_transaction(
            session, TransactionData(account_id=account_id, date=TODAY, amount_cents=-1000)
        )
    window.refresh()
    window._register._view.selectRow(0)

    answer_next_dialog(lambda box: click_button(box, "Annuler"))  # type: ignore[arg-type]
    window.act_delete_transaction.trigger()
    assert len(lines(window)) == 1  # annulé : rien n'a changé

    answer_next_dialog(lambda box: click_button(box, "Supprimer"))  # type: ignore[arg-type]
    window.act_delete_transaction.trigger()
    assert lines(window) == []


def test_delete_transfer_removes_both_legs(window: MainWindow, factory: Factory) -> None:
    sg = make_account(factory, "SG", 100_000)
    bourso = make_account(factory, "Boursorama")
    with unit_of_work(factory) as session:
        tx.create_transfer(
            session,
            tx.TransferData(
                from_account_id=sg, to_account_id=bourso, date=TODAY, amount_cents=10_000
            ),
        )
    window.refresh(select_account_id=sg)
    window._register._view.selectRow(0)

    def confirm(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        assert "deux opérations" in box.text()
        click_button(box, "Supprimer")

    answer_next_dialog(confirm)
    window.act_delete_transaction.trigger()

    assert lines(window) == []
    select_account(window, bourso)
    assert lines(window) == []


def test_edit_and_delete_are_disabled_without_selection(
    window: MainWindow, factory: Factory
) -> None:
    make_account(factory, "SG")
    window.refresh()
    assert not window.act_edit_transaction.isEnabled()
    assert not window.act_delete_transaction.isEnabled()


# --- Catégories -----------------------------------------------------------------------------


def test_categories_dialog_add_rename_delete(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    dialog = CategoriesDialog(factory)

    def type_name(name: str):  # type: ignore[no-untyped-def]
        def fill(box: QDialog) -> None:
            assert isinstance(box, QInputDialog)
            box.setTextValue(name)
            box.accept()

        answer_next_dialog(fill)

    def top(index: int = 0):  # type: ignore[no-untyped-def]
        # L'arbre est reconstruit après chaque action : on relit toujours l'élément.
        return dialog._tree.topLevelItem(index)

    type_name("Logement")
    dialog._on_add_root()
    assert top().text(0) == "Logement"
    assert dialog._selected() is top()  # la nouvelle catégorie est sélectionnée

    type_name("Loyer")
    dialog._on_add_child()
    assert top().childCount() == 1 and top().child(0).text(0) == "Loyer"

    type_name("Charges")
    dialog._tree.setCurrentItem(top())
    dialog._on_rename()
    assert top().text(0) == "Charges"

    answer_next_dialog(lambda box: click_button(box, "Supprimer"))  # type: ignore[arg-type]
    dialog._tree.setCurrentItem(top().child(0))
    dialog._on_delete()
    assert top().childCount() == 0

    with factory() as session:
        assert [c.name for c in categories.list_root_categories(session)] == ["Charges"]


def test_categories_dialog_shows_business_errors(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        categories.create_category(session, "Logement")
    dialog = CategoriesDialog(factory)
    messages: list[str] = []

    def error_box(box: QDialog) -> None:
        assert isinstance(box, QMessageBox)
        messages.append(box.text())
        box.accept()

    def type_duplicate(box: QDialog) -> None:
        assert isinstance(box, QInputDialog)
        box.setTextValue("logement")
        answer_next_dialog(error_box)
        box.accept()

    answer_next_dialog(type_duplicate)
    dialog._on_add_root()

    assert len(messages) == 1 and "existe déjà" in messages[0]
    assert dialog._tree.topLevelItemCount() == 1


def test_categories_dialog_buttons_follow_selection(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        root = categories.create_category(session, "Auto")
        categories.create_category(session, "Assurance", parent_id=root.id)
    dialog = CategoriesDialog(factory)
    assert not dialog._rename.isEnabled()  # rien de sélectionné

    dialog._tree.setCurrentItem(dialog._tree.topLevelItem(0))
    assert dialog._add_child.isEnabled()

    dialog._tree.setCurrentItem(dialog._tree.topLevelItem(0).child(0))
    assert not dialog._add_child.isEnabled()  # pas de sous-sous-catégorie
    assert dialog._rename.isEnabled() and dialog._delete.isEnabled()
