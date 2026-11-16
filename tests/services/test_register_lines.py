import datetime as dt

from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.services import accounts, categories, lookups
from budget.services import transactions as tx
from budget.services.choices import load_choices
from budget.services.transactions import TransactionData, TransferData


def test_register_lines_hold_plain_values(session: Session, sg: Account, day: dt.date) -> None:
    logement = categories.create_category(session, "Logement")
    loyer = categories.create_category(session, "Loyer", parent_id=logement.id)
    payee = lookups.get_or_create_payee(session, "Agence")
    method = lookups.get_or_create_payment_method(session, "Prélèvement")
    tx.add_transaction(
        session,
        TransactionData(
            account_id=sg.id,
            date=day,
            amount_cents=-65_000,
            payee_id=payee.id,
            category_id=loyer.id,
            payment_method_id=method.id,
            notes="Mars",
        ),
    )

    (line,) = tx.register_lines(session, sg.id)

    assert line.payee_name == "Agence"
    assert line.category_name == "Logement : Loyer"
    assert line.category_id == loyer.id
    assert line.payment_method_name == "Prélèvement"
    assert line.notes == "Mars"
    assert line.amount_cents == -65_000
    assert line.balance_cents == 100_000 - 65_000
    assert not line.is_transfer
    assert line.transfer_account_name == ""


def test_register_lines_without_optional_fields(
    session: Session, sg: Account, day: dt.date
) -> None:
    tx.add_transaction(session, TransactionData(account_id=sg.id, date=day, amount_cents=500))
    (line,) = tx.register_lines(session, sg.id)
    assert (line.payee_name, line.category_name, line.payment_method_name) == ("", "", "")
    assert line.category_id is None and line.payment_method_id is None


def test_register_lines_show_the_other_account_of_a_transfer(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    tx.create_transfer(
        session,
        TransferData(from_account_id=sg.id, to_account_id=bourso.id, date=day, amount_cents=300),
    )

    (out_line,) = tx.register_lines(session, sg.id)
    (in_line,) = tx.register_lines(session, bourso.id)

    assert out_line.is_transfer and in_line.is_transfer
    assert out_line.transfer_account_id == bourso.id
    assert out_line.transfer_account_name == "Boursorama"
    assert in_line.transfer_account_id == sg.id
    assert in_line.transfer_account_name == "SG courant"


def test_load_choices(session: Session, sg: Account, bourso: Account) -> None:
    accounts.set_account_closed(session, bourso.id, closed=True)
    auto = categories.create_category(session, "Auto")
    categories.create_category(session, "Assurance", parent_id=auto.id)
    lookups.ensure_default_payment_methods(session)
    lookups.get_or_create_payee(session, "Carrefour")

    choices = load_choices(session)

    assert [c.label for c in choices.accounts] == ["SG courant"]  # clôturé exclu
    assert [c.label for c in choices.categories] == ["Auto", "Auto : Assurance"]
    assert "Carte" in [c.label for c in choices.payment_methods]
    assert choices.payee_names == ("Carrefour",)


def test_account_balance_exposes_closed_flag(
    session: Session, sg: Account, bourso: Account
) -> None:
    accounts.set_account_closed(session, bourso.id, closed=True)
    by_name = {b.name: b for b in accounts.account_balances(session, include_closed=True)}
    assert by_name["Boursorama"].closed is True
    assert by_name["SG courant"].closed is False
