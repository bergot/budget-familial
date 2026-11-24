import subprocess
import sys
import tomllib
from pathlib import Path

import budget

ROOT = Path(__file__).resolve().parent.parent


def test_the_version_in_the_code_matches_pyproject() -> None:
    """La version est écrite à deux endroits (pyproject et code) : ce test les garde d'accord."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert budget.__version__ == pyproject["project"]["version"]


def test_version_option_prints_the_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "budget", "--version"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"Budget familial {budget.__version__}"


def test_the_spec_file_bundles_the_resources() -> None:
    """Oublier d'embarquer les icônes ou les migrations donne un exécutable qui ne démarre pas."""
    spec = (ROOT / "budget-familial.spec").read_text(encoding="utf-8")
    assert "budget/db/migrations" in spec
    assert "budget/ui/resources" in spec
