"""Comptes et soldes.

Règle commune à tous les services : ils reçoivent une `Session`, font un `flush()`
(les changements sont envoyés à la base, mais pas validés) et **ne font jamais de
commit**. C'est l'appelant qui décide quand valider, avec `session.commit()` ou un
bloc `with session.begin():`. Plusieurs appels de services forment ainsi une seule
transaction : tout est validé, ou rien.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Account, Transaction
from budget.domain.errors import DuplicateError, InvalidError
from budget.services._common import clean_name, require


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Soldes d'un compte, prêts à afficher dans la liste des comptes."""

    account_id: int
    name: str
    current_cents: int  # opérations datées d'aujourd'hui ou avant
    forecast_cents: int  # toutes les opérations, y compris futures


def _name_taken(session: Session, name: str, *, except_id: int | None = None) -> bool:
    stmt = select(Account.id).where(func.lower(Account.name) == name.lower())
    if except_id is not None:
        stmt = stmt.where(Account.id != except_id)
    return session.scalar(stmt) is not None


def create_account(
    session: Session, name: str, *, bank: str | None = None, initial_balance_cents: int = 0
) -> Account:
    name = clean_name(name, "Compte")
    if _name_taken(session, name):
        raise DuplicateError(f"Un compte « {name} » existe déjà")
    account = Account(name=name, bank=bank, initial_balance_cents=initial_balance_cents)
    session.add(account)
    session.flush()  # attribue l'identifiant
    return account


def get_account(session: Session, account_id: int) -> Account:
    return require(session, Account, account_id, "Compte")


def list_accounts(session: Session, *, include_closed: bool = False) -> list[Account]:
    stmt = select(Account).order_by(Account.name)
    if not include_closed:
        stmt = stmt.where(Account.closed.is_(False))
    return list(session.scalars(stmt))


def update_account(
    session: Session,
    account_id: int,
    *,
    name: str,
    bank: str | None,
    initial_balance_cents: int,
) -> Account:
    account = get_account(session, account_id)
    name = clean_name(name, "Compte")
    if _name_taken(session, name, except_id=account_id):
        raise DuplicateError(f"Un compte « {name} » existe déjà")
    account.name = name
    account.bank = bank
    account.initial_balance_cents = initial_balance_cents
    session.flush()
    return account


def set_account_closed(session: Session, account_id: int, *, closed: bool) -> Account:
    """Clôture (ou rouvre) un compte. Un compte clôturé n'accepte plus d'opérations."""
    account = get_account(session, account_id)
    account.closed = closed
    session.flush()
    return account


def delete_account(session: Session, account_id: int) -> None:
    """Supprime un compte, seulement s'il n'a aucune opération (sinon, le clôturer)."""
    account = get_account(session, account_id)
    has_transactions = session.scalar(
        select(Transaction.id).where(Transaction.account_id == account_id).limit(1)
    )
    if has_transactions is not None:
        raise InvalidError(
            f"Le compte « {account.name} » contient des opérations : "
            "clôturez-le plutôt que de le supprimer"
        )
    session.delete(account)
    session.flush()


def _sum_amounts(session: Session, account_id: int, *, up_to: dt.date | None) -> int:
    stmt = select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.account_id == account_id
    )
    if up_to is not None:
        stmt = stmt.where(Transaction.date <= up_to)
    return int(session.scalar(stmt) or 0)


def current_balance(session: Session, account_id: int, *, today: dt.date | None = None) -> int:
    """Solde à la date `today` (par défaut aujourd'hui), en centimes.

    Le solde n'est jamais stocké : solde initial + somme des opérations.
    """
    account = get_account(session, account_id)
    today = today or dt.date.today()
    return account.initial_balance_cents + _sum_amounts(session, account_id, up_to=today)


def forecast_balance(session: Session, account_id: int) -> int:
    """Solde prévisionnel : toutes les opérations, y compris celles à venir."""
    account = get_account(session, account_id)
    return account.initial_balance_cents + _sum_amounts(session, account_id, up_to=None)


def account_balances(
    session: Session, *, today: dt.date | None = None, include_closed: bool = False
) -> list[AccountBalance]:
    """Soldes de tous les comptes, pour la liste des comptes de l'interface."""
    today = today or dt.date.today()
    return [
        AccountBalance(
            account_id=account.id,
            name=account.name,
            current_cents=account.initial_balance_cents
            + _sum_amounts(session, account.id, up_to=today),
            forecast_cents=account.initial_balance_cents
            + _sum_amounts(session, account.id, up_to=None),
        )
        for account in list_accounts(session, include_closed=include_closed)
    ]
