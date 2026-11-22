"""Collects the license texts of everything bundled into the exe/AppImage into src/bmpe/resources/licenses/.

Versions and texts come from the current environment (.venv), so they always match the build.
build.spec runs this script automatically; by hand:

    .venv\\Scripts\\python tools\\collect_licenses.py

Result: index.json (read by the info dialog) and one .txt file per license text.
"""

from __future__ import annotations

import json
import platform
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "bmpe" / "resources" / "licenses"
TOOLS_LICENSES = ROOT / "tools" / "licenses"


def dist_file(dist: str, rel: str) -> str:
    """Text of a file shipped with an installed package (usually in its dist-info folder)."""
    for f in metadata.distribution(dist).files or []:
        if str(f).replace("\\", "/").endswith(rel):
            return Path(f.locate()).read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(f"{dist}: {rel} not found")


def python_license() -> str:
    """LICENSE.txt of the Python that builds the exe; some Linux distributions don't install it."""
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
        TOOLS_LICENSES / "Python-LICENSE.txt",  # copy from Python 3.14, as a fallback
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError("Python LICENSE.txt not found")


def write_if_changed(path: Path, text: str) -> None:
    """Leaves unchanged files alone, so a build doesn't touch the working tree."""
    try:
        if path.read_bytes() == text.encode("utf-8"):
            return
    except OSError:
        pass
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from bmpe import __version__

    windows = sys.platform == "win32"
    texts = {
        "pyBatchMKVPropEdit.txt": (ROOT / "LICENSE").read_text(encoding="utf-8"),
        # the GPL 3.0 belongs to PySide6-Fluent-Widgets and is also required next to every LGPL 3.0
        "GPL-3.0.txt": dist_file("PySide6-Fluent-Widgets", "LICENSE"),
        "LGPL-3.0.txt": dist_file("PySideSix-Frameless-Window", "LICENSE"),
        "Python.txt": python_license(),
        "darkdetect.txt": dist_file("darkdetect", "LICENSE"),
        "pydantic.txt": dist_file("pydantic", "licenses/LICENSE"),
        "pydantic-core.txt": dist_file("pydantic_core", "licenses/LICENSE"),
        "annotated-types.txt": dist_file("annotated-types", "licenses/LICENSE"),
        "typing-inspection.txt": dist_file("typing-inspection", "licenses/LICENSE"),
        "typing-extensions.txt": dist_file("typing_extensions", "licenses/LICENSE"),
        "packaging.txt": dist_file("packaging", "licenses/LICENSE"),
        "packaging-Apache-2.0.txt": dist_file("packaging", "licenses/LICENSE.APACHE"),
        "packaging-BSD.txt": dist_file("packaging", "licenses/LICENSE.BSD"),
        "regex.txt": dist_file("regex", "licenses/LICENSE.txt"),
        "DejaVu.txt": (ROOT / "tools" / "fonts" / "LICENSE-DejaVu.txt").read_text(encoding="utf-8"),
    }
    if windows:
        texts["pywin32.txt"] = dist_file("pywin32", "licenses/win32/License.txt")

    v = metadata.version
    entries = [
        {
            "name": "pyBatchMKVPropEdit",
            "version": __version__,
            "license": "MIT",
            "url": "",
            "files": ["pyBatchMKVPropEdit.txt"],
            "note": "The source code of pyBatchMKVPropEdit is released under the MIT License.\n\n"
            "This build also contains the libraries listed here. PySide6-Fluent-Widgets is licensed under "
            "the GPL 3.0, so the build as a whole is distributed under the terms of the GPL 3.0.\n\n"
            "MKVToolNix is not included; it is installed separately.",
        },
        {
            "name": "Python",
            "version": platform.python_version(),
            "license": "PSF-2.0",
            "url": "https://www.python.org",
            "files": ["Python.txt"],
        },
        {
            "name": "Qt / PySide6 / Shiboken6",
            "dist": "PySide6_Essentials",
            "version": v("PySide6_Essentials"),
            "license": "LGPL-3.0",
            "url": "https://www.qt.io/qt-for-python",
            "files": ["LGPL-3.0.txt", "GPL-3.0.txt"],
            "note": "Copyright (C) The Qt Company Ltd. and other contributors.\n\n"
            "Qt and PySide6 are used unmodified under the GNU LGPL 3.0. The source code is available at "
            "https://code.qt.io.",
        },
        {
            "name": "PySide6-Fluent-Widgets",
            "dist": "PySide6-Fluent-Widgets",
            "version": v("PySide6-Fluent-Widgets"),
            "license": "GPL-3.0",
            "url": "https://github.com/zhiyiYo/PyQt-Fluent-Widgets",
            "files": ["GPL-3.0.txt"],
            "note": "Copyright (C) zhiyiYo\n\nUsed unmodified under the GNU GPL 3.0.",
        },
        {
            "name": "PySideSix-Frameless-Window",
            "dist": "PySideSix-Frameless-Window",
            "version": v("PySideSix-Frameless-Window"),
            "license": "LGPL-3.0",
            "url": "https://github.com/zhiyiYo/PyQt-Frameless-Window",
            "files": ["LGPL-3.0.txt", "GPL-3.0.txt"],
            "note": "Copyright (C) zhiyiYo\n\nUsed unmodified under the GNU LGPL 3.0.",
        },
        {
            "name": "darkdetect",
            "dist": "darkdetect",
            "version": v("darkdetect"),
            "license": "BSD-3-Clause",
            "url": "https://github.com/albertosottile/darkdetect",
            "files": ["darkdetect.txt"],
        },
        {
            "name": "pydantic",
            "dist": "pydantic",
            "version": v("pydantic"),
            "license": "MIT",
            "url": "https://github.com/pydantic/pydantic",
            "files": ["pydantic.txt"],
        },
        {
            "name": "pydantic-core",
            "dist": "pydantic_core",
            "version": v("pydantic_core"),
            "license": "MIT",
            "url": "https://github.com/pydantic/pydantic-core",
            "files": ["pydantic-core.txt"],
        },
        {
            "name": "annotated-types",
            "dist": "annotated-types",
            "version": v("annotated-types"),
            "license": "MIT",
            "url": "https://github.com/annotated-types/annotated-types",
            "files": ["annotated-types.txt"],
        },
        {
            "name": "typing-inspection",
            "dist": "typing-inspection",
            "version": v("typing-inspection"),
            "license": "MIT",
            "url": "https://github.com/pydantic/typing-inspection",
            "files": ["typing-inspection.txt"],
        },
        {
            "name": "typing_extensions",
            "dist": "typing_extensions",
            "version": v("typing_extensions"),
            "license": "PSF-2.0",
            "url": "https://github.com/python/typing_extensions",
            "files": ["typing-extensions.txt"],
        },
        {
            "name": "regex",
            "dist": "regex",
            "version": v("regex"),
            "license": "Apache-2.0 AND CNRI-Python",
            "url": "https://github.com/mrabarnett/mrab-regex",
            "files": ["regex.txt"],
        },
        {
            "name": "packaging",
            "dist": "packaging",
            "version": v("packaging"),
            "license": "Apache-2.0 OR BSD-2-Clause",
            "url": "https://github.com/pypa/packaging",
            "files": ["packaging.txt", "packaging-Apache-2.0.txt", "packaging-BSD.txt"],
        },
    ]
    if windows:  # pywin32 is only part of the Windows exe (used by PySideSix-Frameless-Window)
        entries.append(
            {
                "name": "pywin32",
                "dist": "pywin32",
                "version": v("pywin32"),
                "license": "PSF-2.0",
                "url": "https://github.com/mhammond/pywin32",
                "files": ["pywin32.txt"],
            }
        )
    entries.append(
        {
            "name": "DejaVu Sans",
            "version": "2.35",
            "license": "Bitstream Vera",
            "url": "https://dejavu-fonts.github.io",
            "files": ["DejaVu.txt"],
            "note": "Only used to draw the program icon; the font itself is not included.",
        }
    )

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):  # e.g. pywin32.txt after building on Linux
        if old.name not in texts:
            old.unlink()
    for name, txt in texts.items():
        write_if_changed(OUT / name, txt.strip() + "\n")
    write_if_changed(OUT / "index.json", json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(entries)} entries, {len(texts)} license texts -> {OUT}")


if __name__ == "__main__":
    main()
