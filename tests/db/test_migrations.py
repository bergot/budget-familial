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


def _insert_version_1_data(engine) -> None:  # type: ignore[no-untyped-def]
    """Données telles que l'application de l'étape 2 les aurait écrites (schéma 0001)."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO accounts (id, name, bank, initial_balance_cents, closed) VALUES "
            "(1, 'SG', NULL, 100000, 0), (2, 'Boursorama', NULL, 0, 0)"
        )
        connection.exec_driver_sql("INSERT INTO payees (id, name) VALUES (1, 'Carrefour')")
        connection.exec_driver_sql(
            "INSERT INTO transactions "
            "(id, account_id, date, amount_cents, payee_id, notes, transfer_peer_id) VALUES "
            "(1, 1, '2026-03-01', -4250, 1, 'courses', NULL), "
            "(2, 1, '2026-03-02', -30000, NULL, '', NULL), "
            "(3, 2, '2026-03-02', 30000, NULL, '', NULL)"
        )
        # Le virement : deux lignes qui se désignent mutuellement.
        connection.exec_driver_sql("UPDATE transactions SET transfer_peer_id = 3 WHERE id = 2")
        connection.exec_driver_sql("UPDATE transactions SET transfer_peer_id = 2 WHERE id = 3")


def test_upgrade_from_version_1_keeps_existing_data(tmp_path: Path) -> None:
    """Le cas réel : une base déjà remplie passe de la version 0001 à la dernière."""
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine, revision="0001")
    _insert_version_1_data(engine)

    upgrade_to_head(engine)  # applique 0002 sur une base qui contient des données

    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id, account_id, amount_cents, notes, transfer_peer_id, status, "
            "reconciliation_id FROM transactions ORDER BY id"
        ).fetchall()
        assert rows == [
            (1, 1, -4250, "courses", None, "none", None),
            (2, 1, -30000, "", 3, "none", None),  # le lien du virement a survécu
            (3, 2, 30000, "", 2, "none", None),
        ]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        # Les clés étrangères sont de nouveau actives pour l'application.
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_upgrade_from_version_1_gives_a_working_schema(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine, revision="0001")
    _insert_version_1_data(engine)
    upgrade_to_head(engine)

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def test_downgrade_is_possible(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    from budget.db.migrate import MIGRATIONS_DIR

    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001")
    assert "reconciliations" not in set(inspect(engine).get_table_names())


def test_backup_is_made_before_migrating_an_existing_database(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "budget.sqlite"
    engine = create_db_engine(path)
    upgrade_to_head(engine, revision="0001")
    _insert_version_1_data(engine)
    assert list(tmp_path.glob("*.bak")) == []  # base neuve : rien à sauvegarder

    upgrade_to_head(
        engine, revision="0002"
    )  # une version précise : le test ne dépend pas des suivantes

    (backup,) = tmp_path.glob("*.bak")
    assert backup.name == "budget.sqlite.avant-0002.bak"
    with sqlite3.connect(backup) as old:  # la copie est l'ancienne version, avec ses données
        columns = [row[1] for row in old.execute("PRAGMA table_info(transactions)")]
        assert "status" not in columns
        assert old.execute("SELECT count(*) FROM transactions").fetchone() == (3,)


def test_no_backup_when_already_up_to_date(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)
    upgrade_to_head(engine)  # redémarrage
    assert list(tmp_path.glob("*.bak")) == []


def test_foreign_keys_are_off_only_during_the_migration(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_upgrade_from_version_2_keeps_transfers_and_reconciliations(tmp_path: Path) -> None:
    """0002 -> 0003 sur une base peuplée : virements liés et rapprochements intacts."""
    engine = create_db_engine(tmp_path / "budget.sqlite")
    upgrade_to_head(engine, revision="0002")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO accounts (id, name, bank, initial_balance_cents, closed) VALUES "
            "(1, 'SG', NULL, 100000, 0), (2, 'Boursorama', NULL, 0, 0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO reconciliations (id, account_id, statement_date, statement_balance_cents) "
            "VALUES (1, 1, '2026-03-31', 70000)"
        )
        connection.exec_driver_sql(
            "INSERT INTO transactions (id, account_id, date, amount_cents, notes, status, "
            "reconciliation_id) VALUES "
            "(1, 1, '2026-03-02', -30000, '', 'reconciled', 1), "
            "(2, 2, '2026-03-02', 30000, '', 'pointed', NULL), "
            "(3, 1, '2026-04-01', -500, 'x', 'none', NULL)"
        )
        connection.exec_driver_sql("UPDATE transactions SET transfer_peer_id = 2 WHERE id = 1")
        connection.exec_driver_sql("UPDATE transactions SET transfer_peer_id = 1 WHERE id = 2")

    upgrade_to_head(engine)

    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id, transfer_peer_id, status, reconciliation_id, schedule_id "
            "FROM transactions ORDER BY id"
        ).fetchall()
        assert rows == [
            (1, 2, "reconciled", 1, None),  # virement et rapprochement conservés
            (2, 1, "pointed", None, None),
            (3, None, "none", None, None),
        ]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert connection.exec_driver_sql("SELECT count(*) FROM schedules").scalar() == 0
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []
