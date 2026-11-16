# -*- mode: python ; coding: utf-8 -*-
# Construction de l'exécutable : uv run pyinstaller --noconfirm budget-familial.spec
#
# Les migrations Alembic sont des fichiers .py chargés *par chemin* au démarrage :
# PyInstaller ne les voit pas en analysant les imports, il faut les déclarer dans `datas`.
# Les chemins sont écrits avec des « / », valables aussi sous Windows dans un .spec.

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[("src/budget/db/migrations", "budget/db/migrations")],
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="budget-familial",
)
