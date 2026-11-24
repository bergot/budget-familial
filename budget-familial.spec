# -*- mode: python ; coding: utf-8 -*-
# Construction de l'exécutable : uv run pyinstaller --noconfirm budget-familial.spec
#
# Deux dossiers de données doivent être déclarés dans `datas`, car PyInstaller ne les voit pas
# en analysant les imports :
# - les migrations Alembic : des fichiers .py chargés *par chemin* au démarrage ;
# - les ressources de l'interface : l'icône de la fenêtre (PNG).
# Les chemins sont écrits avec des « / », valables aussi sous Windows dans un .spec.
# Le test `tests/test_version.py` vérifie que ces deux déclarations sont bien là.
import sys

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("src/budget/db/migrations", "budget/db/migrations"),
        ("src/budget/ui/resources", "budget/ui/resources"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="budget-familial",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # application graphique : pas de fenêtre de terminal sous Windows
    # Icône du fichier .exe (explorateur, barre des tâches) : Windows seulement.
    icon="src/budget/ui/resources/icon.ico" if sys.platform == "win32" else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="budget-familial",
)
