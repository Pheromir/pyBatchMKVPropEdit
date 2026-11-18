"""License texts of pyBatchMKVPropEdit and the bundled libraries (created by tools/collect_licenses.py)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path


def license_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "bmpe" / "resources" / "licenses"
    return Path(__file__).resolve().parents[1] / "resources" / "licenses"


@dataclass
class LicenseEntry:
    name: str
    version: str
    license: str
    url: str = ""
    note: str = ""
    files: list[str] = field(default_factory=list)

    def text(self, folder: Path | None = None) -> str:
        folder = folder or license_dir()
        parts = [self.note] if self.note else []
        for name in self.files:
            try:
                parts.append((folder / name).read_text(encoding="utf-8").strip())
            except OSError:
                parts.append(f"({name} is missing)")
        return ("\n\n" + "─" * 40 + "\n\n").join(parts)


def _installed_version(dist: str) -> str | None:
    """Version that is actually installed; differs from the build when running from source."""
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def load_licenses(folder: Path | None = None) -> list[LicenseEntry]:
    folder = folder or license_dir()
    try:
        raw = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = []
    for e in raw:
        version = (_installed_version(e["dist"]) if e.get("dist") else None) or e.get("version", "")
        entries.append(
            LicenseEntry(
                name=e["name"],
                version=version,
                license=e.get("license", ""),
                url=e.get("url", ""),
                note=e.get("note", ""),
                files=list(e.get("files", [])),
            )
        )
    return entries
