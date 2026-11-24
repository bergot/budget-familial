"""Préparation de la base au lancement : migrations, sauvegarde du jour, échéances."""

import datetime as dt
import sqlite3
from pathlib import Path

from budget import backup
from budget.db.base import unit_of_work
from budget.domain.enums import Frequency
from budget.services import accounts
from budget.services import schedules as sch
from budget.services.schedules import ScheduleData
from budget.settings import Settings
from budget.startup import open_database

TODAY = dt.date(2026, 3, 15)


def count_backups(database: Path) -> int:
    return len(backup.list_backups(backup.default_backup_dir(database)))


def test_first_launch_creates_the_database_and_no_backup(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, report = open_database(database, today=TODAY)

    assert database.exists()
    assert report.generation.created == 0
    assert report.backup.path is None and report.backup.skipped_reason  # base vide : rien à copier
    assert count_backups(database) == 0
    assert not (tmp_path / "sauvegardes").exists()


def test_a_backup_is_made_once_a_day_once_there_is_data(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        accounts.create_account(session, "SG", initial_balance_cents=1000)

    _, second = open_database(database, today=TODAY)  # le même jour, mais il y a des données
    assert second.backup.path is not None and second.backup.error is None
    assert count_backups(database) == 1

    _, third = open_database(database, today=TODAY)  # relancé le même jour : pas de deuxième copie
    assert third.backup.path is None and "aujourd'hui" in (third.backup.skipped_reason or "")
    assert count_backups(database) == 1

    _, next_day = open_database(database, today=TODAY + dt.timedelta(days=1))
    assert next_day.backup.path is not None
    assert count_backups(database) == 2


def test_the_backup_contains_the_data_as_left_by_the_user(tmp_path: Path) -> None:
    """La sauvegarde est faite avant la génération des échéances : sans les opérations du jour."""
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        account = accounts.create_account(session, "SG").id
        sch.create_schedule(
            session, ScheduleData(account, -100, Frequency.MONTHLY, dt.date(2026, 3, 5))
        )

    _, report = open_database(database, today=TODAY)

    assert report.generation.created == 4  # les opérations sont générées...
    assert report.backup.path is not None
    with sqlite3.connect(report.backup.path) as copy:
        assert copy.execute("SELECT count(*) FROM transactions").fetchone() == (0,)  # ...après
        assert copy.execute("SELECT count(*) FROM schedules").fetchone() == (1,)


def test_backup_settings_are_honored(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        accounts.create_account(session, "SG")

    _, disabled = open_database(database, settings=Settings(backup_enabled=False), today=TODAY)
    assert disabled.backup.path is None and count_backups(database) == 0

    elsewhere = tmp_path / "ailleurs"
    _, custom = open_database(database, settings=Settings(backup_dir=str(elsewhere)), today=TODAY)
    assert custom.backup.path is not None and custom.backup.path.parent == elsewhere


def test_the_horizon_comes_from_the_settings(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        account = accounts.create_account(session, "SG").id
        sch.create_schedule(
            session, ScheduleData(account, -100, Frequency.MONTHLY, dt.date(2026, 3, 1))
        )

    _, short = open_database(database, settings=Settings(schedule_horizon_months=1), today=TODAY)
    assert short.generation.created == 2  # 1er mars et 1er avril (horizon : 15 avril)

    _, long = open_database(database, settings=Settings(schedule_horizon_months=6), today=TODAY)
    assert long.generation.created == 5  # mai à septembre (horizon : 15 septembre)


def test_a_failing_backup_does_not_prevent_startup(tmp_path: Path) -> None:
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        account = accounts.create_account(session, "SG").id
        sch.create_schedule(
            session, ScheduleData(account, -100, Frequency.MONTHLY, dt.date(2026, 3, 5))
        )
    blocker = tmp_path / "copies"
    blocker.write_text("un fichier, pas un dossier")

    _, report = open_database(database, settings=Settings(backup_dir=str(blocker)), today=TODAY)

    assert report.backup.error  # signalé à l'utilisateur...
    assert report.generation.created == 4  # ...mais le reste du démarrage s'est déroulé


def test_the_pre_migration_copy_and_the_daily_backups_do_not_mix(tmp_path: Path) -> None:
    """Les copies « avant migration » restent à côté de la base ; la rotation n'y touche pas."""
    database = tmp_path / "budget.sqlite"
    factory, _ = open_database(database, today=TODAY)
    with unit_of_work(factory) as session:
        accounts.create_account(session, "SG")
    (tmp_path / "budget.sqlite.avant-0004.bak").write_bytes(b"x")

    for day in range(10):
        open_database(
            database, settings=Settings(backup_keep=3), today=TODAY + dt.timedelta(days=day)
        )

    assert count_backups(database) == 3
    assert (tmp_path / "budget.sqlite.avant-0004.bak").exists()
