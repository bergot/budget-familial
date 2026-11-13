import datetime as dt

from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.services import accounts
from budget.services.transactions import TransactionData, add_transaction

TODAY = dt.date(2026, 3, 15)


def _add(session: Session, account: Account, date: dt.date, cents: int) -> None:
    add_transaction(session, TransactionData(account_id=account.id, date=date, amount_cents=cents))


def test_balance_of_account_without_transactions_is_initial_balance(
    session: Session, sg: Account
) -> None:
    assert accounts.current_balance(session, sg.id, today=TODAY) == 100_000
    assert accounts.forecast_balance(session, sg.id) == 100_000


def test_current_balance_ignores_future_transactions(session: Session, sg: Account) -> None:
    _add(session, sg, dt.date(2026, 3, 1), -2_500)  # passé
    _add(session, sg, TODAY, -1_000)  # aujourd'hui : compte
    _add(session, sg, dt.date(2026, 3, 16), -50_000)  # futur : ne compte pas
    assert accounts.current_balance(session, sg.id, today=TODAY) == 100_000 - 2_500 - 1_000


def test_forecast_balance_includes_future_transactions(session: Session, sg: Account) -> None:
    _add(session, sg, dt.date(2026, 3, 1), -2_500)
    _add(session, sg, dt.date(2026, 12, 31), 20_000)
    assert accounts.forecast_balance(session, sg.id) == 100_000 - 2_500 + 20_000


def test_balances_do_not_mix_accounts(session: Session, sg: Account, bourso: Account) -> None:
    _add(session, sg, TODAY, -1_000)
    _add(session, bourso, TODAY, 400)
    assert accounts.current_balance(session, sg.id, today=TODAY) == 99_000
    assert accounts.current_balance(session, bourso.id, today=TODAY) == 400


def test_account_balances_summary(session: Session, sg: Account, bourso: Account) -> None:
    _add(session, sg, TODAY, -1_000)
    _add(session, sg, dt.date(2026, 4, 1), -2_000)
    _add(session, bourso, TODAY, 400)

    by_name = {b.name: b for b in accounts.account_balances(session, today=TODAY)}

    assert by_name["SG courant"].current_cents == 99_000
    assert by_name["SG courant"].forecast_cents == 97_000
    assert by_name["Boursorama"].current_cents == 400
    assert by_name["Boursorama"].forecast_cents == 400


def test_account_balances_hides_closed_accounts(
    session: Session, sg: Account, bourso: Account
) -> None:
    accounts.set_account_closed(session, bourso.id, closed=True)
    names = [b.name for b in accounts.account_balances(session, today=TODAY)]
    assert names == ["SG courant"]
