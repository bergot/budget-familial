from sqlalchemy.orm import Session

from budget.services import lookups


def test_get_or_create_payee_creates_then_reuses(session: Session) -> None:
    first = lookups.get_or_create_payee(session, "Carrefour")
    again = lookups.get_or_create_payee(session, "  carrefour ")
    assert again.id == first.id
    assert len(lookups.list_payees(session)) == 1


def test_payees_are_sorted(session: Session) -> None:
    lookups.get_or_create_payee(session, "Leclerc")
    lookups.get_or_create_payee(session, "Auchan")
    assert [p.name for p in lookups.list_payees(session)] == ["Auchan", "Leclerc"]


def test_default_payment_methods_are_created_once(session: Session) -> None:
    lookups.ensure_default_payment_methods(session)
    lookups.ensure_default_payment_methods(session)
    names = {m.name for m in lookups.list_payment_methods(session)}
    assert names == set(lookups.DEFAULT_PAYMENT_METHODS)


def test_get_or_create_payment_method_ignores_case(session: Session) -> None:
    a = lookups.get_or_create_payment_method(session, "Carte")
    b = lookups.get_or_create_payment_method(session, "carte")
    assert a.id == b.id
