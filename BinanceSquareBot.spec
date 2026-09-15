# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path.cwd()

datas = []
for folder in ("assets", "dashboard"):
    root = project / folder
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file():
                rel_parent = path.parent.relative_to(project)
                datas.append((str(path), str(rel_parent)))

binaries = []
llama_root = project / "vendor" / "llama"
if llama_root.exists():
    for path in llama_root.rglob("*"):
        if path.is_file():
            rel_parent = Path("llama") / path.parent.relative_to(llama_root)
            binaries.append((str(path), str(rel_parent)))

hiddenimports = []
for path in project.glob("*.py"):
    name = path.stem
    if name == "desktop_app" or name.endswith("_test") or name in {"run_tests", "self_test"}:
        continue
    hiddenimports.append(name)

a = Analysis(
    [str(project / "desktop_app.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BinanceSquareBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
