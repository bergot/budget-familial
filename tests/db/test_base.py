import datetime as dt

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from budget.db.base import create_db_engine, init_schema
from budget.db.models import Transaction


def test_foreign_keys_are_enabled(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_foreign_key_violation_is_rejected(session: Session) -> None:
    session.add(Transaction(account_id=999, date=dt.date(2026, 1, 1), amount_cents=100))
    with pytest.raises(IntegrityError):
        session.flush()


def test_file_database_is_created(tmp_path) -> None:
    path = tmp_path / "budget.sqlite"
    engine = create_db_engine(path)
    init_schema(engine)
    assert path.exists()


def test_init_schema_can_be_called_twice(engine: Engine) -> None:
    init_schema(engine)  # ne doit pas échouer : les tables existent déjà


def test_unit_of_work_commits_on_success(tmp_path) -> None:
    from budget.db.base import make_session_factory, unit_of_work
    from budget.services import accounts

    engine = create_db_engine(tmp_path / "b.sqlite")
    init_schema(engine)
    factory = make_session_factory(engine)

    with unit_of_work(factory) as session:
        accounts.create_account(session, "SG")

    with factory() as session:
        assert [a.name for a in accounts.list_accounts(session)] == ["SG"]


def test_unit_of_work_rolls_back_on_error(tmp_path) -> None:
    from budget.db.base import make_session_factory, unit_of_work
    from budget.services import accounts

    engine = create_db_engine(tmp_path / "b.sqlite")
    init_schema(engine)
    factory = make_session_factory(engine)

    with pytest.raises(RuntimeError), unit_of_work(factory) as session:
        accounts.create_account(session, "SG")
        raise RuntimeError("boum")

    with factory() as session:
        assert accounts.list_accounts(session) == []
