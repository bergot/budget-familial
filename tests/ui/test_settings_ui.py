"""Préférences, sauvegardes manuelles, taille des fenêtres, icône, test de fumée."""

import datetime as dt
import os
import sqlite3
import struct
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QLabel
from sqlalchemy.orm import Session, sessionmaker

from budget import __version__, backup
from budget.db.base import unit_of_work
from budget.domain.enums import Frequency
from budget.services import accounts
from budget.services import schedules as sch
from budget.services import transactions as tx
from budget.services.schedules import ScheduleData
from budget.settings import Settings, SettingsStore
from budget.startup import StartupReport
from budget.ui import app as app_module
from budget.ui import main_window as main_window_module
from budget.ui.dialogs import preferences_dialog
from budget.ui.dialogs.budget_dialog import BudgetDialog
from budget.ui.dialogs.categories_dialog import CategoriesDialog
from budget.ui.dialogs.preferences_dialog import PreferencesDialog
from budget.ui.dialogs.reconciliation_dialog import ReconciliationDialog
from budget.ui.dialogs.schedules_dialog import SchedulesDialog
from budget.ui.icons import ICON_SIZES, RESOURCES_DIR, load_app_icon
from budget.ui.main_window import MainWindow
from tests.ui.conftest import TODAY
from tests.ui.helpers import answer_next_dialog

Factory = sessionmaker[Session]
D = dt.date


# L'écran virtuel du mode « offscreen » fait 800 px de large. Qt ramène volontairement une
# fenêtre mémorisée dans l'écran disponible (cas d'un écran débranché) : les tailles de test
# doivent donc rester plus petites que l'écran.


def make_account(factory: Factory, name: str = "SG") -> int:
    """Crée le compte s'il n'existe pas encore (peut être appelée plusieurs fois)."""
    with unit_of_work(factory) as session:
        for existing in accounts.list_accounts(session):
            if existing.name == name:
                return existing.id
        return accounts.create_account(session, name, initial_balance_cents=100_000).id


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Remplace les boîtes d'erreur de la fenêtre principale par un enregistrement."""
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window_module,
        "show_error",
        lambda _parent, text, title="Erreur": messages.append((title, str(text))),
    )
    return messages


def make_window(factory: Factory, database: Path, store: SettingsStore | None = None) -> MainWindow:
    window = MainWindow(factory, today=lambda: TODAY, store=store, database=database)
    window.show()
    return window


# --- Icône ----------------------------------------------------------------------------------


def test_the_icon_is_available_in_every_size(qapp) -> None:  # type: ignore[no-untyped-def]
    icon = load_app_icon()
    assert not icon.isNull()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert {(size, size) for size in ICON_SIZES} <= sizes
    assert icon.pixmap(QSize(64, 64)).width() > 0


def test_icon_files_exist_and_ico_is_well_formed() -> None:
    for name in ("icon.svg", "icon.ico", *(f"icon-{size}.png" for size in ICON_SIZES)):
        assert (RESOURCES_DIR / name).is_file(), name

    data = (RESOURCES_DIR / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(ICON_SIZES))
    for index in range(count):
        *_, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * index : 22 + 16 * index])
        assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n" and size > 0


def test_a_missing_resource_folder_gives_an_empty_icon(
    qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from budget.ui import icons

    monkeypatch.setattr(icons, "RESOURCES_DIR", tmp_path)
    assert icons.load_app_icon().isNull()


# --- Version --------------------------------------------------------------------------------


def test_the_version_is_shown_in_the_status_bar(qapp, factory: Factory, database: Path) -> None:  # type: ignore[no-untyped-def]
    window = make_window(factory, database)
    texts = [label.text() for label in window.statusBar().findChildren(QLabel)]
    assert f"Version {__version__}" in texts


def test_about_shows_the_version_and_the_data_file(
    qapp, factory: Factory, database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    shown: list[str] = []

    class FakeMessageBox:
        @staticmethod
        def about(_parent: object, _title: str, text: str) -> None:
            shown.append(text)

    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)
    window = make_window(factory, database)

    window.act_about.trigger()

    assert __version__ in shown[0] and str(database) in shown[0] and "MIT" in shown[0]


# --- Taille des fenêtres --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "key"),
    [
        (lambda f, s: BudgetDialog(f, today=TODAY, store=s), "budget"),
        (lambda f, s: SchedulesDialog(f, today=TODAY, store=s), "schedules"),
        (lambda f, s: CategoriesDialog(f, store=s), "categories"),
        (
            lambda f, s: ReconciliationDialog(f, make_account(f), today=TODAY, store=s),
            "reconciliation",
        ),
    ],
)
def test_dialogs_remember_their_size(qapp, factory: Factory, make, key: str) -> None:  # type: ignore[no-untyped-def]
    store = SettingsStore()
    first = make(factory, store)
    first.resize(661, 413)
    obtained = (first.width(), first.height())  # la taille obtenue peut différer de la demandée
    assert store.settings.geometry(key) is None  # rien n'est mémorisé avant la fermeture

    first.done(0)

    assert store.settings.geometry(key)
    second = make(factory, store)
    assert (second.width(), second.height()) == obtained


def test_the_size_is_saved_whatever_the_way_the_dialog_closes(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    for close in ("accept", "reject", "close"):
        store = SettingsStore()
        dialog = CategoriesDialog(factory, store=store)
        dialog.show()
        getattr(dialog, close)()
        assert store.settings.geometry("categories"), close


def test_a_dialog_without_a_store_still_works(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    dialog = CategoriesDialog(factory)
    dialog.resize(500, 400)
    dialog.done(0)  # ne doit pas lever d'exception


def test_the_size_survives_a_restart(qapp, factory: Factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "settings.json"
    first = BudgetDialog(factory, today=TODAY, store=SettingsStore.load(path))
    first.resize(677, 444)
    obtained = (first.width(), first.height())
    first.done(0)

    assert "budget" in path.read_text(encoding="utf-8")  # écrit sur le disque
    reloaded = BudgetDialog(factory, today=TODAY, store=SettingsStore.load(path))
    assert (reloaded.width(), reloaded.height()) == obtained


def test_damaged_geometry_data_is_ignored(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    store = SettingsStore(Settings(geometries={"budget": "AAAA", "categories": "pas du base64 !"}))
    default = BudgetDialog(factory, today=TODAY)
    assert (BudgetDialog(factory, today=TODAY, store=store).size()) == default.size()
    CategoriesDialog(factory, store=store)  # ne lève pas d'exception


def test_the_main_window_remembers_its_size_and_splitter(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    store = SettingsStore()
    first = make_window(factory, database, store)
    # Sous Windows, la barre d'outils impose à la fenêtre une largeur minimale (environ 770 px) :
    # la taille demandée n'est pas toujours celle obtenue. On reproduit cette contrainte ici pour
    # que le test se comporte de la même façon partout, et on compare à la taille *obtenue*.
    first.setMinimumWidth(780)
    first.resize(733, 561)
    first._splitter.setSizes([150, 550])  # un partage très différent du partage par défaut
    obtained = (first.width(), first.height())
    assert obtained != (1250, 700)  # sinon le test ne prouverait rien
    first.close()

    assert store.settings.geometry("main") and store.settings.geometry("main_splitter")
    second = make_window(factory, database, store)
    assert (second.width(), second.height()) == obtained
    left, right = second._splitter.sizes()
    assert left / (left + right) < 0.28  # proportions conservées (par défaut : environ 0,34)


def test_the_main_window_starts_with_a_default_size_the_first_time(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(factory, database, SettingsStore())
    assert (window.width(), window.height()) == (1250, 700)


# --- Préférences : fenêtre ------------------------------------------------------------------


def test_preferences_dialog_shows_the_current_settings(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        schedule_horizon_months=8,
        backup_enabled=False,
        backup_keep=30,
        backup_dir=str(tmp_path / "c"),
    )
    dialog = PreferencesDialog(settings, database=tmp_path / "data" / "budget.sqlite")
    assert dialog._horizon.value() == 8
    assert not dialog._backup_enabled.isChecked()
    assert dialog._keep.value() == 30 and not dialog._keep.isEnabled()
    assert dialog._folder.text() == str(tmp_path / "c")
    assert str(tmp_path / "c") in dialog._effective.text()


def test_preferences_dialog_values_and_ranges(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dialog = PreferencesDialog(Settings(), database=tmp_path / "budget.sqlite")
    assert (dialog._horizon.minimum(), dialog._horizon.maximum()) == (1, 24)
    assert (dialog._keep.minimum(), dialog._keep.maximum()) == (1, 365)
    assert str(tmp_path / "sauvegardes") in dialog._effective.text()  # dossier par défaut annoncé

    dialog._horizon.setValue(12)
    dialog._keep.setValue(5)
    dialog._folder.setText("  /mnt/nuage  ")
    dialog.accept()

    values = dialog.values()
    assert (values.schedule_horizon_months, values.backup_keep) == (12, 5)
    assert values.backup_enabled is True and values.backup_dir == "/mnt/nuage"


def test_preferences_browse_button(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    dialog = PreferencesDialog(Settings(), database=tmp_path / "budget.sqlite")
    monkeypatch.setattr(
        preferences_dialog.QFileDialog, "getExistingDirectory", lambda *_a, **_k: "/choisi"
    )
    dialog._on_browse()
    assert dialog._folder.text() == "/choisi"

    monkeypatch.setattr(
        preferences_dialog.QFileDialog, "getExistingDirectory", lambda *_a, **_k: ""
    )
    dialog._on_browse()  # annulé : rien ne change
    assert dialog._folder.text() == "/choisi"


def test_preferences_without_a_database(qapp) -> None:  # type: ignore[no-untyped-def]
    dialog = PreferencesDialog(Settings())
    assert dialog._effective.text() == ""


# --- Préférences : fenêtre principale -------------------------------------------------------


def set_preferences(**changes: object):  # type: ignore[no-untyped-def]
    def fill(dialog: QDialog) -> None:
        assert isinstance(dialog, PreferencesDialog)
        if "horizon" in changes:
            dialog._horizon.setValue(int(changes["horizon"]))  # type: ignore[call-overload]
        if "keep" in changes:
            dialog._keep.setValue(int(changes["keep"]))  # type: ignore[call-overload]
        if "enabled" in changes:
            dialog._backup_enabled.setChecked(bool(changes["enabled"]))
        dialog.accept()

    answer_next_dialog(fill)


def test_preferences_are_applied_and_saved(
    qapp, factory: Factory, database: Path, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "settings.json"
    store = SettingsStore.load(path)
    window = make_window(factory, database, store)

    set_preferences(horizon=9, keep=3, enabled=False)
    window.act_preferences.trigger()

    assert (store.settings.schedule_horizon_months, store.settings.backup_keep) == (9, 3)
    assert store.settings.backup_enabled is False
    reloaded = SettingsStore.load(path).settings  # et bien écrit sur le disque
    assert (reloaded.schedule_horizon_months, reloaded.backup_keep) == (9, 3)
    assert window.statusBar().currentMessage() == "Préférences enregistrées."


def test_cancelling_the_preferences_changes_nothing(
    qapp, factory: Factory, database: Path, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "settings.json"
    window = make_window(factory, database, SettingsStore.load(path))

    def cancel(dialog: QDialog) -> None:
        assert isinstance(dialog, PreferencesDialog)
        dialog._horizon.setValue(20)
        dialog.reject()

    answer_next_dialog(cancel)
    window.act_preferences.trigger()

    assert window._store.settings.schedule_horizon_months == 3
    assert not path.exists()


def test_a_longer_horizon_creates_the_operations_right_away(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    account = make_account(factory)
    with unit_of_work(factory) as session:
        sch.create_schedule(session, ScheduleData(account, -500, Frequency.MONTHLY, D(2026, 3, 5)))
        sch.generate_due_transactions(session, today=TODAY)  # horizon par défaut : 3 mois
    window = make_window(factory, database, SettingsStore())
    window.refresh(select_account_id=account)
    assert window._register._model.rowCount() == 4  # mars à juin

    set_preferences(horizon=6)
    window.act_preferences.trigger()

    assert window._register._model.rowCount() == 7  # jusqu'à septembre : l'écran est à jour


def test_a_shorter_horizon_deletes_nothing(qapp, factory: Factory, database: Path) -> None:  # type: ignore[no-untyped-def]
    account = make_account(factory)
    with unit_of_work(factory) as session:
        sch.create_schedule(session, ScheduleData(account, -500, Frequency.MONTHLY, D(2026, 3, 5)))
        sch.generate_due_transactions(session, today=TODAY)
    window = make_window(factory, database, SettingsStore())

    set_preferences(horizon=1)
    window.act_preferences.trigger()

    with factory() as session:
        assert len(tx.list_transactions(session, account)) == 4


def test_a_failed_save_of_the_preferences_is_reported(
    qapp, factory: Factory, database: Path, tmp_path: Path, errors: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    blocked = tmp_path / "settings.json"
    blocked.mkdir()  # un dossier à la place du fichier : l'écriture échouera
    window = make_window(factory, database, SettingsStore(Settings(), blocked))

    set_preferences(keep=7)
    window.act_preferences.trigger()

    assert window._store.settings.backup_keep == 7  # appliqué pour cette session
    assert errors and errors[0][0] == "Préférences" and "disque" in errors[0][1]


def test_the_horizon_is_used_by_the_schedules_screen(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    from budget.services import schedules

    account = make_account(factory)
    dialog = SchedulesDialog(factory, today=TODAY, horizon_months=1)
    with unit_of_work(factory) as session:
        schedules.create_schedule(
            session, ScheduleData(account, -500, Frequency.MONTHLY, D(2026, 3, 1))
        )
    from tests.ui.test_schedules_ui import fill_new_rent

    answer_next_dialog(fill_new_rent(account))  # ajoute une 2e échéance via l'écran
    dialog._new.click()
    assert dialog._status.text() == "4 opérations générées."  # 2 + 2 : horizon d'un mois seulement


# --- Sauvegardes manuelles ------------------------------------------------------------------


def test_backup_now_creates_a_copy_in_the_default_folder(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    make_account(factory)
    window = make_window(factory, database, SettingsStore())

    window.act_backup_now.trigger()

    (info,) = backup.list_backups(database.parent / "sauvegardes")
    assert window.statusBar().currentMessage() == f"Sauvegarde créée : {info.path.name}"
    with sqlite3.connect(info.path) as copy:
        assert copy.execute("SELECT count(*) FROM accounts").fetchone() == (1,)


def test_backup_now_applies_the_rotation_and_says_so(
    qapp, factory: Factory, database: Path
) -> None:  # type: ignore[no-untyped-def]
    make_account(factory)
    store = SettingsStore(Settings(backup_keep=1))
    window = make_window(factory, database, store)

    window.act_backup_now.trigger()
    window.act_backup_now.trigger()

    assert len(backup.list_backups(database.parent / "sauvegardes")) == 1
    assert "1 ancienne supprimée" in window.statusBar().currentMessage()


def test_backup_now_uses_the_configured_folder(
    qapp, factory: Factory, database: Path, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    make_account(factory)
    elsewhere = tmp_path / "nuage"
    window = make_window(factory, database, SettingsStore(Settings(backup_dir=str(elsewhere))))
    window.act_backup_now.trigger()
    assert len(backup.list_backups(elsewhere)) == 1


def test_a_failed_backup_is_reported(
    qapp, factory: Factory, database: Path, tmp_path: Path, errors: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    make_account(factory)
    blocker = tmp_path / "copies"
    blocker.write_text("un fichier, pas un dossier")
    window = make_window(factory, database, SettingsStore(Settings(backup_dir=str(blocker))))

    window.act_backup_now.trigger()

    assert errors and errors[0][0] == "Sauvegarde" and "échoué" in errors[0][1]


def test_backup_now_without_a_database_file(
    qapp, factory: Factory, errors: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(factory, today=lambda: TODAY)  # aucun chemin de base fourni
    window.act_backup_now.trigger()
    assert errors and "Aucun fichier" in errors[0][1]


def test_open_the_backup_folder(
    qapp, factory: Factory, database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    opened: list[str] = []

    class FakeDesktopServices:
        @staticmethod
        def openUrl(url) -> bool:  # type: ignore[no-untyped-def]
            opened.append(url.toLocalFile())
            return True

    monkeypatch.setattr(main_window_module, "QDesktopServices", FakeDesktopServices)
    window = make_window(factory, database, SettingsStore())
    folder = database.parent / "sauvegardes"
    assert not folder.exists()

    window.act_open_backups.trigger()

    # QUrl.toLocalFile() renvoie des « / » même sous Windows : on compare des chemins,
    # pas des chaînes.
    assert [Path(url) for url in opened] == [folder]
    assert folder.is_dir()  # créé pour que l'explorateur ait quelque chose à ouvrir


# --- Rapport de démarrage -------------------------------------------------------------------


def test_startup_report_with_a_failed_backup(
    qapp, factory: Factory, database: Path, errors: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(factory, database)
    report = StartupReport(
        generation=sch.GenerationResult(created=0),
        backup=backup.BackupOutcome(error="disque plein"),
    )
    window.report_startup(report)
    assert errors[0][0] == "Sauvegarde" and "disque plein" in errors[0][1]


def test_startup_report_messages(
    qapp, factory: Factory, database: Path, errors: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(factory, database)

    window.report_startup(
        StartupReport(sch.GenerationResult(created=0), backup.BackupOutcome(path=Path("x.sqlite")))
    )
    assert window.statusBar().currentMessage() == "Sauvegarde du jour créée."

    window.report_startup(
        StartupReport(sch.GenerationResult(created=2), backup.BackupOutcome(path=Path("x.sqlite")))
    )
    assert "2 opérations créées" in window.statusBar().currentMessage()  # le plus utile d'abord

    window.statusBar().clearMessage()
    window.report_startup(
        StartupReport(
            sch.GenerationResult(created=0), backup.BackupOutcome(skipped_reason="déjà faite")
        )
    )
    assert window.statusBar().currentMessage() == "" and errors == []


# --- Test de fumée --------------------------------------------------------------------------


def test_smoke_test_fails_when_the_icon_is_missing(qapp) -> None:  # type: ignore[no-untyped-def]
    assert app_module._finish_smoke_test(qapp, QIcon()) == app_module.EXIT_MISSING_ICON


def test_smoke_test_runs_as_a_real_process(tmp_path: Path) -> None:
    """Lance l'application comme le fera la CI sur l'exécutable : elle doit démarrer et quitter."""
    config, data, database = tmp_path / "config", tmp_path / "data", tmp_path / "essai.sqlite"
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data),
    }

    result = subprocess.run(
        [sys.executable, "-m", "budget", "--smoke-test", "--base", str(database)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as connection:  # migrations appliquées : la dernière
        from alembic.script import ScriptDirectory

        from budget.db.migrate import _config

        head = ScriptDirectory.from_config(_config()).get_current_head()
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)
        assert connection.execute("SELECT count(*) FROM payment_methods").fetchone() == (5,)
    assert not (
        config / "budget-familial" / "settings.json"
    ).exists()  # rien d'écrit chez l'utilisateur


def test_a_saved_size_larger_than_the_screen_is_brought_back(qapp, factory: Factory) -> None:  # type: ignore[no-untyped-def]
    """Cas réel : la fenêtre a été agrandie sur un grand écran, qui n'est plus branché."""
    from PySide6.QtGui import QGuiApplication

    store = SettingsStore()
    first = CategoriesDialog(factory, store=store)
    first.resize(700, 400)
    first.done(0)
    screen = QGuiApplication.primaryScreen().availableGeometry()
    first.setGeometry(0, 0, screen.width() + 600, 400)  # plus large que l'écran actuel
    first.done(0)

    second = CategoriesDialog(factory, store=store)
    assert second.width() <= screen.width()  # Qt la ramène sur l'écran : jamais hors d'atteinte
