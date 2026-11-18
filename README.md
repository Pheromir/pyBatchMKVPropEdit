# pyBatchMKVPropEdit

> **Note:** This project is developed with the help of AI.

A tool for Windows and Linux for changing track properties, titles, chapters, tags and attachments in many MKV files at
once. It uses `mkvpropedit` from MKVToolNix under the hood. Files are edited in place without remuxing, so
even large files only take a few seconds.

The idea comes from [JMkvpropedit](https://github.com/BrunoReX/jmkvpropedit). JMkvpropedit only addresses
tracks by position ("audio track 2") and never looks at the files beforehand, which goes wrong as soon as the
files are not all built the same way. This tool reads every file with `mkvmerge` first and picks tracks with
rules, for example "all German subtitle tracks whose name contains 'Signs'".

## Requirements

- Windows 10 or 11, or Linux (x86_64)
- [MKVToolNix](https://mkvtoolnix.download/) (not included). On Linux, install it with the package manager,
  e.g. `sudo apt install mkvtoolnix`.

`mkvmerge` and `mkvpropedit` are looked up in this order:

1. the folder set in the settings
2. `PATH`
3. the default installation folder, e.g. `C:\Program Files\MKVToolNix` on Windows or `/usr/bin` on Linux

A folder that contains both programs is preferred, so different versions don't get mixed. If nothing is
found, the program asks for the folder on startup and remembers it.

## Usage

1. **Files**: Drop MKV files or whole folders into the window. The order of the list determines the numbering
   used by `{num}`; drag rows to change it.
2. **Tracks**: Pick a reference file at the top, then create rules. The quickest way is to select a track in
   the table and click "Rule from selected track". Values that will change are shown right in the table as
   `old → new`.
3. **General** and **Attachments**: title, chapters, tags and attachments, if needed.
4. **Preview & run**: Shows the changes, any warnings and the full command line for every file. Then click
   "Run". "Cancel" skips the files that have not been started yet; a file that is being written is always
   finished first, and the same applies when the window is closed during a run. If mkvpropedit works on a
   single file for longer than the time set in the settings (10 minutes by default), the program asks whether
   to keep waiting or to stop that file. Stopping can leave the file damaged, so it is meant for the case that
   mkvpropedit really hangs.

Keep in mind that `mkvpropedit` writes directly into the files and there is no undo. Try new presets on a few
copies first.

## Rules

A rule consists of a match (which tracks) and actions (what to change).

The rule list is grouped by track type. Every rule shows what it looks for (grey) and what it changes (blue),
plus a counter such as `6/8`: the rule finds a track in 6 of the 8 loaded files, so two files are built
differently. A rule applies to the first matching track unless it carries the chip `all` or names positions.

The editor only shows the conditions and actions a rule uses. Add more with "+ Condition" and "+ Action",
remove them with the x next to them. Above that, the rule is written out as a sentence, and below the actions
you see what it changes in the reference file.

**Match.** All listed conditions have to apply.

| Field | Example |
|---|---|
| Track type | Video, Audio, Subtitles |
| Position(s) in type | `1`, `1, 3` or `2-4`. The rule applies to exactly these tracks, as far as they meet the other conditions. |
| Language(s) | `ger, jpn`. The spelling does not matter: `ger`, `deu` and `de` all match every German track, including `de-DE` and files without IETF language tags. A tag with a region such as `de-DE` only matches tracks tagged exactly like that. |
| Codec contains | `PGS`, `AAC` |
| Name (Regex) | `sign\|song` (case-insensitive) |
| Is default / Is forced | yes, no |
| Matches | first matching track only, or all matching tracks. Not used while a position is set. |

**Actions.** Every flag (enabled, default, forced, hearing impaired, visual impaired, text descriptions,
original language, commentary) can be set to yes or no; a click on a flag switches between the two, and flags
that are not listed stay unchanged. On top of that there's the track name, the
language and free-form extra parameters for mkvpropedit. "Exclusive default" makes the track the default track
and removes the default flag from all other tracks of the same type.

A few things worth knowing:

- If several rules match the same track and set the same field, the rule further down the list wins. The
  preview shows a warning in that case. Rules of different track types never get in each other's way, which
  is why a rule is only moved within its type, with the arrow buttons or by dragging it.
- A name condition that is not a valid regular expression is marked in the editor, and the rule is skipped
  with a warning in the preview.
- The language dropdown only offers the languages chosen under Settings → Language picker. Every other
  language can be typed into the field: a code or tag such as `kor` or `pt-BR` is taken as it is, and typing a
  name suggests the matching languages.
- All rules see the file as it was before the run. A rule that matches on the name won't find a name that
  another rule is only about to set.
- By default only values that actually differ are written, so running the same preset twice changes nothing
  the second time. This can be turned off in the settings.

## Placeholders

In titles, track names and extra parameters:

| Placeholder | Content |
|---|---|
| `{file_name}` | file name without extension |
| `{dir_name}` | folder name |
| `{num}` | running number, start value and digits are set under "General" |
| `{title}` | current title of the file |

Only in track names and track extra parameters:

| Placeholder | Content |
|---|---|
| `{track_name}` | current track name |
| `{lang_name}` | language written out, e.g. `German` |
| `{lang}` | language code, e.g. `ger` or `de-DE` |
| `{format}` | short format, e.g. `ASS`, `PGS`, `FLAC`, `DTS-HD MA`, `HEVC` |
| `{codec}` | codec name reported by mkvmerge |
| `{channels}` | channels, e.g. `2.0` or `5.1` |
| `{track_num}` | number of the track within its type |

If a rule also sets a new language, `{lang}` and `{lang_name}` refer to the new language. All other
placeholders show the state before the run.

Example of consistent subtitle names: `{lang_name} · Signs & Songs · CR` and `{lang_name} · Full · BD`.

## Presets

- **Global presets** store everything: General, Attachments and all track rules. Load and save them with the
  bar at the top of the window.
- **Track presets** store the actions for a single track, optionally together with the match. They are applied
  to a rule on the Tracks page, or used to create a new rule.

Both can be renamed, duplicated, deleted, exported and imported as JSON on the Presets page. The current state
is also saved automatically and restored on the next start, even if it was never saved as a preset.

Settings, presets, the automatic backup and an error log (`error.log`) are stored in
`%APPDATA%\pyBatchMKVPropEdit` on Windows and in `~/.config/pyBatchMKVPropEdit` on Linux (or below
`$XDG_CONFIG_HOME`, if set).

## Building

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
```

This installs the dependencies listed in `pyproject.toml`, plus pytest and PyInstaller.

Run and test:

```bash
.venv\Scripts\python run.py
.venv\Scripts\python -m pytest
```

The tests in `tests/test_integration.py` create small MKV files and modify them with the real mkvpropedit.
They are skipped if MKVToolNix is not installed.

Build the exe:

```bash
.venv\Scripts\python tools\make_icon.py
.venv\Scripts\pyinstaller build.spec --noconfirm
```

The result ends up in `dist\pyBatchMKVPropEdit.exe` and runs without a Python installation.

Every build first runs `tools/collect_licenses.py`. It copies the license texts of all bundled libraries,
matching the installed versions, to `src/bmpe/resources/licenses/`. The program shows them under Settings →
About → Info. Run the script by hand after changing the version or updating a library, so the texts in the
repository stay current (`tests/test_licenses.py` checks the version).

### Linux

PyInstaller cannot build for another system, so the Linux version has to be built on Linux. Set up the venv
with `.venv/bin/...` instead of `.venv\Scripts\...`, then build an AppImage:

```bash
tools/build_appimage.sh
```

This needs [appimagetool](https://github.com/AppImage/appimagetool/releases) in `PATH` (or its path in
`APPIMAGETOOL`). The result is `dist/pyBatchMKVPropEdit-<version>-x86_64.AppImage`, a single file that runs
without installation after `chmod +x`. It only runs on systems with the same or a newer glibc than the build
system, so build on the oldest distribution you want to support.

Without an AppImage, the program can also be installed as a Python package, for example with
[pipx](https://pipx.pypa.io/):

```bash
pipx install /path/to/pyBatchMKVPropEdit
```

This adds the command `pybatchmkvpropedit`. `packaging/linux/pybatchmkvpropedit.desktop` is a menu entry for it.

## Project layout

```
src/bmpe/core/   logic without GUI: data model, probing, rules, command line, execution, presets
src/bmpe/ui/     user interface (PySide6 with PySide6-Fluent-Widgets)
tests/           pytest
tools/           helper scripts for the build
packaging/linux/ menu entry for Linux
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
- [MKVToolNix](https://mkvtoolnix.download/) (GPLv2, installed separately)
- [DejaVu Sans](https://dejavu-fonts.github.io/) (Bitstream Vera license), only for drawing the icon in
  `tools/make_icon.py`; see `tools/fonts/LICENSE-DejaVu.txt`

## License

Copyright (c) 2026 Pheromir

The source code of pyBatchMKVPropEdit is released under the [MIT License](LICENSE).

The built exe and AppImage also contain Python and the libraries listed above (except MKVToolNix).
PySide6-Fluent-Widgets is licensed under the GPLv3, so these builds as a whole are distributed under the terms
of the GPLv3. The license texts of all bundled parts can be read in the program under Settings → About → Info.
