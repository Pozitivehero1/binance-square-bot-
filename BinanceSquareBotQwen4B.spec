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

# Dedicated qwen3:4b build uses the user's installed Ollama model and therefore
# intentionally does NOT bundle llama.cpp or any model-downloader runtime.
binaries = []

hiddenimports = []
for path in project.glob("*.py"):
    name = path.stem
    if name == "desktop_app_qwen4b" or name.endswith("_test") or name in {"run_tests", "self_test"}:
        continue
    hiddenimports.append(name)

a = Analysis(
    [str(project / "desktop_app_qwen4b.py")],
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
    name="BinanceSquareBot-Qwen3-4B-FIX-R2",
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
