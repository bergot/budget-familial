"""Opérations, virements et registre d'un compte.

Un **virement** est un couple de deux opérations, une par compte, qui se désignent
mutuellement via `transfer_peer_id` : -x sur le compte source, +x sur le compte
destination. Elles sont toujours créées, modifiées et supprimées ensemble.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from budget.db.models import Account, Category, Payee, PaymentMethod, Transaction
from budget.domain.errors import InvalidError
from budget.services._common import require


@dataclass(frozen=True, slots=True)
class TransactionData:
    """Contenu d'une opération ordinaire, tel que saisi dans le formulaire."""

    account_id: int
    date: dt.date
    amount_cents: int  # signé : < 0 dépense, > 0 recette
    payee_id: int | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class TransferData:
    """Contenu d'un virement."""

    from_account_id: int
    to_account_id: int
    date: dt.date
    amount_cents: int  # strictement positif
    payment_method_id: int | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RegisterRow:
    """Une ligne du registre : l'opération et le solde du compte juste après elle."""

    transaction: Transaction
    balance_cents: int


# --- Validation -----------------------------------------------------------------------


def _require_open_account(session: Session, account_id: int) -> Account:
    account = require(session, Account, account_id, "Compte")
    if account.closed:
        raise InvalidError(f"Le compte « {account.name} » est clôturé")
    return account


def _check_references(
    session: Session,
    *,
    payee_id: int | None,
    category_id: int | None,
    payment_method_id: int | None,
) -> None:
    if payee_id is not None:
        require(session, Payee, payee_id, "Tiers")
    if category_id is not None:
        require(session, Category, category_id, "Catégorie")
    if payment_method_id is not None:
        require(session, PaymentMethod, payment_method_id, "Moyen de paiement")


def _validate_transaction(session: Session, data: TransactionData) -> None:
    _require_open_account(session, data.account_id)
    if data.amount_cents == 0:
        raise InvalidError("Le montant ne peut pas être nul")
    _check_references(
        session,
        payee_id=data.payee_id,
        category_id=data.category_id,
        payment_method_id=data.payment_method_id,
    )


def _validate_transfer(session: Session, data: TransferData) -> None:
    if data.amount_cents <= 0:
        raise InvalidError("Le montant d'un virement doit être positif")
    if data.from_account_id == data.to_account_id:
        raise InvalidError("Un virement doit relier deux comptes différents")
    _require_open_account(session, data.from_account_id)
    _require_open_account(session, data.to_account_id)
    _check_references(
        session, payee_id=None, category_id=None, payment_method_id=data.payment_method_id
    )


# --- Opérations -----------------------------------------------------------------------


def get_transaction(session: Session, transaction_id: int) -> Transaction:
    return require(session, Transaction, transaction_id, "Opération")


def add_transaction(session: Session, data: TransactionData) -> Transaction:
    _validate_transaction(session, data)
    transaction = Transaction(
        account_id=data.account_id,
        date=data.date,
        amount_cents=data.amount_cents,
        payee_id=data.payee_id,
        category_id=data.category_id,
        payment_method_id=data.payment_method_id,
        notes=data.notes,
    )
    session.add(transaction)
    session.flush()
    return transaction


def update_transaction(session: Session, transaction_id: int, data: TransactionData) -> Transaction:
    transaction = get_transaction(session, transaction_id)
    if transaction.is_transfer:
        raise InvalidError("Cette opération fait partie d'un virement : utilisez update_transfer")
    _validate_transaction(session, data)
    transaction.account_id = data.account_id
    transaction.date = data.date
    transaction.amount_cents = data.amount_cents
    transaction.payee_id = data.payee_id
    transaction.category_id = data.category_id
    transaction.payment_method_id = data.payment_method_id
    transaction.notes = data.notes
    session.flush()
    session.refresh(transaction)  # recharge les relations (compte, tiers...) après changement d'id
    return transaction


def delete_transaction(session: Session, transaction_id: int) -> None:
    """Supprime une opération ; pour un virement, supprime les deux moitiés."""
    transaction = get_transaction(session, transaction_id)
    peer = (
        session.get(Transaction, transaction.transfer_peer_id)
        if transaction.transfer_peer_id is not None
        else None
    )
    session.delete(transaction)
    if peer is not None:
        session.delete(peer)
    session.flush()


# --- Virements ------------------------------------------------------------------------


def create_transfer(session: Session, data: TransferData) -> tuple[Transaction, Transaction]:
    """Crée un virement. Retourne (opération sortante, opération entrante)."""
    _validate_transfer(session, data)
    outgoing = Transaction(
        account_id=data.from_account_id,
        date=data.date,
        amount_cents=-data.amount_cents,
        payment_method_id=data.payment_method_id,
        notes=data.notes,
    )
    incoming = Transaction(
        account_id=data.to_account_id,
        date=data.date,
        amount_cents=data.amount_cents,
        payment_method_id=data.payment_method_id,
        notes=data.notes,
    )
    session.add_all([outgoing, incoming])
    session.flush()  # les deux opérations reçoivent leur identifiant...
    outgoing.transfer_peer_id = incoming.id  # ... ce qui permet de les lier
    incoming.transfer_peer_id = outgoing.id
    session.flush()
    return outgoing, incoming


def _transfer_legs(session: Session, transaction_id: int) -> tuple[Transaction, Transaction]:
    """À partir de l'une ou l'autre moitié, retourne (sortante, entrante)."""
    first = get_transaction(session, transaction_id)
    if first.transfer_peer_id is None:
        raise InvalidError("Cette opération n'est pas un virement")
    second = get_transaction(session, first.transfer_peer_id)
    return (first, second) if first.amount_cents < 0 else (second, first)


def update_transfer(
    session: Session, transaction_id: int, data: TransferData
) -> tuple[Transaction, Transaction]:
    """Modifie un virement (on peut passer l'une ou l'autre moitié)."""
    outgoing, incoming = _transfer_legs(session, transaction_id)
    _validate_transfer(session, data)
    outgoing.account_id = data.from_account_id
    incoming.account_id = data.to_account_id
    for leg, amount in ((outgoing, -data.amount_cents), (incoming, data.amount_cents)):
        leg.date = data.date
        leg.amount_cents = amount
        leg.payment_method_id = data.payment_method_id
        leg.notes = data.notes
    session.flush()
    session.refresh(outgoing)
    session.refresh(incoming)
    return outgoing, incoming


# --- Consultation ---------------------------------------------------------------------


def list_transactions(
    session: Session,
    account_id: int,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[Transaction]:
    """Opérations d'un compte, de la plus ancienne à la plus récente."""
    require(session, Account, account_id, "Compte")
    stmt = select(Transaction).where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    stmt = stmt.order_by(Transaction.date, Transaction.id)
    return list(session.scalars(stmt))


def register(session: Session, account_id: int) -> list[RegisterRow]:
    """Registre complet d'un compte, avec le solde cumulé après chaque opération."""
    account = require(session, Account, account_id, "Compte")
    balance = account.initial_balance_cents
    rows: list[RegisterRow] = []
    for transaction in list_transactions(session, account_id):
        balance += transaction.amount_cents
        rows.append(RegisterRow(transaction=transaction, balance_cents=balance))
    return rows
