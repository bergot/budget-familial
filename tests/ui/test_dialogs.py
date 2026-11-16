import datetime as dt

import pytest
from PySide6.QtWidgets import QDialog

from budget.services.choices import Choice, Choices
from budget.services.transactions import RegisterLine
from budget.ui.dialogs import account_dialog, transaction_dialog, transfer_dialog
from budget.ui.dialogs.account_dialog import AccountDialog, AccountInput
from budget.ui.dialogs.transaction_dialog import TransactionDialog
from budget.ui.dialogs.transfer_dialog import TransferDialog

CHOICES = Choices(
    accounts=(Choice(1, "SG"), Choice(2, "Boursorama"), Choice(3, "Livret A")),
    categories=(Choice(10, "Alimentation"), Choice(11, "Alimentation : Courses")),
    payment_methods=(Choice(20, "Carte"), Choice(21, "Virement")),
    payee_names=("Auchan", "Carrefour"),
)


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Remplace les boîtes d'erreur (bloquantes) par un simple enregistrement des messages."""
    messages: list[str] = []
    for module in (account_dialog, transaction_dialog, transfer_dialog):
        monkeypatch.setattr(
            module, "show_error", lambda _parent, error: messages.append(str(error))
        )
    return messages


def make_line(**overrides) -> RegisterLine:  # type: ignore[no-untyped-def]
    values = {
        "transaction_id": 5,
        "account_id": 2,
        "date": dt.date(2026, 2, 10),
        "amount_cents": -4250,
        "balance_cents": 0,
        "payee_name": "Carrefour",
        "category_id": 11,
        "category_name": "Alimentation : Courses",
        "payment_method_id": 20,
        "payment_method_name": "Carte",
        "notes": "semaine 6",
        "transfer_account_id": None,
        "transfer_account_name": "",
    }
    values.update(overrides)
    return RegisterLine(**values)  # type: ignore[arg-type]


# --- Opération ------------------------------------------------------------------------------


def test_new_transaction_defaults(qapp) -> None:  # type: ignore[no-untyped-def]
    today = dt.date(2026, 3, 15)
    dialog = TransactionDialog(CHOICES, account_id=2, today=today)
    assert dialog._account.currentData() == 2
    assert dialog._date.date().toPython() == today
    assert dialog._expense.isChecked()  # une dépense par défaut
    assert dialog._category.currentData() is None
    assert dialog._amount.text() == ""


def test_transaction_expense_becomes_negative(qapp, errors) -> None:  # type: ignore[no-untyped-def]
    dialog = TransactionDialog(CHOICES, account_id=1, today=dt.date(2026, 3, 15))
    dialog._payee.setCurrentText("  Nouveau tiers ")
    dialog._amount.setText("12,50")
    dialog._category.setCurrentIndex(dialog._category.findData(11))
    dialog._method.setCurrentIndex(dialog._method.findData(20))
    dialog._notes.setText(" test ")

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    values = dialog.values()
    assert values.amount_cents == -1250
    assert values.account_id == 1
    assert values.payee_name == "Nouveau tiers"
    assert values.category_id == 11
    assert values.payment_method_id == 20
    assert values.notes == "test"
    assert values.date == dt.date(2026, 3, 15)
    assert errors == []


def test_transaction_income_is_positive(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = TransactionDialog(CHOICES, account_id=1)
    dialog._income.setChecked(True)
    dialog._amount.setText("1 234,56")
    dialog.accept()
    assert dialog.values().amount_cents == 123_456


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "12,345"])
def test_transaction_invalid_amount_keeps_dialog_open(qapp, errors, text: str) -> None:  # type: ignore[no-untyped-def]
    dialog = TransactionDialog(CHOICES, account_id=1)
    dialog._amount.setText(text)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert len(errors) == 1


def test_transaction_without_open_account_is_refused(qapp, errors) -> None:  # type: ignore[no-untyped-def]
    empty = Choices(accounts=(), categories=(), payment_methods=(), payee_names=())
    dialog = TransactionDialog(empty)
    dialog._amount.setText("5")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "compte" in errors[0]


def test_edit_transaction_prefills_the_form(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = TransactionDialog(CHOICES, initial=make_line())
    assert dialog._account.currentData() == 2
    assert dialog._date.date().toPython() == dt.date(2026, 2, 10)
    assert dialog._payee.currentText() == "Carrefour"
    assert dialog._expense.isChecked()
    assert dialog._amount.text() == "42,50"  # valeur absolue : le sens est dans les boutons
    assert dialog._category.currentData() == 11
    assert dialog._method.currentData() == 20
    assert dialog._notes.text() == "semaine 6"

    dialog.accept()  # valider sans rien changer redonne les mêmes valeurs
    assert dialog.values().amount_cents == -4250


def test_edit_income_is_prefilled_as_income(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = TransactionDialog(CHOICES, initial=make_line(amount_cents=9900))
    assert dialog._income.isChecked()
    assert dialog._amount.text() == "99,00"


def test_values_before_validation_is_a_programming_error(qapp) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AssertionError):
        TransactionDialog(CHOICES).values()


# --- Virement -------------------------------------------------------------------------------


def test_new_transfer_proposes_two_different_accounts(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = TransferDialog(CHOICES, from_account_id=1)
    assert dialog._from.currentData() == 1
    assert dialog._to.currentData() != 1


def test_transfer_values(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = TransferDialog(CHOICES, from_account_id=1, today=dt.date(2026, 3, 1))
    dialog._to.setCurrentIndex(dialog._to.findData(2))
    dialog._amount.setText("300")
    dialog._notes.setText("mensuel")
    dialog.accept()
    data = dialog.values()
    assert (data.from_account_id, data.to_account_id) == (1, 2)
    assert data.amount_cents == 30_000
    assert data.date == dt.date(2026, 3, 1)
    assert data.notes == "mensuel"


def test_transfer_same_account_is_refused(qapp, errors) -> None:  # type: ignore[no-untyped-def]
    dialog = TransferDialog(CHOICES, from_account_id=1)
    dialog._to.setCurrentIndex(dialog._to.findData(1))
    dialog._amount.setText("10")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "différents" in errors[0]


def test_edit_transfer_from_outgoing_leg(qapp) -> None:  # type: ignore[no-untyped-def]
    line = make_line(account_id=1, amount_cents=-30_000, transfer_account_id=2)
    dialog = TransferDialog(CHOICES, initial=line)
    assert (dialog._from.currentData(), dialog._to.currentData()) == (1, 2)
    assert dialog._amount.text() == "300,00"


def test_edit_transfer_from_incoming_leg_gives_the_same_direction(qapp) -> None:  # type: ignore[no-untyped-def]
    line = make_line(account_id=2, amount_cents=30_000, transfer_account_id=1)
    dialog = TransferDialog(CHOICES, initial=line)
    assert (dialog._from.currentData(), dialog._to.currentData()) == (1, 2)


# --- Compte ---------------------------------------------------------------------------------


def test_account_dialog_values(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = AccountDialog()
    dialog._name.setText(" Livret A ")
    dialog._bank.setText("")
    dialog._balance.setText("1 250,00")
    dialog.accept()
    assert dialog.values() == AccountInput("Livret A", None, 125_000)


def test_account_dialog_accepts_negative_initial_balance(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = AccountDialog()
    dialog._name.setText("Découvert")
    dialog._balance.setText("-150")
    dialog.accept()
    assert dialog.values().initial_balance_cents == -15_000


def test_account_dialog_requires_a_name(qapp, errors) -> None:  # type: ignore[no-untyped-def]
    dialog = AccountDialog()
    dialog._name.setText("   ")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert len(errors) == 1


def test_account_dialog_rejects_bad_balance(qapp, errors) -> None:  # type: ignore[no-untyped-def]
    dialog = AccountDialog()
    dialog._name.setText("X")
    dialog._balance.setText("abc")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert len(errors) == 1


def test_account_dialog_prefill(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = AccountDialog(initial=AccountInput("SG", "Société Générale", 100_050))
    assert dialog._name.text() == "SG"
    assert dialog._bank.text() == "Société Générale"
    assert dialog._balance.text() == "1\u202f000,50"
    dialog.accept()
    assert dialog.values() == AccountInput("SG", "Société Générale", 100_050)
