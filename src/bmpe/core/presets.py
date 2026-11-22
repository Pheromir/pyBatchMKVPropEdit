"""Stores global presets, track presets and app settings as JSON."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .models import AppSettings, GlobalPreset, SourceMode, TrackActions, TrackPreset

APP_NAME = "pyBatchMKVPropEdit"
# device names Windows does not allow as a file name, with or without an extension
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# unreadable, not UTF-8, not JSON or not matching the model (ValidationError is a ValueError)
READ_ERRORS = (OSError, ValueError)

T = TypeVar("T", bound=BaseModel)
P = TypeVar("P", GlobalPreset, TrackPreset)


def default_base_dir() -> Path:
    """Folder for settings and presets."""
    root = Path(os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / APP_NAME


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "preset"
    if cleaned.split(".")[0].strip().upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned


def external_references(preset: GlobalPreset | TrackPreset) -> list[str]:
    """Local files a preset reads and free parameters it passes to mkvpropedit.

    A preset from someone else could use them to copy a private file into the MKVs (as an attachment, for
    example), so they are shown before such a preset is imported.
    """
    out: list[str] = []
    actions: list[tuple[str, TrackActions]] = []
    if isinstance(preset, GlobalPreset):
        g = preset.general
        for kind, src in (("Chapters", g.chapters), ("Tags", g.tags)):
            if src.mode == SourceMode.FILE and src.file_path.strip():
                out.append(f"{kind} from {src.file_path}")
        for a in preset.attachments.add:
            out.append(f"Add attachment {a.path}" + (f' named "{a.name}"' if a.name.strip() else ""))
        for r in preset.attachments.replace:
            out.append(f"Replace attachment {r.value} with {r.path}")
        if g.extra_args.strip():
            out.append(f"Extra parameters: {g.extra_args.strip()}")
        actions = [(f"rule '{rule.display_label}'", rule.actions) for rule in preset.rules]
    else:
        actions = [("the track preset", preset.actions)]
    for where, a in actions:
        if a.extra_args.strip():
            out.append(f"Extra parameters of {where}: {a.extra_args.strip()}")
    return out


class PresetStore:
    """Presets are identified by the name stored inside the file; the file name is only derived from it.

    Different names can lead to the same file name ("DE/JP" and "DE:JP", or "anime" and "Anime" on
    Windows), so a preset is always looked up by its content and never overwritten by another name.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base = Path(base_dir) if base_dir else default_base_dir()
        self.global_dir = self.base / "presets" / "global"
        self.track_dir = self.base / "presets" / "track"
        self.settings_path = self.base / "settings.json"
        self.autosave_path = self.base / "autosave.json"
        for d in (self.global_dir, self.track_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _write(path: Path, model: BaseModel) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _read(path: Path, cls: type[T]) -> T:
        # utf-8-sig: editors like Notepad put a BOM in front
        return cls.model_validate_json(path.read_text(encoding="utf-8-sig"))

    def _list(self, folder: Path, cls: type[P]) -> list[P]:
        items: list[P] = []
        for f in folder.glob("*.json"):
            try:
                items.append(self._read(f, cls))
            except READ_ERRORS:
                continue
        return sorted(items, key=lambda p: p.name.lower())

    def _find(self, folder: Path, cls: type[P], name: str) -> Path | None:
        """The file that holds the preset called `name`."""
        direct = folder / f"{safe_filename(name)}.json"
        others = sorted(f for f in folder.glob("*.json") if f.name.lower() != direct.name.lower())
        for f in (direct, *others):
            try:
                if self._read(f, cls).name == name:
                    return f
            except READ_ERRORS:
                continue
        return None

    @staticmethod
    def _free_path(folder: Path, name: str) -> Path:
        base = safe_filename(name)
        path = folder / f"{base}.json"
        n = 2
        while path.exists():
            path = folder / f"{base} ({n}).json"
            n += 1
        return path

    def _save(self, folder: Path, preset: P) -> Path:
        path = self._find(folder, type(preset), preset.name) or self._free_path(folder, preset.name)
        self._write(path, preset)
        return path

    def _load(self, folder: Path, cls: type[P], name: str) -> P:
        path = self._find(folder, cls, name)
        if path is None:
            raise FileNotFoundError(f"Preset \"{name}\" not found in {folder}")
        return self._read(path, cls)

    def _delete(self, folder: Path, cls: type[P], name: str) -> None:
        path = self._find(folder, cls, name)
        if path is not None:
            path.unlink(missing_ok=True)

    def _rename(self, folder: Path, cls: type[P], old: str, new: str) -> P:
        src = self._find(folder, cls, old)
        if src is None:
            raise FileNotFoundError(f"Preset \"{old}\" not found in {folder}")
        preset = self._read(src, cls)
        if new == old:
            return preset
        preset.name = new
        taken = self._find(folder, cls, new)  # another preset with the new name gets replaced
        if taken is not None:
            self._write(taken, preset)
            src.unlink(missing_ok=True)
            return preset
        self._write(src, preset)
        # let the file name follow the new name; src stays where it is if that name is taken
        wanted = folder / f"{safe_filename(new)}.json"
        if wanted.name != src.name and (not wanted.exists() or wanted.samefile(src)):
            os.replace(src, wanted)
        return preset

    # ---------------------------------------------------------------- global presets
    def list_global(self) -> list[GlobalPreset]:
        return self._list(self.global_dir, GlobalPreset)

    def has_global(self, name: str) -> bool:
        return self._find(self.global_dir, GlobalPreset, name) is not None

    def save_global(self, preset: GlobalPreset) -> Path:
        return self._save(self.global_dir, preset)

    def load_global(self, name: str) -> GlobalPreset:
        return self._load(self.global_dir, GlobalPreset, name)

    def delete_global(self, name: str) -> None:
        self._delete(self.global_dir, GlobalPreset, name)

    def rename_global(self, old: str, new: str) -> GlobalPreset:
        return self._rename(self.global_dir, GlobalPreset, old, new)

    # ---------------------------------------------------------------- track presets
    def list_track(self) -> list[TrackPreset]:
        return self._list(self.track_dir, TrackPreset)

    def has_track(self, name: str) -> bool:
        return self._find(self.track_dir, TrackPreset, name) is not None

    def save_track(self, preset: TrackPreset) -> Path:
        return self._save(self.track_dir, preset)

    def load_track(self, name: str) -> TrackPreset:
        return self._load(self.track_dir, TrackPreset, name)

    def delete_track(self, name: str) -> None:
        self._delete(self.track_dir, TrackPreset, name)

    def rename_track(self, old: str, new: str) -> TrackPreset:
        return self._rename(self.track_dir, TrackPreset, old, new)

    # ---------------------------------------------------------------- Import/Export
    def export_to(self, model: BaseModel, path: Path) -> None:
        self._write(Path(path), model)

    @staticmethod
    def import_file(path: Path) -> GlobalPreset | TrackPreset:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not a preset file")
        if "rules" in data or "general" in data:
            return GlobalPreset.model_validate(data)
        return TrackPreset.model_validate(data)

    # ---------------------------------------------------------------- settings / autosave
    def load_settings(self) -> AppSettings:
        try:
            return self._read(self.settings_path, AppSettings)
        except READ_ERRORS:
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self._write(self.settings_path, settings)

    def load_autosave(self) -> GlobalPreset | None:
        try:
            return self._read(self.autosave_path, GlobalPreset)
        except READ_ERRORS:
            return None

    def save_autosave(self, preset: GlobalPreset) -> None:
        self._write(self.autosave_path, preset)
