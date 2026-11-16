"""Listes de choix pour les formulaires (comptes, catégories, moyens de paiement, tiers)."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from budget.services import accounts, categories, lookups


@dataclass(frozen=True, slots=True)
class Choice:
    """Une entrée de liste déroulante : un identifiant et le texte affiché."""

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class Choices:
    accounts: tuple[Choice, ...]  # comptes ouverts seulement
    categories: tuple[Choice, ...]  # dans l'ordre de l'arbre : « Logement », « Logement : Loyer »
    payment_methods: tuple[Choice, ...]
    payee_names: tuple[str, ...]  # pour l'auto-complétion


def load_choices(session: Session) -> Choices:
    return Choices(
        accounts=tuple(Choice(a.id, a.name) for a in accounts.list_accounts(session)),
        categories=tuple(
            Choice(c.id, c.full_name) for c in categories.list_all_categories(session)
        ),
        payment_methods=tuple(Choice(m.id, m.name) for m in lookups.list_payment_methods(session)),
        payee_names=tuple(p.name for p in lookups.list_payees(session)),
    )
