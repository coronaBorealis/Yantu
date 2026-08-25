from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


ROOT = Path(SPECPATH).resolve().parent
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

datas = collect_data_files("yantu", include_py_files=False)
datas += copy_metadata("pywebview")
datas += copy_metadata("keyring")

# Conda keeps Python extension dependencies in Library/bin. PyInstaller can
# discover the .pyd files but does not always resolve these sibling DLLs.
binaries = []
conda_bin = Path(sys.prefix) / "Library" / "bin"
for dll_name in (
    "ffi.dll",
    "libbz2.dll",
    "libcrypto-3-x64.dll",
    "libexpat.dll",
    "liblzma.dll",
    "libssl-3-x64.dll",
    "sqlite3.dll",
):
    candidate = conda_bin / dll_name
    if candidate.is_file():
        binaries.append((str(candidate), "."))

hiddenimports = [
    "keyring.backends.Windows",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

excluded = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "webview.platforms.android",
    "webview.platforms.cef",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
    "paddle",
    "paddleocr",
    "cv2",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "matplotlib",
    "pytest",
    "torch",
    "torchvision",
    "transformers",
    "onnxruntime",
    "ruamel",
]

a = Analysis(
    [str(ROOT / "packaging" / "yantu_desktop.py")],
    pathex=[str(SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Yantu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "src" / "yantu" / "web" / "assets" / "yantu.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Yantu",
)
