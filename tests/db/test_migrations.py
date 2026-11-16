from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from budget.db.base import Base, create_db_engine, make_session_factory, unit_of_work
from budget.db.migrate import upgrade_to_head
from budget.services import accounts


def test_migrations_build_a_database_identical_to_the_models(tmp_path: Path) -> None:
    """Garde-fou : si on modifie un modèle sans écrire la migration, ce test échoue."""
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_upgrade_creates_all_tables(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"accounts", "categories", "payees", "payment_methods", "transactions"} <= tables
    assert "alembic_version" in tables


def test_upgrade_twice_keeps_existing_data(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite"
    engine = create_db_engine(path)
    upgrade_to_head(engine)
    factory = make_session_factory(engine)
    with unit_of_work(factory) as session:
        accounts.create_account(session, "SG", initial_balance_cents=1000)

    upgrade_to_head(engine)  # simule un redémarrage de l'application

    with factory() as session:
        (account,) = accounts.list_accounts(session)
        assert account.initial_balance_cents == 1000
