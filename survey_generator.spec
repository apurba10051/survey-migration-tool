# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Survey Flow Generator (macOS arm64 one-folder build).
Run:  pyinstaller survey_generator.spec
Requires: Python 3.11–3.14 on Apple Silicon (arm64).
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None

# ── Collect all data files needed at runtime ──────────────────────────────────
datas = []

# Jinja2 templates
datas += [("templates", "templates")]

# Package dist-info metadata — Streamlit reads its own metadata at startup.
# copy_metadata() is the PyInstaller-supported way (works on Python 3.12+).
for _pkg in ("streamlit", "altair", "pandas", "jinja2", "openpyxl", "pyarrow",
             "click", "rich", "packaging", "watchdog"):
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

# Application source files bundled as data (Streamlit loads them by path)
datas += [("survey_app.py",      ".")]
datas += [("survey_pipeline.py", ".")]
datas += [("generate_surveys.py",".")]
datas += [("veeva_to_lsc.py",    ".")]

# Streamlit static assets + component data
datas += collect_data_files("streamlit")
datas += collect_data_files("altair")
datas += collect_data_files("pandas")

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = (
    collect_submodules("streamlit")
    + collect_submodules("streamlit.web")
    + collect_submodules("streamlit.components")
    + collect_submodules("jinja2")
    + collect_submodules("pandas")
    + collect_submodules("openpyxl")
    + collect_submodules("pyarrow")
    + [
        "openpyxl.cell._writer",
        "openpyxl.styles.numbers",
        "altair",
        "pyarrow",
        "pyarrow.vendored.version",
        "PIL",
        "PIL.Image",
        "streamlit.runtime.scriptrunner.magic_funcs",
    ]
)

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["launcher.py"],
    pathex=[str(Path(".").resolve())],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "IPython", "notebook", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Survey Generator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,   # None = match the build machine; CI sets arm64 or x86_64 via runner
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Survey Generator",
)

# ── macOS .app bundle ──────────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name="Survey Generator.app",
    icon=None,
    bundle_identifier="com.lsc.survey-generator",
    info_plist={
        "CFBundleShortVersionString": "2.1.0",
        "CFBundleVersion":            "2.1.0",
        "NSHighResolutionCapable":    True,
        "LSBackgroundOnly":           False,
    },
)
