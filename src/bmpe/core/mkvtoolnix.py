"""Locates mkvpropedit/mkvmerge.

Order: folder saved in the config -> PATH -> default installation folder.
If nothing is found, the GUI asks for the folder and saves it in the config.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

EXE_SUFFIX = ".exe" if os.name == "nt" else ""
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
REQUIRED_TOOLS = ("mkvmerge", "mkvpropedit")


def standard_dirs() -> list[Path]:
    dirs: list[Path] = []
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = os.environ.get(env)
            if root:
                dirs.append(Path(root) / "MKVToolNix")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Programs" / "MKVToolNix")
    else:
        dirs += [Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin")]
    seen, unique = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


@dataclass
class ToolLocation:
    path: Path
    source: str  # "config" | "PATH" | "default folder"


def _exe_in(folder: Path | str, name: str) -> Path:
    folder = Path(folder)
    exe = name + EXE_SUFFIX
    if folder.is_file():  # the user picked an exe directly
        folder = folder.parent
    return folder / exe


def find_tool(name: str, config_dir: str = "") -> ToolLocation | None:
    if config_dir:
        p = _exe_in(config_dir, name)
        if p.is_file():
            return ToolLocation(p, "config")
    found = shutil.which(name)
    if found:
        return ToolLocation(Path(found), "PATH")
    for d in standard_dirs():
        p = d / (name + EXE_SUFFIX)
        if p.is_file():
            return ToolLocation(p, "default folder")
    return None


def find_tools(config_dir: str = "") -> dict[str, ToolLocation | None]:
    """Looks for mkvmerge + mkvpropedit, preferring a folder that contains both (same version)."""
    candidates: list[tuple[Path, str]] = []
    if config_dir:
        candidates.append((_exe_in(config_dir, "x").parent, "config"))
    for name in REQUIRED_TOOLS:
        found = shutil.which(name)
        if found:
            candidates.append((Path(found).parent, "PATH"))
    candidates += [(d, "default folder") for d in standard_dirs()]
    for folder, source in candidates:
        if dir_has_tools(str(folder)):
            return {n: ToolLocation(_exe_in(folder, n), source) for n in REQUIRED_TOOLS}
    # no folder with both: look for each one separately
    return {n: find_tool(n, config_dir) for n in REQUIRED_TOOLS}


def dir_has_tools(folder: str) -> bool:
    return bool(folder) and all(_exe_in(folder, n).is_file() for n in REQUIRED_TOOLS)


def run_hidden(args: list[str], timeout: float | None = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
    )


def tool_version(path: Path) -> str:
    try:
        out = run_hidden([str(path), "--version"], timeout=15).stdout.decode("utf-8", "replace")
        return out.strip().splitlines()[0] if out.strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""
