import datetime as dt

import pytest
from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.domain.errors import DuplicateError, InvalidError, NotFoundError
from budget.services import accounts
from budget.services.transactions import TransactionData, add_transaction


def test_create_account(session: Session) -> None:
    account = accounts.create_account(
        session, "  Livret   A ", bank="SG", initial_balance_cents=5000
    )
    assert account.id is not None
    assert account.name == "Livret A"  # espaces superflus retirés
    assert account.initial_balance_cents == 5000
    assert account.closed is False


def test_create_account_rejects_empty_name(session: Session) -> None:
    with pytest.raises(InvalidError):
        accounts.create_account(session, "   ")


def test_create_account_rejects_duplicate_name_ignoring_case(session: Session, sg: Account) -> None:
    with pytest.raises(DuplicateError):
        accounts.create_account(session, "sg COURANT")


def test_list_accounts_hides_closed_by_default(
    session: Session, sg: Account, bourso: Account
) -> None:
    accounts.set_account_closed(session, bourso.id, closed=True)
    assert [a.name for a in accounts.list_accounts(session)] == ["SG courant"]
    assert len(accounts.list_accounts(session, include_closed=True)) == 2


def test_list_accounts_is_sorted_by_name(session: Session) -> None:
    accounts.create_account(session, "Zèbre")
    accounts.create_account(session, "Abeille")
    assert [a.name for a in accounts.list_accounts(session)] == ["Abeille", "Zèbre"]


def test_update_account(session: Session, sg: Account) -> None:
    accounts.update_account(session, sg.id, name="SG joint", bank=None, initial_balance_cents=0)
    assert sg.name == "SG joint"
    assert sg.bank is None
    assert sg.initial_balance_cents == 0


def test_update_account_can_keep_its_own_name(session: Session, sg: Account) -> None:
    accounts.update_account(session, sg.id, name="SG courant", bank="X", initial_balance_cents=1)
    assert sg.bank == "X"


def test_update_account_rejects_name_of_another(
    session: Session, sg: Account, bourso: Account
) -> None:
    with pytest.raises(DuplicateError):
        accounts.update_account(
            session, bourso.id, name="SG courant", bank=None, initial_balance_cents=0
        )


def test_get_unknown_account(session: Session) -> None:
    with pytest.raises(NotFoundError):
        accounts.get_account(session, 12345)


def test_delete_empty_account(session: Session, sg: Account) -> None:
    accounts.delete_account(session, sg.id)
    assert accounts.list_accounts(session, include_closed=True) == []


def test_delete_account_with_transactions_is_refused(
    session: Session, sg: Account, day: dt.date
) -> None:
    add_transaction(session, TransactionData(account_id=sg.id, date=day, amount_cents=-100))
    with pytest.raises(InvalidError):
        accounts.delete_account(session, sg.id)
