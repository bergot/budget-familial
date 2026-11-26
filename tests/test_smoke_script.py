"""Le script de test de fumée de la CI (`packaging/smoke_test.py`) doit lui-même être fiable."""

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from budget.db.base import create_db_engine, make_session_factory, unit_of_work
from budget.db.migrate import upgrade_to_head
from budget.services.lookups import ensure_default_payment_methods

SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "smoke_test.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_test_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_database(path: Path) -> None:
    engine = create_db_engine(path)
    upgrade_to_head(engine)
    with unit_of_work(make_session_factory(engine)) as session:
        ensure_default_payment_methods(session)
    engine.dispose()


def test_the_script_reads_the_schema_state(tmp_path: Path) -> None:
    database = tmp_path / "essai.sqlite"
    make_database(database)

    version, methods = load_script().read_schema_state(database)

    assert version is not None and methods == 5


def test_the_script_closes_its_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Régression : une connexion laissée ouverte empêche, sous Windows, de supprimer le fichier.

    (Sous Linux on peut supprimer un fichier ouvert : le défaut n'y est pas visible. On vérifie
    donc directement que la connexion est fermée, ce qui est vrai sur tous les systèmes.)
    """
    database = tmp_path / "essai.sqlite"
    make_database(database)
    script = load_script()
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(connection)
        return connection

    monkeypatch.setattr(script.sqlite3, "connect", spy)

    script.read_schema_state(database)

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")  # une connexion fermée refuse toute requête
    database.unlink()  # et le fichier peut être supprimé


def test_the_script_rejects_a_missing_executable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert load_script().main(["smoke_test.py", str(tmp_path)]) == 1
    assert "introuvable" in capsys.readouterr().err
