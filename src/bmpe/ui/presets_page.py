"""Presets page: manage, import and export global and track presets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)
from qfluentwidgets import FluentIcon as FIF

from ..core.models import GlobalPreset, TrackPreset
from ..core.presets import safe_filename
from .state import AppState
from .widgets.common import TextInputDialog, page_layout


class PresetsPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("presetsPage")
        lay = page_layout(self, "Presets")
        info = CaptionLabel(
            "Global presets store all settings (General, Attachments and every track rule). "
            "Track presets store the actions for a single track (optionally with the match) and are "
            "applied on the Tracks page.",
            self,
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        lay.addLayout(cols, 1)

        # ---------------- global
        g = QVBoxLayout()
        g.addWidget(StrongBodyLabel("Global presets", self))
        self.global_list = ListWidget(self)
        g.addWidget(self.global_list, 1)
        bar = QHBoxLayout()
        self.btn_g_load = PrimaryPushButton(FIF.DOWNLOAD, "Load", self)
        self.btn_g_rename = PushButton(FIF.EDIT, "Rename", self)
        self.btn_g_dup = PushButton(FIF.COPY, "Duplicate", self)
        self.btn_g_del = PushButton(FIF.DELETE, "Delete", self)
        self.btn_g_export = PushButton(FIF.SHARE, "Export", self)
        for b in (self.btn_g_load, self.btn_g_rename, self.btn_g_dup, self.btn_g_del, self.btn_g_export):
            bar.addWidget(b)
        bar.addStretch(1)
        g.addLayout(bar)
        cols.addLayout(g, 1)

        # ---------------- track
        t = QVBoxLayout()
        t.addWidget(StrongBodyLabel("Track presets", self))
        self.track_list = ListWidget(self)
        t.addWidget(self.track_list, 1)
        bar = QHBoxLayout()
        self.btn_t_rename = PushButton(FIF.EDIT, "Rename", self)
        self.btn_t_dup = PushButton(FIF.COPY, "Duplicate", self)
        self.btn_t_del = PushButton(FIF.DELETE, "Delete", self)
        self.btn_t_export = PushButton(FIF.SHARE, "Export", self)
        for b in (self.btn_t_rename, self.btn_t_dup, self.btn_t_del, self.btn_t_export):
            bar.addWidget(b)
        bar.addStretch(1)
        t.addLayout(bar)
        cols.addLayout(t, 1)

        foot = QHBoxLayout()
        self.btn_import = PushButton(FIF.FOLDER, "Import preset...", self)
        self.btn_open_dir = PushButton(FIF.FOLDER, "Open preset folder", self)
        foot.addWidget(self.btn_import)
        foot.addWidget(self.btn_open_dir)
        foot.addStretch(1)
        lay.addLayout(foot)

        self.btn_g_load.clicked.connect(self._load_global)
        self.global_list.itemDoubleClicked.connect(lambda _: self._load_global())
        self.btn_g_rename.clicked.connect(lambda: self._rename(True))
        self.btn_t_rename.clicked.connect(lambda: self._rename(False))
        self.btn_g_dup.clicked.connect(lambda: self._duplicate(True))
        self.btn_t_dup.clicked.connect(lambda: self._duplicate(False))
        self.btn_g_del.clicked.connect(lambda: self._delete(True))
        self.btn_t_del.clicked.connect(lambda: self._delete(False))
        self.btn_g_export.clicked.connect(lambda: self._export(True))
        self.btn_t_export.clicked.connect(lambda: self._export(False))
        self.btn_import.clicked.connect(self._import)
        self.btn_open_dir.clicked.connect(self._open_dir)
        state.presets_saved.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        self._fill(self.global_list, self.state.store.list_global(), True)
        self._fill(self.track_list, self.state.store.list_track(), False)

    def _fill(self, lst: ListWidget, presets, is_global: bool):
        cur = lst.currentItem().data(256) if lst.currentItem() else None
        lst.clear()
        for p in presets:
            if is_global:
                detail = f"{len(p.rules)} track rule(s)"
            else:
                detail = p.actions.describe()
                if p.matcher:
                    detail += f"  |  match: {p.matcher.describe()}"
            item = QListWidgetItem(f"{p.name}\n     {detail}")
            item.setData(256, p.name)
            item.setToolTip(detail)
            lst.addItem(item)
            if p.name == cur:
                lst.setCurrentItem(item)

    def _selected(self, is_global: bool) -> str | None:
        lst = self.global_list if is_global else self.track_list
        item = lst.currentItem()
        return item.data(256) if item else None

    def _toast(self, title, text="", error=False):
        (InfoBar.error if error else InfoBar.success)(title, text, duration=2500, parent=self.window())

    def _exists(self, name: str, is_global: bool) -> bool:
        s = self.state.store
        return s.has_global(name) if is_global else s.has_track(name)

    def _confirm(self, title: str, text: str) -> bool:
        box = MessageBox(title, text, self.window())
        box.yesButton.setText("Yes")
        box.cancelButton.setText("Cancel")
        return bool(box.exec())

    # ------------------------------------------------------------------ actions
    def _load_global(self):
        name = self._selected(True)
        if not name:
            return
        if self.state.modified and not self._confirm(
            "Unsaved changes", "The current settings were changed. Load anyway?"
        ):
            return
        self.state.load_preset(self.state.store.load_global(name), name)
        self._toast("Preset loaded", name)

    def _rename(self, is_global: bool):
        name = self._selected(is_global)
        if not name:
            return
        new = TextInputDialog.ask(self.window(), "Rename", "New name:", name)
        if not new or new == name:
            return
        if self._exists(new, is_global):
            if not self._confirm("Overwrite?", f"\"{new}\" already exists. Overwrite it?"):
                return
        store = self.state.store
        if is_global:
            store.rename_global(name, new)
            if self.state.preset_name == name:
                self.state.rename_current(new)
        else:
            store.rename_track(name, new)
        self.state.presets_saved.emit()

    def _duplicate(self, is_global: bool):
        name = self._selected(is_global)
        if not name:
            return
        new = TextInputDialog.ask(self.window(), "Duplicate", "Name of the copy:", f"{name} (copy)")
        if not new:
            return
        if self._exists(new, is_global) and not self._confirm(
            "Overwrite?", f"\"{new}\" already exists. Overwrite it?"
        ):
            return
        store = self.state.store
        if is_global:
            p = store.load_global(name)
            p.name = new
            store.save_global(p)
        else:
            p = store.load_track(name)
            p.name = new
            store.save_track(p)
        self.state.presets_saved.emit()

    def _delete(self, is_global: bool):
        name = self._selected(is_global)
        if not name or not self._confirm("Delete preset?", f"\"{name}\" will be deleted permanently."):
            return
        if is_global:
            self.state.store.delete_global(name)
        else:
            self.state.store.delete_track(name)
        self.state.presets_saved.emit()

    def _export(self, is_global: bool):
        name = self._selected(is_global)
        if not name:
            return
        store = self.state.store
        model = store.load_global(name) if is_global else store.load_track(name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export preset", str(Path.home() / f"{safe_filename(name)}.json"), "JSON (*.json)"
        )
        if path:
            store.export_to(model, Path(path))
            self._toast("Exported", path)

    def _import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import presets", str(Path.home()), "JSON (*.json)")
        store = self.state.store
        count = 0
        for f in files:
            try:
                model = store.import_file(Path(f))
            except Exception as e:  # noqa: BLE001
                self._toast("Import failed", f"{Path(f).name}: {e}", error=True)
                continue
            if not model.name:
                model.name = Path(f).stem
            is_global = isinstance(model, GlobalPreset)
            if self._exists(model.name, is_global) and not self._confirm(
                "Overwrite?", f"\"{model.name}\" already exists. Overwrite it?"
            ):
                continue
            if is_global:
                store.save_global(model)
            elif isinstance(model, TrackPreset):
                store.save_track(model)
            count += 1
        if count:
            self.state.presets_saved.emit()
            self._toast("Imported", f"{count} preset(s)")

    def _open_dir(self):
        folder = self.state.store.base / "presets"
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
