"""PyInstaller build for a standalone Habit Tracker desktop app.

Build with all optional GUI extras installed:

    python -m pip install -e ".[all,build]"
    pyinstaller habit_tracker.spec

The entry script is ``build_gui.py`` rather than ``habit_tracker/gui.py``:
PyInstaller runs its entry script as a top-level ``__main__``, which would break
every relative import inside the package.

The result is a single ``dist/HabitTracker.exe`` (or ``dist/HabitTracker``) that
needs no Python install. The terminal interface is better installed with pip
(``pipx install habit-tracker``) and used via the ``ht`` command.
"""

import importlib.util

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Optional extras that PyInstaller's static analysis cannot see, because the
# application imports them inside try/except blocks. The window's colours come
# from habit_tracker.theme, so there is no theming package to bundle.
OPTIONAL_PACKAGES = (
    "tkcalendar",
    "dateparser",
    "platformdirs",
    "rich",
    "textual",
)


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


datas = []
binaries = []
hiddenimports = []

for package in OPTIONAL_PACKAGES:
    if not _installed(package):
        continue
    if package in ("tkcalendar", "dateparser"):
        found_datas, found_binaries, found_hidden = collect_all(package)
        datas += found_datas
        binaries += found_binaries
        hiddenimports += found_hidden
    else:
        hiddenimports += collect_submodules(package)

hiddenimports += ["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.simpledialog"]

a = Analysis(
    # Not "habit_tracker/gui.py": PyInstaller runs the entry script as a
    # top-level __main__, which breaks the package's relative imports.
    ["build_gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HabitTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
