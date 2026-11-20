"""Catégories et sous-catégories (deux niveaux au maximum)."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from budget.db.models import BudgetLine, Category, Schedule, Transaction
from budget.domain.enums import CategoryKind
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


def create_category(
    session: Session,
    name: str,
    *,
    parent_id: int | None = None,
    kind: CategoryKind = CategoryKind.EXPENSE,
) -> Category:
    """Crée une catégorie ou, si `parent_id` est donné, une sous-catégorie.

    Une sous-catégorie prend toujours le type (dépense ou recette) de sa catégorie parente :
    le paramètre `kind` ne sert que pour une catégorie de premier niveau.
    """
    name = clean_name(name, "Catégorie")
    if parent_id is not None:
        parent = require(session, Category, parent_id, "Catégorie parente")
        if parent.parent_id is not None:
            raise InvalidError("Une sous-catégorie ne peut pas avoir de sous-catégorie")
        kind = parent.kind
    if _sibling_exists(session, name, parent_id):
        raise DuplicateError(f"« {name} » existe déjà à cet emplacement")
    category = Category(name=name, parent_id=parent_id, kind=kind)
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


def set_category_kind(session: Session, category_id: int, kind: CategoryKind) -> Category:
    """Change le type d'une catégorie de premier niveau ; ses sous-catégories le suivent.

    Les montants prévus du budget sont positifs dans les deux cas : changer le type ne les
    modifie pas, mais change leur interprétation (sortie ou entrée d'argent).
    """
    category = get_category(session, category_id)
    if category.parent_id is not None:
        raise InvalidError(
            f"« {category.full_name} » suit le type de sa catégorie : modifiez celui de "
            f"« {category.parent.name if category.parent else ''} »"
        )
    category.kind = kind
    for child in category.children:
        child.kind = kind
    session.flush()
    return category


def update_category(
    session: Session, category_id: int, *, name: str, kind: CategoryKind
) -> Category:
    """Renomme une catégorie et, si elle est de premier niveau, change son type."""
    category = rename_category(session, category_id, name)
    if category.kind != kind:
        set_category_kind(session, category_id, kind)
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
    used_by_schedule = session.scalar(
        select(Schedule.id).where(Schedule.category_id == category_id).limit(1)
    )
    if used_by_schedule is not None:
        raise InvalidError(f"« {category.full_name} » est utilisée par des échéances")
    # Les montants prévus ne sont que des projections : ils disparaissent avec la catégorie.
    session.execute(delete(BudgetLine).where(BudgetLine.category_id == category_id))
    session.delete(category)
    session.flush()
