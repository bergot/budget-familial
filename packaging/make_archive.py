"""Crée l'archive de distribution à partir du dossier construit par PyInstaller.

    uv run python packaging/make_archive.py dist/budget-familial

- Linux : `budget-familial-<version>-linux-<arch>.tar.gz` (conserve les droits d'exécution) ;
- Windows : `budget-familial-<version>-windows-<arch>.zip`.

L'archive est écrite à côté du dossier ; son chemin est affiché sur la dernière ligne.
"""

import platform
import shutil
import sys
from pathlib import Path

from budget import __version__


def archive_base_name() -> tuple[str, str]:
    """Nom de l'archive (sans extension) et format `shutil`, selon le système."""
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("arm64", "aarch64")
    if sys.platform == "win32":
        return f"budget-familial-{__version__}-windows-{machine}", "zip"
    return f"budget-familial-{__version__}-linux-{machine}", "gztar"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage : make_archive.py <dossier construit>", file=sys.stderr)
        return 1
    folder = Path(argv[1]).resolve()
    if not folder.is_dir():
        print(f"dossier introuvable : {folder}", file=sys.stderr)
        return 1
    name, archive_format = archive_base_name()
    # root_dir = parent, base_dir = nom du dossier : l'archive contient `budget-familial/...`.
    path = shutil.make_archive(
        str(folder.parent / name), archive_format, root_dir=folder.parent, base_dir=folder.name
    )
    print(Path(path).as_posix())  # des « / » : pas de souci d'échappement sous Windows
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
