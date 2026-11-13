import datetime as dt

import pytest
from sqlalchemy.orm import Session

from budget.db.models import Account, Transaction
from budget.domain.errors import InvalidError, NotFoundError
from budget.services import accounts, categories, lookups
from budget.services import transactions as tx
from budget.services.transactions import TransactionData


def test_add_transaction_with_all_fields(session: Session, sg: Account, day: dt.date) -> None:
    payee = lookups.get_or_create_payee(session, "Carrefour")
    category = categories.create_category(session, "Courses")
    method = lookups.get_or_create_payment_method(session, "Carte")

    created = tx.add_transaction(
        session,
        TransactionData(
            account_id=sg.id,
            date=day,
            amount_cents=-4_250,
            payee_id=payee.id,
            category_id=category.id,
            payment_method_id=method.id,
            notes="Courses de la semaine",
        ),
    )

    assert created.id is not None
    assert created.account is sg
    assert created.payee is payee
    assert created.category is category
    assert created.payment_method is method
    assert created.amount_cents == -4_250
    assert created.notes == "Courses de la semaine"
    assert not created.is_transfer


def test_add_transaction_with_only_required_fields(
    session: Session, sg: Account, day: dt.date
) -> None:
    created = tx.add_transaction(
        session, TransactionData(account_id=sg.id, date=day, amount_cents=1_000)
    )
    assert created.payee is None
    assert created.category is None
    assert created.payment_method is None
    assert created.notes == ""


def test_zero_amount_is_refused(session: Session, sg: Account, day: dt.date) -> None:
    with pytest.raises(InvalidError):
        tx.add_transaction(session, TransactionData(account_id=sg.id, date=day, amount_cents=0))


def test_unknown_account_is_refused(session: Session, day: dt.date) -> None:
    with pytest.raises(NotFoundError):
        tx.add_transaction(session, TransactionData(account_id=999, date=day, amount_cents=100))


@pytest.mark.parametrize("field", ["payee_id", "category_id", "payment_method_id"])
def test_unknown_reference_is_refused(
    session: Session, sg: Account, day: dt.date, field: str
) -> None:
    data = TransactionData(account_id=sg.id, date=day, amount_cents=100, **{field: 999})
    with pytest.raises(NotFoundError):
        tx.add_transaction(session, data)


def test_closed_account_refuses_transactions(session: Session, sg: Account, day: dt.date) -> None:
    accounts.set_account_closed(session, sg.id, closed=True)
    with pytest.raises(InvalidError):
        tx.add_transaction(session, TransactionData(account_id=sg.id, date=day, amount_cents=100))


def test_update_transaction(session: Session, sg: Account, bourso: Account, day: dt.date) -> None:
    created = tx.add_transaction(
        session, TransactionData(account_id=sg.id, date=day, amount_cents=-100)
    )
    new_day = day + dt.timedelta(days=3)

    tx.update_transaction(
        session,
        created.id,
        TransactionData(account_id=bourso.id, date=new_day, amount_cents=-250, notes="corrigé"),
    )

    assert created.account is bourso
    assert created.date == new_day
    assert created.amount_cents == -250
    assert created.notes == "corrigé"


def test_update_unknown_transaction(session: Session, sg: Account, day: dt.date) -> None:
    with pytest.raises(NotFoundError):
        tx.update_transaction(
            session, 999, TransactionData(account_id=sg.id, date=day, amount_cents=100)
        )


def test_delete_transaction(session: Session, sg: Account, day: dt.date) -> None:
    created = tx.add_transaction(
        session, TransactionData(account_id=sg.id, date=day, amount_cents=-100)
    )
    tx.delete_transaction(session, created.id)
    assert tx.list_transactions(session, sg.id) == []
    assert accounts.forecast_balance(session, sg.id) == sg.initial_balance_cents


def test_list_transactions_is_chronological_and_filtered(
    session: Session, sg: Account, bourso: Account
) -> None:
    def add(account: Account, date: dt.date, cents: int) -> Transaction:
        return tx.add_transaction(
            session, TransactionData(account_id=account.id, date=date, amount_cents=cents)
        )

    late = add(sg, dt.date(2026, 3, 20), -3)
    early = add(sg, dt.date(2026, 3, 1), -1)
    middle = add(sg, dt.date(2026, 3, 10), -2)
    add(bourso, dt.date(2026, 3, 5), -9)  # autre compte : jamais listé

    assert tx.list_transactions(session, sg.id) == [early, middle, late]
    assert tx.list_transactions(session, sg.id, date_from=dt.date(2026, 3, 10)) == [middle, late]
    assert tx.list_transactions(session, sg.id, date_to=dt.date(2026, 3, 10)) == [early, middle]


def test_same_day_transactions_keep_entry_order(
    session: Session, sg: Account, day: dt.date
) -> None:
    first = tx.add_transaction(session, TransactionData(account_id=sg.id, date=day, amount_cents=1))
    second = tx.add_transaction(
        session, TransactionData(account_id=sg.id, date=day, amount_cents=2)
    )
    assert tx.list_transactions(session, sg.id) == [first, second]


def test_register_has_running_balance(session: Session, sg: Account) -> None:
    for date, cents in [
        (dt.date(2026, 3, 1), -2_000),
        (dt.date(2026, 3, 2), 5_000),
        (dt.date(2026, 3, 3), -1_500),
    ]:
        tx.add_transaction(
            session, TransactionData(account_id=sg.id, date=date, amount_cents=cents)
        )

    rows = tx.register(session, sg.id)

    assert [r.balance_cents for r in rows] == [98_000, 103_000, 101_500]
    assert rows[-1].balance_cents == accounts.forecast_balance(session, sg.id)


def test_register_of_empty_account_is_empty(session: Session, sg: Account) -> None:
    assert tx.register(session, sg.id) == []
