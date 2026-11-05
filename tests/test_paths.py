from pathlib import Path

from budget import paths


def test_database_file_is_a_sqlite_path_inside_data_dir(tmp_path: Path, monkeypatch) -> None:
    # On redirige le dossier de données pour ne pas toucher au vrai profil.
    monkeypatch.setattr(paths, "user_data_path", lambda *args, **kwargs: tmp_path)

    db = paths.database_file()

    assert db.parent == tmp_path
    assert db.name == "budget.sqlite"
