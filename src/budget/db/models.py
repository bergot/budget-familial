"""Modèles SQLAlchemy 2.x : une classe = une table.

Conventions :
- les montants sont des entiers en centimes (`*_cents`) ;
- un montant d'opération est signé : négatif = dépense, positif = recette ;
- on écrit `dt.date` (et non `date`) car la colonne s'appelle `date` : un attribut
  de même nom que son type provoque des confusions dans les annotations.
"""

import datetime as dt

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budget.db.base import Base


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
    # Pour un virement : l'autre moitié du couple d'opérations liées.
    transfer_peer_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )

    account: Mapped[Account] = relationship(back_populates="transactions")
    payee: Mapped[Payee | None] = relationship()
    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()

    @property
    def is_transfer(self) -> bool:
        return self.transfer_peer_id is not None

    def __repr__(self) -> str:
        return (
            f"Transaction(id={self.id}, account_id={self.account_id}, "
            f"{self.date}, {self.amount_cents})"
        )
