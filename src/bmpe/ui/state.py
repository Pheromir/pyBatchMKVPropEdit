"""Central application state: files, current preset, settings, tool paths."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.languages import Language, load_languages
from ..core.mkvtoolnix import ToolLocation, find_tools
from ..core.models import FileInfo, GlobalPreset
from ..core.presets import PresetStore
from ..core.probe import collect_files, probe


class AppState(QObject):
    files_changed = Signal()  # list (order/content) changed
    file_updated = Signal(str)  # one file was probed again
    probing_changed = Signal(bool)
    preset_replaced = Signal()  # a whole new preset was loaded -> refill the UI
    preset_edited = Signal()  # small change to the current preset
    preset_meta_changed = Signal()  # name / modified state
    presets_saved = Signal()  # preset list on disk changed
    settings_changed = Signal()
    tools_changed = Signal()
    _collected = Signal(object)
    _probed = Signal(object)
    _probe_done = Signal()

    def __init__(self, store: PresetStore | None = None):
        super().__init__()
        self.store = store or PresetStore()
        self.settings = self.store.load_settings()
        self.files: list[FileInfo] = []
        self.pending: set[str] = set()
        self.preset: GlobalPreset = self.store.load_autosave() or GlobalPreset()
        self.preset_name: str = self.settings.last_preset
        # unsaved changes survive a restart through the autosave, so the marker has to as well
        self.modified = self.settings.preset_modified
        self.mkvmerge: ToolLocation | None = None
        self.mkvpropedit: ToolLocation | None = None
        self._languages: list[Language] | None = None
        self._probe_jobs = 0

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(800)
        self._autosave.timeout.connect(lambda: self.store.save_autosave(self.preset))
        self._collected.connect(self._on_collected)
        self._probed.connect(self._on_probed)
        self._probe_done.connect(self._end_job)
        self.refresh_tools()

    # ------------------------------------------------------------------ Tools
    def refresh_tools(self) -> None:
        tools = find_tools(self.settings.mkvtoolnix_dir)
        self.mkvmerge = tools["mkvmerge"]
        self.mkvpropedit = tools["mkvpropedit"]
        self._languages = None
        self.tools_changed.emit()

    def languages(self) -> list[Language]:
        if self._languages is None:
            self._languages = load_languages(self.mkvmerge.path if self.mkvmerge else None)
        return self._languages

    @property
    def tools_ok(self) -> bool:
        return self.mkvmerge is not None and self.mkvpropedit is not None

    def set_mkvtoolnix_dir(self, folder: str) -> None:
        self.settings.mkvtoolnix_dir = folder
        self.store.save_settings(self.settings)
        self.refresh_tools()
        self.settings_changed.emit()

    # ------------------------------------------------------------------ settings
    def save_settings(self) -> None:
        self.store.save_settings(self.settings)
        self.settings_changed.emit()

    # ------------------------------------------------------------------ Preset
    def _set_saved_state(self, name: str, modified: bool) -> None:
        self.preset_name = name
        self.modified = modified
        self.settings.last_preset = name
        self.settings.preset_modified = modified
        self.store.save_settings(self.settings)

    def mark_dirty(self) -> None:
        self._autosave.start()
        if not self.modified:
            self._set_saved_state(self.preset_name, True)
            self.preset_meta_changed.emit()
        self.preset_edited.emit()

    def rename_current(self, name: str) -> None:
        """The loaded preset was renamed on disk."""
        self.preset.name = name
        self._set_saved_state(name, self.modified)
        self.preset_meta_changed.emit()

    def load_preset(self, preset: GlobalPreset, name: str = "") -> None:
        self.preset = preset.model_copy(deep=True)
        self._set_saved_state(name, False)
        self.store.save_autosave(self.preset)
        self.preset_replaced.emit()
        self.preset_meta_changed.emit()
        self.preset_edited.emit()

    def new_preset(self) -> None:
        self.load_preset(GlobalPreset(), "")

    def save_preset_as(self, name: str) -> None:
        self.preset.name = name
        self.store.save_global(self.preset)
        self._set_saved_state(name, False)
        self.preset_meta_changed.emit()
        self.presets_saved.emit()

    # ------------------------------------------------------------------ files
    @property
    def probing(self) -> bool:
        return self._probe_jobs > 0

    def _begin_job(self) -> None:
        self._probe_jobs += 1
        if self._probe_jobs == 1:
            self.probing_changed.emit(True)

    def _end_job(self) -> None:
        self._probe_jobs -= 1
        if self._probe_jobs == 0:
            self.probing_changed.emit(False)
            self.files_changed.emit()

    def add_paths(self, paths: list[str]) -> None:
        """Adds files and the MKVs inside folders; the folders are searched in the background."""
        paths = list(paths)
        recursive = self.settings.recursive
        self._begin_job()

        def work():
            self._collected.emit(collect_files(paths, recursive))

        threading.Thread(target=work, daemon=True).start()

    def _on_collected(self, files: list[str]) -> None:
        # normcase: case-insensitive on Windows, case-sensitive on Linux
        known = {os.path.normcase(f.path) for f in self.files}
        new = []
        for p in files:
            key = os.path.normcase(p)
            if key not in known:
                known.add(key)
                new.append(p)
        if new:
            for p in new:
                self.files.append(FileInfo(path=p))
                self.pending.add(p)
            self.files_changed.emit()
            self._probe(new)
        self._end_job()

    def reprobe(self, paths: list[str] | None = None) -> None:
        paths = paths if paths is not None else [f.path for f in self.files]
        paths = [p for p in paths if p not in self.pending]
        if not paths:
            return
        self.pending.update(paths)
        for p in paths:
            self.file_updated.emit(p)
        self._probe(paths, use_cache=False)

    def _probe(self, paths: list[str], use_cache: bool = True) -> None:
        if not self.mkvmerge:
            for p in paths:
                self._on_probed(FileInfo(path=p, error="mkvmerge not found (check the settings)"))
            return
        exe = self.mkvmerge.path
        self._begin_job()

        def work():
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=4) as pool:
                for info in pool.map(lambda p: probe(exe, p, use_cache), paths):
                    self._probed.emit(info)
            self._probe_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _on_probed(self, info: FileInfo) -> None:
        self.pending.discard(info.path)
        for i, f in enumerate(self.files):
            if f.path == info.path:
                self.files[i] = info
                self.file_updated.emit(info.path)
                break

    def remove_files(self, paths: set[str]) -> None:
        self.files = [f for f in self.files if f.path not in paths]
        self.files_changed.emit()

    def clear_files(self) -> None:
        self.files = []
        self.files_changed.emit()

    def move_files(self, paths: set[str], delta: int) -> None:
        idx = [i for i, f in enumerate(self.files) if f.path in paths]
        if not idx:
            return
        order = idx if delta < 0 else list(reversed(idx))
        for i in order:
            j = i + delta
            if 0 <= j < len(self.files) and self.files[j].path not in paths:
                self.files[i], self.files[j] = self.files[j], self.files[i]
        self.files_changed.emit()

    def move_files_to(self, paths: set[str], index: int) -> None:
        """Moves the given files, keeping their order, in front of the file that is at `index` now."""
        moving = [f for f in self.files if f.path in paths]
        if not moving:
            return
        at = sum(1 for f in self.files[:index] if f.path not in paths)
        rest = [f for f in self.files if f.path not in paths]
        files = rest[:at] + moving + rest[at:]
        if [f.path for f in files] != [f.path for f in self.files]:
            self.files = files
            self.files_changed.emit()

    def sort_files(self) -> None:
        self.files.sort(key=lambda f: f.path.lower())
        self.files_changed.emit()

    def ready_files(self) -> list[FileInfo]:
        return [f for f in self.files if f.path not in self.pending]
