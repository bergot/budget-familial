"""Modèles SQLAlchemy 2.x : une classe = une table.

Conventions :
- les montants sont des entiers en centimes (`*_cents`) ;
- un montant d'opération est signé : négatif = dépense, positif = recette ;
- on écrit `dt.date` (et non `date`) car la colonne s'appelle `date` : un attribut
  de même nom que son type provoque des confusions dans les annotations.
"""

import datetime as dt
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budget.db.base import Base
from budget.domain.enums import Frequency, ReconciliationStatus


def enum_column[E: StrEnum](enum_class: type[E]) -> Enum:
    """Colonne énumérée : SQLite n'a pas de type énuméré, on stocke la valeur comme du texte."""
    return Enum(
        enum_class,
        native_enum=False,
        length=20,
        # On stocke « pointed » (la valeur) plutôt que « POINTED » (le nom du membre).
        values_callable=lambda members: [member.value for member in members],
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    bank: Mapped[str | None] = mapped_column(String(100))  # None => NULL en base
    initial_balance_cents: Mapped[int] = mapped_column(default=0)
    closed: Mapped[bool] = mapped_column(default=False)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")

    def __repr__(self) -> str:
        return f"Account(id={self.id}, name={self.name!r})"


class Category(Base):
    """Catégorie (parent_id vide) ou sous-catégorie (parent_id renseigné)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    parent: Mapped[Category | None] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list[Category]] = relationship(
        back_populates="parent", order_by="Category.name"
    )

    @property
    def full_name(self) -> str:
        """'Logement : Loyer' pour une sous-catégorie, 'Logement' pour une catégorie."""
        return f"{self.parent.name} : {self.name}" if self.parent else self.name

    def __repr__(self) -> str:
        return f"Category(id={self.id}, name={self.name!r}, parent_id={self.parent_id})"


class Payee(Base):
    """Tiers : la personne ou l'enseigne de l'opération."""

    __tablename__ = "payees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Reconciliation(Base):
    """Un rapprochement validé : le solde du relevé à une date donnée."""

    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    statement_date: Mapped[dt.date]
    statement_balance_cents: Mapped[int]


class Schedule(Base):
    """Échéance récurrente : un modèle d'opération (ou de virement) et son rythme.

    Les opérations sont générées jusqu'à un horizon (voir `services/schedules.py`). Le
    compteur `generated_count` est le nombre d'occurrences déjà générées : la prochaine à
    produire est l'occurrence n° `generated_count` (0 = la date de début). Ce compteur évite
    tout doublon, et une opération générée puis supprimée n'est jamais recréée.
    """

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[
        int
    ]  # opération : signé ; virement : positif (sens = compte -> destination)
    frequency: Mapped[Frequency] = mapped_column(enum_column(Frequency))
    start_date: Mapped[dt.date]
    end_date: Mapped[dt.date | None]
    generated_count: Mapped[int] = mapped_column(default=0, server_default="0")
    payee_id: Mapped[int | None] = mapped_column(ForeignKey("payees.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    notes: Mapped[str] = mapped_column(default="")
    # Renseigné pour un virement planifié : le compte qui reçoit.
    transfer_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    # Deux clés étrangères vers `accounts` : il faut dire à SQLAlchemy laquelle utiliser.
    account: Mapped[Account] = relationship(foreign_keys=[account_id])
    transfer_account: Mapped[Account | None] = relationship(foreign_keys=[transfer_account_id])
    payee: Mapped[Payee | None] = relationship()
    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()

    @property
    def is_transfer(self) -> bool:
        return self.transfer_account_id is not None


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_account_date", "account_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    date: Mapped[dt.date]
    amount_cents: Mapped[int]  # signé : < 0 dépense, > 0 recette
    payee_id: Mapped[int | None] = mapped_column(ForeignKey("payees.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    notes: Mapped[str] = mapped_column(default="")
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_column(ReconciliationStatus),
        default=ReconciliationStatus.NONE,
        server_default=ReconciliationStatus.NONE.value,
    )
    reconciliation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reconciliations.id", name="fk_transactions_reconciliation_id")
    )
    # Échéance qui a généré cette opération (None si saisie à la main). Supprimer l'échéance
    # conserve les opérations déjà générées : elles perdent simplement ce lien.
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id", name="fk_transactions_schedule_id", ondelete="SET NULL")
    )
    # Pour un virement : l'autre moitié du couple d'opérations liées.
    transfer_peer_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )

    account: Mapped[Account] = relationship(back_populates="transactions")
    payee: Mapped[Payee | None] = relationship()
    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()
    transfer_peer: Mapped[Transaction | None] = relationship(
        remote_side="Transaction.id", foreign_keys=[transfer_peer_id]
    )

    @property
    def is_transfer(self) -> bool:
        return self.transfer_peer_id is not None

    def __repr__(self) -> str:
        return (
            f"Transaction(id={self.id}, account_id={self.account_id}, "
            f"{self.date}, {self.amount_cents})"
        )
