"""Régénère les icônes de l'application à partir de `icon.svg`.

    uv run python packaging/make_icons.py

Produit dans `src/budget/ui/resources/` :
- `icon-<taille>.png` : pour la fenêtre (Linux, Windows) ;
- `icon.ico` : pour l'exécutable Windows (plusieurs tailles dans un seul fichier).

Le rendu utilise QtSvg (livré avec PySide6) : aucune autre dépendance. Le format `.ico` est écrit
à la main : un en-tête, un répertoire des images, puis les images PNG elles-mêmes (le format
ICO accepte le PNG depuis Windows Vista).
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "budget" / "ui" / "resources"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    header = struct.pack("<HHH", 0, 1, len(images))  # réservé, type 1 = icône, nombre d'images
    offset = 6 + 16 * len(images)
    directory = b""
    for size, data in images:
        side = 0 if size >= 256 else size  # 0 signifie 256 dans le format ICO
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + directory + b"".join(data for _, data in images))


def main() -> int:
    _app = QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(RESOURCES / "icon.svg"))
    if not renderer.isValid():
        print("icon.svg est invalide", file=sys.stderr)
        return 1
    for size in PNG_SIZES:
        (RESOURCES / f"icon-{size}.png").write_bytes(png_bytes(render(renderer, size)))
    write_ico(RESOURCES / "icon.ico", [(s, png_bytes(render(renderer, s))) for s in ICO_SIZES])
    print(f"Icônes écrites dans {RESOURCES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
