"""Tiers et moyens de paiement : de simples listes de noms."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Payee, PaymentMethod
from budget.services._common import clean_name

DEFAULT_PAYMENT_METHODS = ("Carte", "Virement", "Prélèvement", "Chèque", "Espèces")


def get_or_create_payee(session: Session, name: str) -> Payee:
    """Retourne le tiers de ce nom (sans tenir compte de la casse), en le créant au besoin."""
    name = clean_name(name, "Tiers")
    existing = session.scalar(select(Payee).where(func.lower(Payee.name) == name.lower()))
    if existing is not None:
        return existing
    payee = Payee(name=name)
    session.add(payee)
    session.flush()
    return payee


def list_payees(session: Session) -> list[Payee]:
    return list(session.scalars(select(Payee).order_by(Payee.name)))


def get_or_create_payment_method(session: Session, name: str) -> PaymentMethod:
    name = clean_name(name, "Moyen de paiement")
    existing = session.scalar(
        select(PaymentMethod).where(func.lower(PaymentMethod.name) == name.lower())
    )
    if existing is not None:
        return existing
    method = PaymentMethod(name=name)
    session.add(method)
    session.flush()
    return method


def list_payment_methods(session: Session) -> list[PaymentMethod]:
    return list(session.scalars(select(PaymentMethod).order_by(PaymentMethod.name)))


def ensure_default_payment_methods(session: Session) -> None:
    """Crée les moyens de paiement usuels s'ils n'existent pas (appelable plusieurs fois)."""
    for name in DEFAULT_PAYMENT_METHODS:
        get_or_create_payment_method(session, name)
