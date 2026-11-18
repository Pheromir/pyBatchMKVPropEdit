# pyBatchMKVPropEdit

> **Note:** This project is developed with the help of AI.

pyBatchMKVPropEdit changes track properties, titles, chapters, tags and attachments in many MKV files at once.
It uses `mkvpropedit` from MKVToolNix, so files are edited in place without remuxing.

Tracks are selected with rules instead of fixed positions, for example "all German subtitle tracks whose name
contains 'Signs'". Every file is read with `mkvmerge` first, so the rules also work when the files are not all
built the same way. The idea comes from [JMkvpropedit](https://github.com/BrunoReX/jmkvpropedit), which only
addresses tracks by position.

## Download

Get the latest version from the [Releases](../../releases) page:

- Windows: `pyBatchMKVPropEdit-<version>-windows-x64.exe`, runs without installation.
- Linux: `pyBatchMKVPropEdit-<version>-linux-x86_64.AppImage`, make it executable with `chmod +x` and start it.

Or install it as a Python package (Python 3.11 or newer), which adds the command `pybatchmkvpropedit`:

```bash
pipx install git+https://github.com/Pheromir/pyBatchMKVPropEdit.git
```

`pip install` works with the same URL; [pipx](https://pipx.pypa.io/) keeps the program in its own environment.

## Requirements

- Windows 10/11 or Linux (x86_64)
- [MKVToolNix](https://mkvtoolnix.download/), installed separately. On Linux, use the package manager, e.g.
  `sudo apt install mkvtoolnix`.

`mkvmerge` and `mkvpropedit` are searched for in this order:

1. the folder set in the settings
2. `PATH`
3. the default installation folder (`C:\Program Files\MKVToolNix` on Windows, `/usr/bin` on Linux)

A folder that contains both programs is preferred. If nothing is found, the program asks for the folder.

## Usage

1. **Files**: Drop MKV files or folders into the window. The order of the list sets the numbering for `{num}`;
   drag rows to change it.
2. **Tracks**: Pick a reference file and create rules. "Rule from selected track" creates a rule from a track
   in the table. Values that will change are shown in the table as `old → new`.
3. **General** and **Attachments**: title, chapters, tags and attachments, if needed.
4. **Preview & run**: Shows the changes, warnings and the command line for every file. "Run" starts the
   changes.

During a run, "Cancel" skips the files that have not started yet. A file that is being written is always
finished, also when the window is closed. If a single file takes longer than the time set in the settings
(10 minutes by default), the program asks whether to keep waiting or to stop it. Stopping can damage the file.

`mkvpropedit` writes directly into the files and there is no undo. Test new presets on copies first.

## Rules

A rule consists of a match (which tracks) and actions (what to change).

The rule list is grouped by track type. Each rule shows its match in grey, its changes in blue and a counter
such as `6/8`: the rule finds a track in 6 of 8 loaded files. A rule applies to the first matching track
unless it is marked `all` or names positions.

The editor shows only the conditions and actions a rule uses. "+ Condition" and "+ Action" add more, the x
next to a field removes it. Above the fields, the rule is written out as a sentence; below them, the editor
shows what changes in the reference file.

**Match.** All listed conditions must apply.

| Field | Example |
|---|---|
| Track type | Video, Audio, Subtitles |
| Position(s) in type | `1`, `1, 3` or `2-4`. The rule applies to exactly these tracks, if they meet the other conditions. |
| Language(s) | `ger, jpn`. `ger`, `deu` and `de` all match every German track, including `de-DE` and files without IETF language tags. A tag with a region such as `de-DE` only matches tracks with exactly that tag. |
| Codec contains | `PGS`, `AAC` |
| Name (Regex) | `sign\|song` (case-insensitive) |
| Is default / Is forced | yes, no |
| Matches | the first matching track or all matching tracks. Not used when positions are set. |

**Actions.** Each flag (enabled, default, forced, hearing impaired, visual impaired, text descriptions,
original language, commentary) can be set to yes or no; clicking a flag switches between the two. Flags that
are not listed stay unchanged. Further actions: track name, language and extra parameters for mkvpropedit.
"Exclusive default" makes the track the default track and removes the default flag from all other tracks of
the same type.

Notes:

- If several rules set the same field of the same track, the lower rule wins and the preview shows a warning.
  Rules for different track types do not affect each other, so a rule can only be moved within its type.
- A name condition that is not a valid regular expression is marked in the editor; the rule is skipped and
  the preview shows a warning.
- The language dropdown offers the languages chosen under Settings → Language picker. Other languages can be
  typed: a code or tag such as `kor` or `pt-BR` is used as it is, a name shows matching languages.
- All rules see the file as it was before the run. A rule that matches a name does not see a name that another
  rule sets.
- By default, only values that differ are written, so running the same preset twice changes nothing the second
  time. This can be turned off in the settings.

## Placeholders

In titles, track names and extra parameters:

| Placeholder | Content |
|---|---|
| `{file_name}` | file name without extension |
| `{dir_name}` | folder name |
| `{num}` | running number; start value and digits are set under "General" |
| `{title}` | current title of the file |

Only in track names and track extra parameters:

| Placeholder | Content |
|---|---|
| `{track_name}` | current track name |
| `{lang_name}` | language name, e.g. `German` |
| `{lang}` | language code, e.g. `ger` or `de-DE` |
| `{format}` | short format, e.g. `ASS`, `PGS`, `FLAC`, `DTS-HD MA`, `HEVC` |
| `{codec}` | codec name reported by mkvmerge |
| `{channels}` | channels, e.g. `2.0` or `5.1` |
| `{track_num}` | number of the track within its type |

If a rule also sets a new language, `{lang}` and `{lang_name}` use the new language. All other placeholders
show the state before the run.

Example: `{lang_name} · Signs & Songs` and `{lang_name} · Full · {format}`.

## Presets and settings

- **Global presets** contain everything: General, Attachments and all track rules. They are loaded and saved
  with the bar at the top of the window.
- **Track presets** contain the actions for one track, optionally with the match. They can be applied to a
  rule on the Tracks page or used to create a new rule.

The Presets page renames, duplicates, deletes, exports and imports presets as JSON. The current state is saved
automatically and restored on the next start.

Settings, presets, the automatic backup and the error log (`error.log`) are stored in
`%APPDATA%\pyBatchMKVPropEdit` on Windows and `~/.config/pyBatchMKVPropEdit` on Linux (or
`$XDG_CONFIG_HOME/pyBatchMKVPropEdit`).

## Building from source

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python run.py
.venv\Scripts\python -m pytest
```

On Linux, use `.venv/bin/` instead of `.venv\Scripts\`. `[dev]` adds pytest and PyInstaller. The tests in
`tests/test_integration.py` need MKVToolNix and are skipped without it.

**Windows exe:**

```bash
.venv\Scripts\pyinstaller build.spec --noconfirm
```

Creates `dist\pyBatchMKVPropEdit.exe`.

**Linux AppImage:** PyInstaller cannot build for another system, so this has to run on Linux. It needs
[appimagetool](https://github.com/AppImage/appimagetool/releases) in `PATH` or its path in `APPIMAGETOOL`.

```bash
tools/build_appimage.sh
```

Creates `dist/pyBatchMKVPropEdit-<version>-x86_64.AppImage`. It runs on systems with the same or a newer glibc
than the build system.

**Python package:** `pipx install .` installs the checked-out folder. On Linux,
`packaging/linux/pybatchmkvpropedit.desktop` adds a menu entry for the command `pybatchmkvpropedit`.

**License texts:** Every build runs `tools/collect_licenses.py` first. It copies the license texts of all
bundled libraries to `src/bmpe/resources/licenses/`; the program shows them under Settings → About → Info.
After changing the version or updating a library, run the script by hand and commit the result
(`tests/test_licenses.py` checks the version).

## Releasing

1. Set the version in `src/bmpe/__init__.py`, run `tools/collect_licenses.py` and commit.
2. Publish a release on GitHub with the tag `v<version>`, e.g. `v0.2.0`.

The workflow `.github/workflows/release.yml` then builds the exe and the AppImage and attaches both to the
release. It stops if the tag does not match the version. "Run workflow" on the Actions page builds both files
without a release.

## Project layout

```
src/bmpe/core/      logic without GUI: data model, probing, rules, command line, execution, presets
src/bmpe/ui/        user interface (PySide6 with PySide6-Fluent-Widgets)
tests/              pytest
tools/              build scripts
packaging/linux/    menu entry for Linux
.github/workflows/  release build
```

## Libraries

- [PySide6](https://doc.qt.io/qtforpython-6/) and Qt (LGPLv3)
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) (GPLv3) with
  [PySideSix-Frameless-Window](https://github.com/zhiyiYo/PyQt-Frameless-Window) (LGPLv3) and
  [darkdetect](https://github.com/albertosottile/darkdetect) (BSD-3-Clause)
- [pydantic](https://docs.pydantic.dev/) (MIT) with pydantic-core, annotated-types, typing-inspection (MIT) and
  typing_extensions (PSF-2.0)
- [packaging](https://github.com/pypa/packaging) (Apache-2.0 or BSD-2-Clause)
- [pywin32](https://github.com/mhammond/pywin32) (PSF), Windows only
- [MKVToolNix](https://mkvtoolnix.download/) (GPLv2), installed separately
- [DejaVu Sans](https://dejavu-fonts.github.io/) (Bitstream Vera license), only used to draw the icon in
  `tools/make_icon.py`; see `tools/fonts/LICENSE-DejaVu.txt`

## License

Copyright (c) 2026 Pheromir

The source code is released under the [MIT License](LICENSE).

The exe and the AppImage also contain Python and the libraries listed above (except MKVToolNix).
PySide6-Fluent-Widgets is licensed under the GPLv3, so these builds as a whole are distributed under the
GPLv3. The license texts of all bundled parts are shown in the program under Settings → About → Info.
