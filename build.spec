# PyInstaller spec.
# Windows: a single windowed exe       ->  .venv\Scripts\pyinstaller build.spec --noconfirm
# Linux:   a folder for the AppImage   ->  tools/build_appimage.sh
# PyInstaller cannot cross-build: the Linux version has to be built on Linux.
# MKVToolNix is NOT bundled (PATH / default folder / asks for the path).

import runpy
import sys

from PyInstaller.utils.hooks import collect_data_files

WINDOWS = sys.platform == "win32"

# license texts matching the installed versions (shown in Settings -> About -> Info)
runpy.run_path("tools/collect_licenses.py", run_name="__main__")

datas = [("src/bmpe/resources", "bmpe/resources")]
datas += collect_data_files("qfluentwidgets")

EXCLUDES = [
    "tkinter", "unittest", "pydoc", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio",
    "PySide6.QtHttpServer", "PySide6.QtWebSockets", "PySide6.QtNetworkAuth", "PySide6.QtUiTools",
    "PySide6.QtAxContainer", "PySide6.QtConcurrent", "PySide6.QtCanvasPainter",
]

a = Analysis(
    ["run.py"],
    pathex=["src"],
    datas=datas,
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
if WINDOWS:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="pyBatchMKVPropEdit",
        console=False,
        icon="src/bmpe/resources/icon.ico",
        upx=False,
        runtime_tmpdir=None,
    )
else:
    # onedir: starts faster than a onefile build and is what the AppImage wraps
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="pybatchmkvpropedit",
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="pybatchmkvpropedit", upx=False)
