import json
from pathlib import Path

import pytest

from budget.settings import (
    HORIZON_MAX,
    HORIZON_MIN,
    KEEP_MAX,
    KEEP_MIN,
    Settings,
    SettingsStore,
    load_settings,
    save_settings,
)


def test_defaults() -> None:
    settings = Settings()
    assert settings.schedule_horizon_months == 3
    assert settings.backup_enabled is True
    assert settings.backup_keep == 14
    assert settings.backup_dir == ""
    assert settings.geometries == {}


def test_missing_or_unspecified_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(None) == Settings()
    assert load_settings(tmp_path / "absent.json") == Settings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(
        schedule_horizon_months=6,
        backup_enabled=False,
        backup_keep=30,
        backup_dir="/données/copies",
    )
    original.set_geometry("main", b"\x01\x02\xff")

    save_settings(original, path)

    assert load_settings(path) == original
    assert not list(tmp_path.glob("*.tmp"))  # aucun fichier temporaire ne traîne


def test_file_is_human_readable_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(Settings(backup_dir="Sauvegardes é"), path)
    text = path.read_text(encoding="utf-8")
    assert "Sauvegardes é" in text  # pas d'échappement inutile : ensure_ascii=False
    assert json.loads(text)["schedule_horizon_months"] == 3


def test_saving_creates_the_folder(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "settings.json"
    save_settings(Settings(), path)
    assert path.exists()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, HORIZON_MIN),
        (-5, HORIZON_MIN),
        (999, HORIZON_MAX),
        (12, 12),
        ("12", 3),
        (True, 3),
        (2.5, 3),
        (None, 3),
    ],
)
def test_horizon_is_checked(value: object, expected: int) -> None:
    assert (
        Settings.from_json({"schedule_horizon_months": value}).schedule_horizon_months == expected
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, KEEP_MIN), (10_000, KEEP_MAX), (7, 7), ("x", 14), (False, 14)],
)
def test_backup_keep_is_checked(value: object, expected: int) -> None:
    assert Settings.from_json({"backup_keep": value}).backup_keep == expected


def test_each_invalid_value_falls_back_on_its_own() -> None:
    settings = Settings.from_json(
        {
            "schedule_horizon_months": "beaucoup",  # invalide
            "backup_enabled": "oui",  # invalide : pas un booléen
            "backup_keep": 20,  # valide : conservé
            "backup_dir": 42,  # invalide
            "geometries": "pas un dictionnaire",  # invalide
        }
    )
    assert settings == Settings(backup_keep=20)


def test_unknown_keys_are_ignored() -> None:
    settings = Settings.from_json({"backup_keep": 5, "futur": {"a": 1}})
    assert settings.backup_keep == 5


def test_geometries_keep_only_text_entries() -> None:
    settings = Settings.from_json({"geometries": {"main": "AAEC", "bad": 3, 7: "x"}})
    assert settings.geometries == {"main": "AAEC"}


def test_geometry_round_trip_and_bad_data() -> None:
    settings = Settings()
    assert settings.geometry("main") is None
    settings.set_geometry("main", bytes(range(10)))
    assert settings.geometry("main") == bytes(range(10))
    settings.geometries["broken"] = "###pas du base64###"
    assert settings.geometry("broken") is None  # ne lève pas d'exception


@pytest.mark.parametrize("content", ["", "{pas du json", "[1, 2]", "42", "\x00\x01"])
def test_a_damaged_file_never_breaks_startup(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    assert load_settings(path) == Settings()

    # Le fichier abîmé est mis de côté plutôt que perdu ou écrasé.
    assert not path.exists()
    assert (tmp_path / "settings.json.corrompu").read_text(encoding="utf-8") == content


def test_an_unreadable_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe\xfa")  # pas de l'UTF-8
    assert load_settings(path) == Settings()


def test_store_without_a_file_writes_nothing(tmp_path: Path) -> None:
    store = SettingsStore()
    store.settings.backup_keep = 5
    assert store.save() is True
    assert list(tmp_path.iterdir()) == []


def test_store_saves_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore.load(path)  # fichier absent : valeurs par défaut
    store.settings.schedule_horizon_months = 9
    assert store.save() is True

    assert SettingsStore.load(path).settings.schedule_horizon_months == 9


def test_store_reports_a_failed_save_instead_of_raising(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.mkdir()  # un dossier à la place du fichier : l'écriture est impossible
    assert SettingsStore(Settings(), path).save() is False
