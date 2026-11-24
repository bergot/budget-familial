"""Icône de l'application."""

from pathlib import Path

from PySide6.QtGui import QIcon

RESOURCES_DIR = Path(__file__).parent / "resources"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def load_app_icon() -> QIcon:
    """Icône multi-tailles (Qt choisit la plus adaptée). Vide si les fichiers manquent."""
    icon = QIcon()
    for size in ICON_SIZES:
        path = RESOURCES_DIR / f"icon-{size}.png"
        if path.is_file():
            icon.addFile(str(path))
    return icon
