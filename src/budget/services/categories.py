"""Catégories et sous-catégories (deux niveaux au maximum)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Category, Transaction
from budget.domain.errors import DuplicateError, InvalidError
from budget.services._common import clean_name, require


def _sibling_exists(
    session: Session, name: str, parent_id: int | None, *, except_id: int | None = None
) -> bool:
    """Une catégorie de ce nom existe-t-elle déjà sous ce parent (casse ignorée) ?"""
    stmt = select(Category.id).where(func.lower(Category.name) == name.lower())
    # En SQL, `parent_id = NULL` n'est jamais vrai : il faut `IS NULL`.
    stmt = stmt.where(
        Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    )
    if except_id is not None:
        stmt = stmt.where(Category.id != except_id)
    return session.scalar(stmt) is not None


def create_category(session: Session, name: str, *, parent_id: int | None = None) -> Category:
    name = clean_name(name, "Catégorie")
    if parent_id is not None:
        parent = require(session, Category, parent_id, "Catégorie parente")
        if parent.parent_id is not None:
            raise InvalidError("Une sous-catégorie ne peut pas avoir de sous-catégorie")
    if _sibling_exists(session, name, parent_id):
        raise DuplicateError(f"« {name} » existe déjà à cet emplacement")
    category = Category(name=name, parent_id=parent_id)
    session.add(category)
    session.flush()
    return category


def get_category(session: Session, category_id: int) -> Category:
    return require(session, Category, category_id, "Catégorie")


def list_root_categories(session: Session) -> list[Category]:
    """Catégories de premier niveau, triées ; leurs sous-catégories sont dans `.children`."""
    stmt = select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    return list(session.scalars(stmt))


def list_all_categories(session: Session) -> list[Category]:
    """Toutes les catégories à plat, dans l'ordre de l'arbre (parent puis ses enfants)."""
    result: list[Category] = []
    for root in list_root_categories(session):
        result.append(root)
        result.extend(root.children)
    return result


def rename_category(session: Session, category_id: int, name: str) -> Category:
    category = get_category(session, category_id)
    name = clean_name(name, "Catégorie")
    if _sibling_exists(session, name, category.parent_id, except_id=category_id):
        raise DuplicateError(f"« {name} » existe déjà à cet emplacement")
    category.name = name
    session.flush()
    return category


def delete_category(session: Session, category_id: int) -> None:
    """Supprime une catégorie, si elle n'a pas de sous-catégories et n'est pas utilisée."""
    category = get_category(session, category_id)
    if category.children:
        raise InvalidError(f"« {category.name} » contient des sous-catégories")
    used = session.scalar(
        select(Transaction.id).where(Transaction.category_id == category_id).limit(1)
    )
    if used is not None:
        raise InvalidError(f"« {category.full_name} » est utilisée par des opérations")
    session.delete(category)
    session.flush()
