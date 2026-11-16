"""Rapprochement bancaire : confronter le registre au relevé de la banque.

Déroulement :
1. La banque envoie un relevé : une date et un solde final.
2. L'utilisateur **pointe** les opérations du registre qui figurent sur le relevé
   (statut `NONE` -> `POINTED`). Le pointage est enregistré aussitôt : on peut fermer
   l'application et reprendre plus tard.
3. L'**écart** mesure ce qui manque :
       écart = solde du relevé - (solde rapproché + total des opérations pointées)
   où « solde rapproché » = solde initial + opérations déjà rapprochées.
4. Quand l'écart est nul, on **valide** : les opérations pointées deviennent `RECONCILED`,
   rattachées à un enregistrement `Reconciliation`, et ne sont plus modifiables.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Account, Reconciliation, Transaction
from budget.domain.enums import ReconciliationStatus
from budget.domain.errors import InvalidError
from budget.domain.money import format_cents
from budget.services._common import require
from budget.services.transactions import RegisterLine, get_transaction, register_lines


@dataclass(frozen=True, slots=True)
class ReconciliationState:
    """Où en est le rapprochement d'un compte."""

    reconciled_balance_cents: int  # solde initial + opérations déjà rapprochées
    pointed_total_cents: int  # somme (signée) des opérations pointées
    pointed_count: int

    def gap_cents(self, statement_balance_cents: int) -> int:
        """Écart entre le relevé et ce qui est pointé : zéro = prêt à valider."""
        return statement_balance_cents - (self.reconciled_balance_cents + self.pointed_total_cents)


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    id: int
    account_id: int
    statement_date: dt.date
    statement_balance_cents: int
    transaction_count: int


def _sum_and_count(
    session: Session, account_id: int, status: ReconciliationStatus
) -> tuple[int, int]:
    row = session.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0), func.count(Transaction.id))
        .where(Transaction.account_id == account_id)
        .where(Transaction.status == status)
    ).one()
    return int(row[0]), int(row[1])


def reconciliation_state(session: Session, account_id: int) -> ReconciliationState:
    account = require(session, Account, account_id, "Compte")
    reconciled_sum, _ = _sum_and_count(session, account_id, ReconciliationStatus.RECONCILED)
    pointed_sum, pointed_count = _sum_and_count(session, account_id, ReconciliationStatus.POINTED)
    return ReconciliationState(
        reconciled_balance_cents=account.initial_balance_cents + reconciled_sum,
        pointed_total_cents=pointed_sum,
        pointed_count=pointed_count,
    )


def pointable_lines(session: Session, account_id: int) -> list[RegisterLine]:
    """Opérations pas encore rapprochées (donc pointables), par date."""
    return [
        line
        for line in register_lines(session, account_id)
        if line.status is not ReconciliationStatus.RECONCILED
    ]


def set_pointed(session: Session, transaction_id: int, *, pointed: bool) -> None:
    """Pointe ou dépointe une opération."""
    transaction = get_transaction(session, transaction_id)
    if transaction.status is ReconciliationStatus.RECONCILED:
        raise InvalidError("Cette opération est déjà rapprochée")
    transaction.status = ReconciliationStatus.POINTED if pointed else ReconciliationStatus.NONE
    session.flush()


def clear_pointing(session: Session, account_id: int) -> int:
    """Dépointe toutes les opérations pointées du compte. Retourne leur nombre."""
    require(session, Account, account_id, "Compte")
    pointed = session.scalars(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.status == ReconciliationStatus.POINTED)
    ).all()
    for transaction in pointed:
        transaction.status = ReconciliationStatus.NONE
    session.flush()
    return len(pointed)


def _summary(session: Session, reconciliation: Reconciliation) -> ReconciliationSummary:
    count = session.scalar(
        select(func.count(Transaction.id)).where(Transaction.reconciliation_id == reconciliation.id)
    )
    return ReconciliationSummary(
        id=reconciliation.id,
        account_id=reconciliation.account_id,
        statement_date=reconciliation.statement_date,
        statement_balance_cents=reconciliation.statement_balance_cents,
        transaction_count=int(count or 0),
    )


def _latest(session: Session, account_id: int) -> Reconciliation | None:
    return session.scalars(
        select(Reconciliation)
        .where(Reconciliation.account_id == account_id)
        .order_by(Reconciliation.statement_date.desc(), Reconciliation.id.desc())
        .limit(1)
    ).first()


def last_reconciliation(session: Session, account_id: int) -> ReconciliationSummary | None:
    latest = _latest(session, account_id)
    return _summary(session, latest) if latest else None


def list_reconciliations(session: Session, account_id: int) -> list[ReconciliationSummary]:
    """Historique des rapprochements du compte, du plus récent au plus ancien."""
    require(session, Account, account_id, "Compte")
    rows = session.scalars(
        select(Reconciliation)
        .where(Reconciliation.account_id == account_id)
        .order_by(Reconciliation.statement_date.desc(), Reconciliation.id.desc())
    )
    return [_summary(session, row) for row in rows]


def complete_reconciliation(
    session: Session,
    account_id: int,
    *,
    statement_date: dt.date,
    statement_balance_cents: int,
) -> ReconciliationSummary:
    """Valide le rapprochement : fige les opérations pointées. Exige un écart nul."""
    state = reconciliation_state(session, account_id)
    if state.pointed_count == 0:
        raise InvalidError("Aucune opération pointée : il n'y a rien à rapprocher")

    gap = state.gap_cents(statement_balance_cents)
    if gap != 0:
        raise InvalidError(
            f"Écart de {format_cents(gap)} : le solde pointé ne correspond pas au relevé"
        )

    previous = _latest(session, account_id)
    if previous is not None and statement_date < previous.statement_date:
        raise InvalidError(
            "La date du relevé ne peut pas précéder celle du dernier rapprochement "
            f"({previous.statement_date.strftime('%d/%m/%Y')})"
        )

    reconciliation = Reconciliation(
        account_id=account_id,
        statement_date=statement_date,
        statement_balance_cents=statement_balance_cents,
    )
    session.add(reconciliation)
    session.flush()  # attribue l'identifiant

    pointed = session.scalars(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .where(Transaction.status == ReconciliationStatus.POINTED)
    )
    for transaction in pointed:
        transaction.status = ReconciliationStatus.RECONCILED
        transaction.reconciliation_id = reconciliation.id
    session.flush()
    return _summary(session, reconciliation)


def undo_last_reconciliation(session: Session, account_id: int) -> ReconciliationSummary:
    """Annule le dernier rapprochement du compte : ses opérations redeviennent non pointées.

    Seul le dernier peut être annulé : les soldes rapprochés se suivent en chaîne.
    """
    latest = _latest(session, account_id)
    if latest is None:
        raise InvalidError("Ce compte n'a aucun rapprochement à annuler")
    summary = _summary(session, latest)

    transactions = session.scalars(
        select(Transaction).where(Transaction.reconciliation_id == latest.id)
    )
    for transaction in transactions:
        transaction.status = ReconciliationStatus.NONE
        transaction.reconciliation_id = None
    session.flush()  # les lignes ne pointent plus vers le rapprochement : on peut le supprimer
    session.delete(latest)
    session.flush()
    return summary
