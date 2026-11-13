import datetime as dt

import pytest
from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.domain.errors import InvalidError, NotFoundError
from budget.services import accounts, lookups
from budget.services import transactions as tx
from budget.services.transactions import TransactionData, TransferData


def _transfer(sg: Account, bourso: Account, day: dt.date, cents: int = 30_000) -> TransferData:
    return TransferData(
        from_account_id=sg.id, to_account_id=bourso.id, date=day, amount_cents=cents
    )


def test_create_transfer_makes_two_linked_opposite_transactions(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    method = lookups.get_or_create_payment_method(session, "Virement")
    data = TransferData(
        from_account_id=sg.id,
        to_account_id=bourso.id,
        date=day,
        amount_cents=30_000,
        payment_method_id=method.id,
        notes="Alimentation mensuelle",
    )

    outgoing, incoming = tx.create_transfer(session, data)

    assert outgoing.account is sg
    assert incoming.account is bourso
    assert outgoing.amount_cents == -30_000
    assert incoming.amount_cents == 30_000
    assert outgoing.transfer_peer_id == incoming.id
    assert incoming.transfer_peer_id == outgoing.id
    assert outgoing.is_transfer and incoming.is_transfer
    assert outgoing.payment_method is method
    assert incoming.notes == "Alimentation mensuelle"
    assert outgoing.category is None and outgoing.payee is None


def test_transfer_moves_money_between_balances(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    tx.create_transfer(session, _transfer(sg, bourso, day))

    assert accounts.current_balance(session, sg.id, today=day) == 100_000 - 30_000
    assert accounts.current_balance(session, bourso.id, today=day) == 30_000
    # La somme des soldes est inchangée : l'argent n'a fait que changer de compte.
    total = accounts.forecast_balance(session, sg.id) + accounts.forecast_balance(
        session, bourso.id
    )
    assert total == 100_000


@pytest.mark.parametrize("cents", [0, -100])
def test_transfer_amount_must_be_positive(
    session: Session, sg: Account, bourso: Account, day: dt.date, cents: int
) -> None:
    with pytest.raises(InvalidError):
        tx.create_transfer(session, _transfer(sg, bourso, day, cents))


def test_transfer_needs_two_different_accounts(session: Session, sg: Account, day: dt.date) -> None:
    with pytest.raises(InvalidError):
        tx.create_transfer(session, _transfer(sg, sg, day))


def test_transfer_with_unknown_account(session: Session, sg: Account, day: dt.date) -> None:
    data = TransferData(from_account_id=sg.id, to_account_id=999, date=day, amount_cents=100)
    with pytest.raises(NotFoundError):
        tx.create_transfer(session, data)


def test_transfer_to_closed_account_is_refused(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    accounts.set_account_closed(session, bourso.id, closed=True)
    with pytest.raises(InvalidError):
        tx.create_transfer(session, _transfer(sg, bourso, day))


def test_failed_transfer_creates_nothing(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    with pytest.raises(InvalidError):
        tx.create_transfer(session, _transfer(sg, bourso, day, cents=-1))
    assert tx.list_transactions(session, sg.id) == []
    assert tx.list_transactions(session, bourso.id) == []


def test_update_transfer_from_either_leg(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    outgoing, incoming = tx.create_transfer(session, _transfer(sg, bourso, day))
    new_day = day + dt.timedelta(days=1)

    # On modifie en passant la moitié *entrante* : les deux changent.
    tx.update_transfer(session, incoming.id, _transfer(sg, bourso, new_day, 45_000))

    assert outgoing.amount_cents == -45_000
    assert incoming.amount_cents == 45_000
    assert outgoing.date == incoming.date == new_day


def test_update_transfer_can_change_accounts(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    livret = accounts.create_account(session, "Livret A")
    outgoing, incoming = tx.create_transfer(session, _transfer(sg, bourso, day))

    tx.update_transfer(
        session,
        outgoing.id,
        TransferData(from_account_id=sg.id, to_account_id=livret.id, date=day, amount_cents=30_000),
    )

    assert incoming.account is livret
    assert tx.list_transactions(session, bourso.id) == []


def test_update_transaction_refuses_transfer_legs(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    outgoing, _ = tx.create_transfer(session, _transfer(sg, bourso, day))
    with pytest.raises(InvalidError):
        tx.update_transaction(
            session, outgoing.id, TransactionData(account_id=sg.id, date=day, amount_cents=-1)
        )


def test_update_transfer_refuses_ordinary_transaction(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    ordinary = tx.add_transaction(
        session, TransactionData(account_id=sg.id, date=day, amount_cents=-100)
    )
    with pytest.raises(InvalidError):
        tx.update_transfer(session, ordinary.id, _transfer(sg, bourso, day))


def test_delete_transfer_removes_both_legs(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    outgoing, _incoming = tx.create_transfer(session, _transfer(sg, bourso, day))

    tx.delete_transaction(session, outgoing.id)

    assert tx.list_transactions(session, sg.id) == []
    assert tx.list_transactions(session, bourso.id) == []
    assert accounts.forecast_balance(session, bourso.id) == 0


def test_delete_transfer_from_incoming_leg(
    session: Session, sg: Account, bourso: Account, day: dt.date
) -> None:
    _outgoing, incoming = tx.create_transfer(session, _transfer(sg, bourso, day))
    tx.delete_transaction(session, incoming.id)
    assert tx.list_transactions(session, sg.id) == []
