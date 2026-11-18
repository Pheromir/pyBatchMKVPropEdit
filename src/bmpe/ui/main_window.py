"""Main window with navigation and a preset bar in the title bar."""

from __future__ import annotations

from PySide6.QtCore import QDir, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentWindow,
    InfoBar,
    MessageBox,
    NavigationItemPosition,
    ToolButton,
    ToolTipFilter,
)
from qfluentwidgets import FluentIcon as FIF

from ..core.mkvtoolnix import dir_has_tools
from .attachments_page import AttachmentsPage
from .files_page import FilesPage
from .general_page import GeneralPage
from .presets_page import PresetsPage
from .run_page import RunPage
from .settings_page import SettingsPage
from .state import AppState
from .tracks_page import TracksPage
from .widgets.common import TextInputDialog

NO_PRESET = "(no preset)"


class PresetBar(QWidget):
    def __init__(self, state: AppState, window, parent=None):
        super().__init__(parent)
        self.state = state
        self.win = window
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(BodyLabel("Preset:", self))
        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(240)
        lay.addWidget(self.combo)
        self.dirty = BodyLabel("", self)
        self.dirty.setFixedWidth(90)
        self.btn_new = ToolButton(FIF.ADD, self)
        self.btn_save = ToolButton(FIF.SAVE, self)
        self.btn_save_as = ToolButton(FIF.SAVE_AS, self)
        for b, tip in (
            (self.btn_new, "New empty preset"),
            (self.btn_save, "Save preset"),
            (self.btn_save_as, "Save preset as..."),
        ):
            b.setToolTip(tip)
            b.installEventFilter(ToolTipFilter(b))
            b.setFixedSize(QSize(32, 32))
            lay.addWidget(b)
        lay.addWidget(self.dirty)

        self.combo.currentIndexChanged.connect(self._on_select)
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_save_as.clicked.connect(self._save_as)
        state.presets_saved.connect(self.refresh)
        state.preset_meta_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        names = [p.name for p in self.state.store.list_global()]
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(NO_PRESET, userData="")
        for n in names:
            self.combo.addItem(n, userData=n)
        idx = self.combo.findData(self.state.preset_name) if self.state.preset_name in names else 0
        self.combo.setCurrentIndex(max(idx, 0))
        self.combo.blockSignals(False)
        self.dirty.setText("● modified" if self.state.modified else "")

    def _confirm_discard(self) -> bool:
        if not self.state.modified:
            return True
        box = MessageBox(
            "Unsaved changes",
            "The current settings were changed since they were last saved. Discard them?",
            self.win,
        )
        box.yesButton.setText("Discard")
        box.cancelButton.setText("Cancel")
        return bool(box.exec())

    def _on_select(self, _):
        name = self.combo.currentData()
        if name == self.state.preset_name:
            return
        if not self._confirm_discard():
            self.refresh()
            return
        if not name:
            self.state.new_preset()
            return
        try:
            self.state.load_preset(self.state.store.load_global(name), name)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("Could not load preset", str(e), parent=self.win)
            self.refresh()

    def _new(self):
        if self._confirm_discard():
            self.state.new_preset()

    def _save(self):
        if not self.state.preset_name:
            self._save_as()
            return
        self.state.save_preset_as(self.state.preset_name)
        InfoBar.success("Saved", self.state.preset_name, duration=2000, parent=self.win)

    def _save_as(self):
        name = TextInputDialog.ask(
            self.win, "Save global preset", "Name (an existing name is overwritten):", self.state.preset_name
        )
        if name:
            self.state.save_preset_as(name)
            InfoBar.success("Saved", name, duration=2000, parent=self.win)


class MainWindow(FluentWindow):
    def __init__(self, state: AppState, icon: QIcon | None = None):
        super().__init__()
        self.state = state
        self.setWindowTitle("pyBatchMKVPropEdit")
        if icon:
            self.setWindowIcon(icon)
        self.resize(1360, 900)
        self.setMinimumSize(1000, 680)

        self.files_page = FilesPage(state, self)
        self.tracks_page = TracksPage(state, self)
        self.general_page = GeneralPage(state, self)
        self.attachments_page = AttachmentsPage(state, self)
        self.run_page = RunPage(state, self)
        self.presets_page = PresetsPage(state, self)
        self.settings_page = SettingsPage(state, self)

        self.addSubInterface(self.files_page, FIF.FOLDER, "Files")
        self.addSubInterface(self.tracks_page, FIF.MEDIA, "Tracks")
        self.addSubInterface(self.general_page, FIF.INFO, "General")
        self.addSubInterface(self.attachments_page, FIF.FONT, "Attachments")
        self.addSubInterface(self.run_page, FIF.PLAY, "Preview & run")
        self.addSubInterface(self.presets_page, FIF.LIBRARY, "Presets", NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settings_page, FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(220)

        self.preset_bar = PresetBar(state, self, self.titleBar)
        self.titleBar.hBoxLayout.insertWidget(2, self.preset_bar, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self._closing = False  # close was requested during a run; done as soon as the run has ended
        self.run_page.run_finished.connect(self._on_run_finished)

        QTimer.singleShot(300, self.ensure_tools)

    def ensure_tools(self):
        """Asks for the MKVToolNix folder if neither PATH nor the default folder provides it."""
        while not self.state.tools_ok:
            box = MessageBox(
                "MKVToolNix not found",
                "mkvmerge and mkvpropedit were found neither in PATH nor in the default installation folder."
                "\n\nPlease choose the MKVToolNix folder (it will be saved in the settings).",
                self,
            )
            box.yesButton.setText("Choose folder...")
            box.cancelButton.setText("Later")
            if not box.exec():
                InfoBar.warning(
                    "No MKVToolNix",
                    "Files can only be read once the path is set in the settings.",
                    duration=5000,
                    parent=self,
                )
                return
            folder = QFileDialog.getExistingDirectory(self, "Choose MKVToolNix folder")
            if not folder:
                continue
            folder = QDir.toNativeSeparators(folder)
            if dir_has_tools(folder):
                self.state.set_mkvtoolnix_dir(folder)
                self.state.reprobe([f.path for f in self.state.files if f.error])
            else:
                InfoBar.error(
                    "Invalid folder",
                    "That folder does not contain mkvmerge/mkvpropedit.",
                    duration=3000,
                    parent=self,
                )

    def _on_run_finished(self):
        if self._closing:
            self.close()

    def closeEvent(self, e):
        if self.run_page.running:
            # never leave while mkvpropedit is writing: wait for the file in progress, skip the rest
            e.ignore()
            if self._closing:
                return
            box = MessageBox(
                "Run in progress",
                "mkvpropedit is still working. The file that is being written right now will be finished, "
                "all remaining files are skipped, and then the window closes.",
                self,
            )
            box.yesButton.setText("Stop and close")
            box.cancelButton.setText("Keep running")
            if not box.exec():
                return
            if self.run_page.running:
                self._closing = True
                self.run_page.cancel_run()
                InfoBar.info("Closing", "Waiting for the file in progress...", duration=-1, parent=self)
            else:  # the run ended while the question was open
                QTimer.singleShot(0, self.close)
            return
        try:
            self.state.store.save_autosave(self.state.preset)
            self.state.store.save_settings(self.state.settings)
        finally:
            super().closeEvent(e)
