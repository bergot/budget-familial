import datetime as dt

import pytest
from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.domain.enums import ReconciliationStatus as Status
from budget.domain.errors import InvalidError, NotFoundError
from budget.services import accounts
from budget.services import reconciliation as rec
from budget.services import transactions as tx
from budget.services.transactions import TransactionData, TransferData


def add(session: Session, account: Account, day: int, cents: int, month: int = 3) -> int:
    """Ajoute une opération le `day` du mois et retourne son identifiant."""
    return tx.add_transaction(
        session,
        TransactionData(account_id=account.id, date=dt.date(2026, month, day), amount_cents=cents),
    ).id


def status_of(session: Session, transaction_id: int) -> Status:
    return tx.get_transaction(session, transaction_id).status


@pytest.fixture
def three_ops(session: Session, sg: Account) -> tuple[int, int, int]:
    """SG (solde initial 1 000,00 €) avec -20,00 / -30,00 / +50,00."""
    return add(session, sg, 1, -2_000), add(session, sg, 2, -3_000), add(session, sg, 3, 5_000)


# --- État et écart --------------------------------------------------------------------------


def test_new_account_state(session: Session, sg: Account) -> None:
    state = rec.reconciliation_state(session, sg.id)
    assert state == rec.ReconciliationState(100_000, 0, 0)
    assert state.gap_cents(100_000) == 0
    assert state.gap_cents(98_000) == -2_000  # le relevé est plus bas que ce qu'on a pointé


def test_gap_arithmetic() -> None:
    state = rec.ReconciliationState(
        reconciled_balance_cents=100_000, pointed_total_cents=-5_000, pointed_count=2
    )
    assert state.gap_cents(95_000) == 0
    assert state.gap_cents(94_000) == -1_000
    assert state.gap_cents(96_500) == 1_500


def test_pointing_updates_the_state(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, _c = three_ops
    rec.set_pointed(session, a, pointed=True)
    rec.set_pointed(session, b, pointed=True)

    state = rec.reconciliation_state(session, sg.id)
    assert state.pointed_total_cents == -5_000
    assert state.pointed_count == 2
    assert state.reconciled_balance_cents == 100_000  # rien de rapproché encore

    rec.set_pointed(session, b, pointed=False)
    state = rec.reconciliation_state(session, sg.id)
    assert (state.pointed_total_cents, state.pointed_count) == (-2_000, 1)
    assert status_of(session, b) is Status.NONE


def test_pointing_is_per_account(
    session: Session, sg: Account, bourso: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)
    assert rec.reconciliation_state(session, bourso.id).pointed_count == 0


def test_cannot_point_unknown_or_reconciled_transaction(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    with pytest.raises(NotFoundError):
        rec.set_pointed(session, 9999, pointed=True)

    rec.set_pointed(session, three_ops[0], pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=98_000
    )
    with pytest.raises(InvalidError):
        rec.set_pointed(session, three_ops[0], pointed=False)


def test_clear_pointing(session: Session, sg: Account, three_ops: tuple[int, int, int]) -> None:
    for transaction_id in three_ops[:2]:
        rec.set_pointed(session, transaction_id, pointed=True)
    assert rec.clear_pointing(session, sg.id) == 2
    assert rec.reconciliation_state(session, sg.id).pointed_count == 0
    assert rec.clear_pointing(session, sg.id) == 0


# --- Validation -----------------------------------------------------------------------------


def test_complete_reconciliation_freezes_pointed_transactions(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, c = three_ops
    # Le relevé du 31 mars : 1 000 - 20 + 50 = 1 030 ; le -30 n'y figure pas encore.
    rec.set_pointed(session, a, pointed=True)
    rec.set_pointed(session, c, pointed=True)

    summary = rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=103_000
    )

    assert summary.statement_balance_cents == 103_000
    assert summary.transaction_count == 2
    assert status_of(session, a) is Status.RECONCILED
    assert status_of(session, c) is Status.RECONCILED
    assert status_of(session, b) is Status.NONE  # reste à rapprocher au prochain relevé
    assert tx.get_transaction(session, a).reconciliation_id == summary.id

    state = rec.reconciliation_state(session, sg.id)
    assert state.reconciled_balance_cents == 103_000  # = le solde du relevé
    assert state.pointed_count == 0


def test_second_reconciliation_continues_from_the_first(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, c = three_ops
    rec.set_pointed(session, a, pointed=True)
    rec.set_pointed(session, c, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=103_000
    )
    d = add(session, sg, 5, -1_000, month=4)

    # Relevé suivant : 1 030 - 30 - 10 = 990.
    rec.set_pointed(session, b, pointed=True)
    rec.set_pointed(session, d, pointed=True)
    assert rec.reconciliation_state(session, sg.id).gap_cents(99_000) == 0

    second = rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 4, 30), statement_balance_cents=99_000
    )
    assert second.transaction_count == 2
    assert rec.reconciliation_state(session, sg.id).reconciled_balance_cents == 99_000


def test_gap_blocks_validation_and_changes_nothing(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)

    with pytest.raises(InvalidError, match="Écart de"):
        rec.complete_reconciliation(
            session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=105_000
        )

    assert status_of(session, three_ops[0]) is Status.POINTED  # toujours pointée, pas figée
    assert rec.last_reconciliation(session, sg.id) is None


def test_gap_message_shows_the_amount(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)  # solde pointé : 980,00
    with pytest.raises(InvalidError) as error:
        rec.complete_reconciliation(
            session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=98_250
        )
    assert "2,50" in str(error.value)


def test_nothing_pointed_cannot_be_validated(session: Session, sg: Account) -> None:
    with pytest.raises(InvalidError, match="Aucune opération pointée"):
        rec.complete_reconciliation(
            session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=100_000
        )


def test_statement_date_cannot_go_backwards(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=98_000
    )
    rec.set_pointed(session, three_ops[1], pointed=True)
    with pytest.raises(InvalidError, match="31/03/2026"):
        rec.complete_reconciliation(
            session, sg.id, statement_date=dt.date(2026, 3, 15), statement_balance_cents=95_000
        )


def test_each_account_is_reconciled_on_its_own(
    session: Session, sg: Account, bourso: Account, three_ops: tuple[int, int, int]
) -> None:
    other = add(session, bourso, 4, 700)
    rec.set_pointed(session, three_ops[0], pointed=True)
    rec.set_pointed(session, other, pointed=True)

    rec.complete_reconciliation(
        session, bourso.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=700
    )

    assert status_of(session, other) is Status.RECONCILED
    assert status_of(session, three_ops[0]) is Status.POINTED  # l'autre compte n'est pas touché


# --- Historique et annulation ---------------------------------------------------------------


def test_history_is_newest_first(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, _c = three_ops
    assert rec.last_reconciliation(session, sg.id) is None
    assert rec.list_reconciliations(session, sg.id) == []

    rec.set_pointed(session, a, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 10), statement_balance_cents=98_000
    )
    rec.set_pointed(session, b, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=95_000
    )

    history = rec.list_reconciliations(session, sg.id)
    assert [h.statement_date for h in history] == [dt.date(2026, 3, 31), dt.date(2026, 3, 10)]
    assert rec.last_reconciliation(session, sg.id) == history[0]


def test_undo_last_reconciliation(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, _c = three_ops
    rec.set_pointed(session, a, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 10), statement_balance_cents=98_000
    )
    rec.set_pointed(session, b, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=95_000
    )

    undone = rec.undo_last_reconciliation(session, sg.id)

    assert undone.statement_date == dt.date(2026, 3, 31)
    assert undone.transaction_count == 1
    assert status_of(session, b) is Status.NONE
    assert tx.get_transaction(session, b).reconciliation_id is None
    assert status_of(session, a) is Status.RECONCILED  # le premier rapprochement est intact
    assert rec.last_reconciliation(session, sg.id).statement_date == dt.date(2026, 3, 10)  # type: ignore[union-attr]
    assert rec.reconciliation_state(session, sg.id).reconciled_balance_cents == 98_000


def test_undo_without_reconciliation_is_refused(session: Session, sg: Account) -> None:
    with pytest.raises(InvalidError):
        rec.undo_last_reconciliation(session, sg.id)


# --- Opérations figées ----------------------------------------------------------------------


@pytest.fixture
def reconciled_op(session: Session, sg: Account) -> int:
    transaction_id = add(session, sg, 1, -2_000)
    rec.set_pointed(session, transaction_id, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=98_000
    )
    return transaction_id


def test_reconciled_transaction_cannot_be_edited_or_deleted(
    session: Session, sg: Account, reconciled_op: int
) -> None:
    data = TransactionData(account_id=sg.id, date=dt.date(2026, 3, 1), amount_cents=-9_999)
    with pytest.raises(InvalidError, match="rapprochée"):
        tx.update_transaction(session, reconciled_op, data)
    with pytest.raises(InvalidError, match="rapprochée"):
        tx.delete_transaction(session, reconciled_op)
    assert tx.get_transaction(session, reconciled_op).amount_cents == -2_000


def test_undoing_the_reconciliation_makes_it_editable_again(
    session: Session, sg: Account, reconciled_op: int
) -> None:
    rec.undo_last_reconciliation(session, sg.id)
    data = TransactionData(account_id=sg.id, date=dt.date(2026, 3, 1), amount_cents=-2_500)
    tx.update_transaction(session, reconciled_op, data)
    assert tx.get_transaction(session, reconciled_op).amount_cents == -2_500


def test_pointed_transaction_stays_editable_and_pointed(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)
    data = TransactionData(account_id=sg.id, date=dt.date(2026, 3, 1), amount_cents=-2_100)
    tx.update_transaction(session, three_ops[0], data)
    assert status_of(session, three_ops[0]) is Status.POINTED
    assert rec.reconciliation_state(session, sg.id).pointed_total_cents == -2_100


def test_moving_a_pointed_transaction_to_another_account_resets_the_pointing(
    session: Session, sg: Account, bourso: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[0], pointed=True)
    data = TransactionData(account_id=bourso.id, date=dt.date(2026, 3, 1), amount_cents=-2_000)
    tx.update_transaction(session, three_ops[0], data)
    assert status_of(session, three_ops[0]) is Status.NONE


def test_transfer_with_a_reconciled_leg_is_frozen(
    session: Session, sg: Account, bourso: Account
) -> None:
    day = dt.date(2026, 3, 5)
    outgoing, incoming = tx.create_transfer(
        session,
        TransferData(from_account_id=sg.id, to_account_id=bourso.id, date=day, amount_cents=500),
    )
    # Seule la moitié du compte Boursorama est rapprochée.
    rec.set_pointed(session, incoming.id, pointed=True)
    rec.complete_reconciliation(
        session, bourso.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=500
    )

    new_data = TransferData(
        from_account_id=sg.id, to_account_id=bourso.id, date=day, amount_cents=900
    )
    with pytest.raises(InvalidError, match="rapprochée"):
        tx.update_transfer(session, outgoing.id, new_data)  # via la moitié non rapprochée
    with pytest.raises(InvalidError, match="rapprochée"):
        tx.delete_transaction(session, outgoing.id)
    assert accounts.forecast_balance(session, sg.id) == 100_000 - 500  # rien n'a bougé


def test_transfer_legs_are_pointed_independently(
    session: Session, sg: Account, bourso: Account
) -> None:
    outgoing, incoming = tx.create_transfer(
        session,
        TransferData(
            from_account_id=sg.id,
            to_account_id=bourso.id,
            date=dt.date(2026, 3, 5),
            amount_cents=500,
        ),
    )
    rec.set_pointed(session, outgoing.id, pointed=True)
    assert status_of(session, incoming.id) is Status.NONE


# --- Listes pour l'interface ----------------------------------------------------------------


def test_pointable_lines_exclude_reconciled(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    a, b, c = three_ops
    rec.set_pointed(session, a, pointed=True)
    rec.complete_reconciliation(
        session, sg.id, statement_date=dt.date(2026, 3, 31), statement_balance_cents=98_000
    )
    rec.set_pointed(session, b, pointed=True)

    lines = rec.pointable_lines(session, sg.id)

    assert [line.transaction_id for line in lines] == [b, c]
    assert [line.status for line in lines] == [Status.POINTED, Status.NONE]


def test_register_lines_expose_the_status(
    session: Session, sg: Account, three_ops: tuple[int, int, int]
) -> None:
    rec.set_pointed(session, three_ops[1], pointed=True)
    statuses = [line.status for line in tx.register_lines(session, sg.id)]
    assert statuses == [Status.NONE, Status.POINTED, Status.NONE]
