"""Test de fumée de l'exécutable construit par PyInstaller.

    uv run python packaging/smoke_test.py dist/budget-familial

Lance l'exécutable avec `--smoke-test` (il démarre, ouvre une base neuve, affiche sa fenêtre,
vérifie son icône puis quitte), depuis un dossier quelconque et sur une base jetable, puis
contrôle la base qu'il a créée. Cela détecte les oublis classiques d'un exécutable gelé :
migrations ou icône non embarquées, bibliothèque manquante, dépendance au dossier courant.

Le script est identique sous Linux et Windows ; la CI le lance sur les deux.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 120
DEFAULT_PAYMENT_METHODS = 5


def fail(message: str) -> int:
    print(f"ÉCHEC : {message}", file=sys.stderr)
    return 1


def expected_head() -> str:
    """Dernière version du schéma attendue, lue dans le code source du dépôt."""
    from alembic.script import ScriptDirectory

    from budget.db.migrate import _config

    head = ScriptDirectory.from_config(_config()).get_current_head()
    assert head is not None
    return head


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return fail("usage : smoke_test.py <dossier de l'exécutable>")
    folder = Path(argv[1]).resolve()
    executable = folder / ("budget-familial.exe" if sys.platform == "win32" else "budget-familial")
    if not executable.is_file():
        return fail(f"exécutable introuvable : {executable}")

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        database = work / "essai.sqlite"
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",  # pas d'écran sur un serveur de CI
            # Isole les réglages et les données de l'utilisateur de la machine.
            "XDG_CONFIG_HOME": str(work / "config"),
            "XDG_DATA_HOME": str(work / "data"),
            "APPDATA": str(work / "appdata"),
            "LOCALAPPDATA": str(work / "localappdata"),
        }
        print(f"Lancement de {executable}")
        try:
            result = subprocess.run(
                [str(executable), "--smoke-test", "--base", str(database)],
                env=env,
                cwd=work,  # un autre dossier que celui du programme : il ne doit pas en dépendre
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return fail(f"l'exécutable n'a pas quitté en {TIMEOUT_SECONDS} s")

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode != 0:
            hint = " : l'icône n'est pas embarquée" if result.returncode == 3 else ""
            return fail(f"code de retour {result.returncode}{hint}")
        if not database.is_file():
            return fail("la base de données n'a pas été créée")

        head = expected_head()
        with sqlite3.connect(database) as connection:
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            methods = connection.execute("SELECT count(*) FROM payment_methods").fetchone()[0]
        if version != (head,):
            return fail(
                f"schéma en version {version}, attendu {head} : migrations mal embarquées ?"
            )
        if methods != DEFAULT_PAYMENT_METHODS:
            return fail(f"{methods} moyens de paiement créés, attendu {DEFAULT_PAYMENT_METHODS}")

    print(f"OK : l'exécutable démarre, crée sa base (schéma {head}) et trouve son icône.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
