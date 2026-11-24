import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from budget import backup
from budget.backup import BackupError
from budget.settings import Settings

NOW = dt.datetime(2026, 3, 15, 9, 30, 0)


def make_database(path: Path, accounts: int = 1) -> Path:
    """Une petite base avec le strict nécessaire : une table `accounts` et quelques lignes."""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany(
            "INSERT INTO accounts (name) VALUES (?)", [(f"Compte {i}",) for i in range(accounts)]
        )
    sqlite3.connect(path).close()
    return path


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# --- Noms et liste --------------------------------------------------------------------------


def test_file_name_is_sortable_and_parsable() -> None:
    name = backup.backup_file_name(NOW)
    assert name == "budget-2026-03-15-093000.sqlite"
    assert backup._parse_name(name) == NOW


@pytest.mark.parametrize(
    "name",
    [
        "budget.sqlite",
        "budget-2026-03-15.sqlite",
        "budget-2026-13-45-250000.sqlite",
        "budget-2026-03-15-093000.sqlite.partiel",
        "budget.sqlite.avant-0004.bak",
        "notes.txt",
    ],
)
def test_other_names_are_not_backups(name: str) -> None:
    assert backup._parse_name(name) is None


def test_list_backups_newest_first_and_ignores_strangers(tmp_path: Path) -> None:
    for name in (
        "budget-2026-03-10-080000.sqlite",
        "budget-2026-03-15-093000.sqlite",
        "budget-2026-03-12-120000.sqlite",
        "budget.sqlite.avant-0004.bak",  # copie « avant migration » : pas une sauvegarde régulière
        "budget-2026-03-12-120000.sqlite.partiel",
        "notes.txt",
    ):
        (tmp_path / name).write_bytes(b"x")
    found = backup.list_backups(tmp_path)
    assert [info.moment.day for info in found] == [15, 12, 10]
    assert all(info.size_bytes == 1 for info in found)


def test_list_backups_of_a_missing_folder(tmp_path: Path) -> None:
    assert backup.list_backups(tmp_path / "absent") == []


def test_default_and_configured_folders(tmp_path: Path) -> None:
    database = tmp_path / "data" / "budget.sqlite"
    assert backup.default_backup_dir(database) == tmp_path / "data" / "sauvegardes"
    assert backup.backup_dir_for(database, "") == tmp_path / "data" / "sauvegardes"
    assert backup.backup_dir_for(database, "   ") == tmp_path / "data" / "sauvegardes"
    assert backup.backup_dir_for(database, str(tmp_path / "copies")) == tmp_path / "copies"
    assert backup.backup_dir_for(database, "~/copies") == Path("~/copies").expanduser()


# --- Création -------------------------------------------------------------------------------


def test_create_backup_copies_the_data(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite", accounts=3)
    directory = tmp_path / "sauvegardes"  # n'existe pas encore : il est créé

    path = backup.create_backup(database, directory, moment=NOW)

    assert path == directory / "budget-2026-03-15-093000.sqlite"
    with sqlite3.connect(path) as copy:
        assert copy.execute("SELECT count(*) FROM accounts").fetchone() == (3,)
    assert names(directory) == [path.name]  # aucun fichier provisoire ne reste


def test_backup_is_a_snapshot_not_a_link(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite", accounts=1)
    path = backup.create_backup(database, tmp_path / "s", moment=NOW)
    with sqlite3.connect(database) as live:
        live.execute("INSERT INTO accounts (name) VALUES ('Nouveau')")
    with sqlite3.connect(path) as copy:
        assert copy.execute("SELECT count(*) FROM accounts").fetchone() == (1,)


def test_backup_while_the_database_is_open_elsewhere(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite", accounts=2)
    reader = sqlite3.connect(database)  # l'application garde sa connexion ouverte
    try:
        reader.execute("SELECT * FROM accounts").fetchall()
        path = backup.create_backup(database, tmp_path / "s", moment=NOW)
    finally:
        reader.close()
    with sqlite3.connect(path) as copy:
        assert copy.execute("SELECT count(*) FROM accounts").fetchone() == (2,)


def test_two_backups_in_the_same_second_do_not_overwrite(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    first = backup.create_backup(database, tmp_path / "s", moment=NOW)
    second = backup.create_backup(database, tmp_path / "s", moment=NOW)
    assert first != second
    assert len(backup.list_backups(tmp_path / "s")) == 2


def test_missing_database_is_reported(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="introuvable"):
        backup.create_backup(tmp_path / "absent.sqlite", tmp_path / "s", moment=NOW)


def test_a_copy_failing_the_integrity_check_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    monkeypatch.setattr(backup, "_integrity_ok", lambda _path: False)
    with pytest.raises(BackupError, match="intégrité"):
        backup.create_backup(database, tmp_path / "s", moment=NOW)
    assert names(tmp_path / "s") == []  # ni copie, ni fichier provisoire


def test_a_file_that_is_not_a_database_is_not_backed_up(tmp_path: Path) -> None:
    junk = tmp_path / "budget.sqlite"
    junk.write_bytes(b"ceci n'est pas une base SQLite" * 50)
    with pytest.raises((BackupError, sqlite3.Error)):
        backup.create_backup(junk, tmp_path / "s", moment=NOW)
    assert backup.list_backups(tmp_path / "s") == []


# --- Rotation -------------------------------------------------------------------------------


def make_old_backups(directory: Path, days: int) -> None:
    directory.mkdir(exist_ok=True)
    for day in range(1, days + 1):
        (directory / f"budget-2026-03-{day:02d}-080000.sqlite").write_bytes(b"x")


def test_prune_keeps_the_newest(tmp_path: Path) -> None:
    make_old_backups(tmp_path, 10)
    removed = backup.prune_backups(tmp_path, keep=3)

    assert len(removed) == 7
    assert [info.moment.day for info in backup.list_backups(tmp_path)] == [10, 9, 8]


def test_prune_with_few_backups_removes_nothing(tmp_path: Path) -> None:
    make_old_backups(tmp_path, 3)
    assert backup.prune_backups(tmp_path, keep=14) == ()
    assert len(backup.list_backups(tmp_path)) == 3


def test_prune_never_touches_other_files(tmp_path: Path) -> None:
    make_old_backups(tmp_path, 5)
    (tmp_path / "budget.sqlite.avant-0004.bak").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    backup.prune_backups(tmp_path, keep=1)
    assert "budget.sqlite.avant-0004.bak" in names(tmp_path) and "notes.txt" in names(tmp_path)


def test_prune_always_keeps_at_least_one(tmp_path: Path) -> None:
    make_old_backups(tmp_path, 4)
    backup.prune_backups(tmp_path, keep=0)  # garde-fou : jamais tout supprimer
    assert len(backup.list_backups(tmp_path)) == 1


# --- À faire aujourd'hui ? ------------------------------------------------------------------


def test_backup_is_due_only_once_a_day(tmp_path: Path) -> None:
    today = dt.date(2026, 3, 15)
    assert backup.backup_is_due(tmp_path, today)  # dossier absent
    make_old_backups(tmp_path, 14)
    assert backup.backup_is_due(tmp_path, today)  # la dernière date de la veille
    (tmp_path / "budget-2026-03-15-070000.sqlite").write_bytes(b"x")
    assert not backup.backup_is_due(tmp_path, today)


def test_has_data(tmp_path: Path) -> None:
    assert not backup.has_data(tmp_path / "absent.sqlite")
    assert not backup.has_data(make_database(tmp_path / "vide.sqlite", accounts=0))
    assert backup.has_data(make_database(tmp_path / "pleine.sqlite", accounts=1))
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"pas du sqlite" * 20)
    assert not backup.has_data(junk)
    no_table = tmp_path / "sanstable.sqlite"
    sqlite3.connect(no_table).close()
    assert not backup.has_data(no_table)


# --- Sauvegarde automatique -----------------------------------------------------------------


def test_automatic_backup_creates_one_and_then_waits_for_tomorrow(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite", accounts=2)
    settings = Settings()

    first = backup.run_automatic_backup(database, settings, now=NOW)
    assert first.path is not None and first.error is None and first.skipped_reason is None
    assert first.path.parent == tmp_path / "sauvegardes"

    again = backup.run_automatic_backup(database, settings, now=NOW + dt.timedelta(hours=5))
    assert again.path is None and "aujourd'hui" in (again.skipped_reason or "")
    assert len(backup.list_backups(tmp_path / "sauvegardes")) == 1

    tomorrow = backup.run_automatic_backup(database, settings, now=NOW + dt.timedelta(days=1))
    assert tomorrow.path is not None
    assert len(backup.list_backups(tmp_path / "sauvegardes")) == 2


def test_automatic_backup_applies_the_rotation(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    folder = tmp_path / "sauvegardes"
    make_old_backups(folder, 10)

    outcome = backup.run_automatic_backup(database, Settings(backup_keep=4), now=NOW)

    assert outcome.path is not None and len(outcome.removed) == 7  # 10 + 1 - 4
    assert len(backup.list_backups(folder)) == 4
    assert backup.list_backups(folder)[0].path == outcome.path  # la nouvelle est conservée


def test_automatic_backup_can_be_disabled(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    outcome = backup.run_automatic_backup(database, Settings(backup_enabled=False), now=NOW)
    assert outcome.path is None and "désactivée" in (outcome.skipped_reason or "")
    assert not (tmp_path / "sauvegardes").exists()


def test_automatic_backup_skips_an_empty_or_missing_database(tmp_path: Path) -> None:
    empty = make_database(tmp_path / "vide.sqlite", accounts=0)
    assert backup.run_automatic_backup(empty, Settings(), now=NOW).skipped_reason is not None
    missing = tmp_path / "absent.sqlite"
    assert backup.run_automatic_backup(missing, Settings(), now=NOW).skipped_reason is not None
    assert not (tmp_path / "sauvegardes").exists()  # pas de dossier créé pour rien


def test_automatic_backup_uses_the_configured_folder(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    elsewhere = tmp_path / "nuage" / "copies"
    outcome = backup.run_automatic_backup(database, Settings(backup_dir=str(elsewhere)), now=NOW)
    assert outcome.path is not None and outcome.path.parent == elsewhere


def test_automatic_backup_failure_is_reported_not_raised(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    blocker = tmp_path / "copies"
    blocker.write_text("un fichier là où il faudrait un dossier")

    outcome = backup.run_automatic_backup(database, Settings(backup_dir=str(blocker)), now=NOW)

    assert outcome.path is None and outcome.error  # l'application démarrera quand même


def test_backup_now_ignores_the_daily_limit(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite")
    settings = Settings(backup_keep=5)
    first, _ = backup.backup_now(database, settings, now=NOW)
    second, _ = backup.backup_now(database, settings, now=NOW + dt.timedelta(minutes=1))
    assert first != second and len(backup.list_backups(tmp_path / "sauvegardes")) == 2
