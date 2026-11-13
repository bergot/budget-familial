import datetime as dt

import pytest
from sqlalchemy.orm import Session

from budget.db.models import Account
from budget.domain.errors import DuplicateError, InvalidError, NotFoundError
from budget.services import categories
from budget.services.transactions import TransactionData, add_transaction


def test_create_category_and_subcategory(session: Session) -> None:
    logement = categories.create_category(session, "Logement")
    loyer = categories.create_category(session, "Loyer", parent_id=logement.id)

    assert logement.parent_id is None
    assert loyer.parent_id == logement.id
    assert loyer.full_name == "Logement : Loyer"
    assert logement.full_name == "Logement"


def test_only_two_levels(session: Session) -> None:
    logement = categories.create_category(session, "Logement")
    loyer = categories.create_category(session, "Loyer", parent_id=logement.id)
    with pytest.raises(InvalidError):
        categories.create_category(session, "Charges", parent_id=loyer.id)


def test_unknown_parent(session: Session) -> None:
    with pytest.raises(NotFoundError):
        categories.create_category(session, "Loyer", parent_id=999)


def test_duplicate_root_name_is_refused_ignoring_case(session: Session) -> None:
    categories.create_category(session, "Logement")
    with pytest.raises(DuplicateError):
        categories.create_category(session, "logement")


def test_same_name_allowed_under_different_parents(session: Session) -> None:
    a = categories.create_category(session, "Auto")
    b = categories.create_category(session, "Moto")
    categories.create_category(session, "Assurance", parent_id=a.id)
    categories.create_category(session, "Assurance", parent_id=b.id)  # pas d'erreur


def test_duplicate_under_same_parent_is_refused(session: Session) -> None:
    a = categories.create_category(session, "Auto")
    categories.create_category(session, "Assurance", parent_id=a.id)
    with pytest.raises(DuplicateError):
        categories.create_category(session, "assurance", parent_id=a.id)


def test_tree_is_sorted(session: Session) -> None:
    z = categories.create_category(session, "Zoo")
    a = categories.create_category(session, "Auto")
    categories.create_category(session, "Péage", parent_id=a.id)
    categories.create_category(session, "Assurance", parent_id=a.id)

    roots = categories.list_root_categories(session)
    assert [c.name for c in roots] == ["Auto", "Zoo"]
    assert [c.name for c in roots[0].children] == ["Assurance", "Péage"]

    flat = categories.list_all_categories(session)
    assert [c.name for c in flat] == ["Auto", "Assurance", "Péage", "Zoo"]
    assert z in flat


def test_rename(session: Session) -> None:
    c = categories.create_category(session, "Loisir")
    categories.rename_category(session, c.id, "Loisirs")
    assert c.name == "Loisirs"


def test_rename_to_existing_sibling_is_refused(session: Session) -> None:
    categories.create_category(session, "Loisirs")
    c = categories.create_category(session, "Sorties")
    with pytest.raises(DuplicateError):
        categories.rename_category(session, c.id, "loisirs")


def test_delete_category(session: Session) -> None:
    c = categories.create_category(session, "Divers")
    categories.delete_category(session, c.id)
    assert categories.list_root_categories(session) == []


def test_delete_category_with_children_is_refused(session: Session) -> None:
    a = categories.create_category(session, "Auto")
    categories.create_category(session, "Assurance", parent_id=a.id)
    with pytest.raises(InvalidError):
        categories.delete_category(session, a.id)


def test_delete_used_category_is_refused(session: Session, sg: Account, day: dt.date) -> None:
    c = categories.create_category(session, "Courses")
    add_transaction(
        session,
        TransactionData(account_id=sg.id, date=day, amount_cents=-500, category_id=c.id),
    )
    with pytest.raises(InvalidError):
        categories.delete_category(session, c.id)
