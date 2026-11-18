"""Entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__


def resource_path(name: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "bmpe" / "resources" / name
    return Path(__file__).resolve().parent / "resources" / name


def install_excepthook(log_dir: Path) -> None:
    """Writes unexpected errors to error.log and shows them (the exe has no console)."""
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "error.log", "a", encoding="utf-8") as fh:
                import datetime

                fh.write(f"\n--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n{text}")
        except OSError:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "Unexpected error",
                f"{exc_type.__name__}: {exc}\n\nDetails in {log_dir / 'error.log'}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def main() -> int:
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("pyBatchMKVPropEdit")
    app.setOrganizationName("pyBatchMKVPropEdit")
    app.setApplicationVersion(__version__)
    # Linux: lets the desktop (Wayland in particular) match the window to pybatchmkvpropedit.desktop
    app.setDesktopFileName("pybatchmkvpropedit")

    # import only after QApplication exists (qfluentwidgets needs it).
    # qfluentwidgets always prints an advertisement to the console on import; swallow it.
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        import qfluentwidgets  # noqa: F401
    from .ui.main_window import MainWindow
    from .ui.settings_page import apply_theme
    from .ui.state import AppState

    from .core.presets import default_base_dir

    install_excepthook(default_base_dir())
    state = AppState()
    apply_theme(state.settings.theme)
    icon_file = resource_path("icon.ico" if sys.platform == "win32" else "icon.png")
    icon = QIcon(str(icon_file)) if icon_file.exists() else None
    if icon:
        app.setWindowIcon(icon)
    win = MainWindow(state, icon)
    win.show()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        state.add_paths(args)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
