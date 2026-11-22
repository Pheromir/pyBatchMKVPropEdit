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

Each file has a `.sha256` file next to it with its checksum. Check it with `sha256sum -c <file>.sha256` on Linux
or compare it with `Get-FileHash <file>` in PowerShell.

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

The rules are evaluated from the top of the list. Each rule sees the tracks as the rules above it left them: a
flag, language or name set further up counts for its conditions and placeholders. Put rules that set basic
values, such as the language or the commentary flag, above the rules that build on them.

The rule list is grouped by track type. Each rule shows its match in grey, its changes in blue and a counter
such as `6/8`: at its place in the list, the rule finds a track in 6 of 8 loaded files. A rule applies to the
first matching track unless it is marked `all` or names positions.

The editor shows only the conditions and actions a rule uses. "+ Condition" and "+ Action" add more, the x
next to a field removes it. Above the fields, the rule is written out as a sentence; below them, the editor
shows what changes in the reference file.

**Match.** All listed conditions must apply. "+ Condition" groups them into track, flags, technical values and
file.

| Condition | Choices and example |
|---|---|
| Track type | Video, Audio, Subtitles |
| Position(s) in type | `1`, `1, 3` or `2-4`. The rule applies to exactly these tracks, if they meet the other conditions. |
| Language(s) | is / is not, e.g. `ger, jpn`. `ger`, `deu` and `de` all match every German track, including `de-DE` and files without IETF language tags. A tag with a region such as `de-DE` only matches tracks with exactly that tag. |
| Codec | contains / doesn't contain, e.g. `PGS`, `AAC` |
| Name | matches / doesn't match a regular expression such as `sign\|song`, or is empty / isn't empty |
| Flags | Default, Forced, Enabled, Hearing impaired, Visual impaired, Text descriptions, Original language, Commentary: yes or no. A track without the Enabled element counts as enabled. |
| Channels, Sample rate (kHz), Bit depth (bit) | audio tracks |
| Bitrate (kbps) | audio and video tracks |
| Height (px), Frame rate (fps) | video tracks |
| Path | the full path of the file |
| File name | the file name with extension |
| Matches | the first matching track or all matching tracks. Not used when positions are set. |

- Technical values are compared with `=`, `≠`, `<`, `≤`, `>` or `≥`, e.g. Channels `≥ 6`, Frame rate `= 23.976`.
  A track that does not report the value does not match; the preview names the missing value. The bitrate
  comes from the track statistics tags, which some tools do not write (General → Track statistics tags adds
  them).
- Path and file name take contains / doesn't contain with a plain text, or matches / doesn't match with a
  regular expression. They are checked once per file: in a file that does not meet them, the rule matches no
  track.
- All text comparisons and regular expressions ignore case. A regular expression that takes longer than a
  quarter of a second on one text is stopped and counts as no match; the preview shows a warning.

**Actions.** Each flag (enabled, default, forced, hearing impaired, visual impaired, text descriptions,
original language, commentary) can be set to yes or no; clicking a flag switches between the two. Flags that
are not listed stay unchanged. Further actions: track name, language and extra parameters for mkvpropedit.
"Exclusive default" makes the track the default track and removes the default flag from all other tracks of
the same type. A rule further down can still change the default flag again.

Notes:

- If several rules set the same field of the same track, the lower rule wins and the preview shows a warning.
  Rules for different track types do not affect each other, so a rule can only be moved within its type.
- A condition with an invalid regular expression is marked in the editor; the rule is skipped and the preview
  shows a warning.
- The language dropdown offers the languages chosen under Settings → Language picker. Other languages can be
  typed: a code or tag such as `kor` or `pt-BR` is used as it is, a name shows matching languages.
- Codec, technical values, path and file name do not change during a run, so for them it makes no difference
  where a rule is in the list.
- By default, only values that differ are written, so running the same preset twice changes nothing the second
  time. This can be turned off in the settings.

## Placeholders

The + button next to a template field inserts placeholders and filters.

In titles, track names and extra parameters:

| Placeholder | Content |
|---|---|
| `{file_name}` | file name without extension |
| `{ext}` | file extension without the dot, e.g. `mkv` |
| `{dir_name}` | folder name |
| `{parent_dir}` | name of the folder above it, e.g. the series for a season folder |
| `{num}` | running number; start value and digits are set under "General" |
| `{title}` | current title of the file |
| `{duration}` | duration of the file, e.g. `23:40` or `1:52:08` |
| `{audio_langs}` | languages of all audio tracks, e.g. `JPN/GER` |
| `{sub_langs}` | languages of all subtitle tracks, e.g. `GER/ENG` |
| `{video_format}` | format of the first video track, e.g. `HEVC` |
| `{resolution}` | size of the first video track, e.g. `1920x1080` |
| `{height}` | height of the first video track, e.g. `1080` |
| `{fps}` | frame rate of the first video track, e.g. `23.976` |
| `{1}`, `{2}`, … | groups of the file name pattern, see below; `{0}` is the whole match |

Only in track names and track extra parameters:

| Placeholder | Content |
|---|---|
| `{track_name}` | name of the track before the run |
| `{prev_track_name}` | name set by the rules above; without one, the name before the run |
| `{lang_name}` | language name, e.g. `German` |
| `{lang}` | language code, e.g. `ger` or `de-DE` |
| `{format}` | short format, e.g. `ASS`, `PGS`, `FLAC`, `DTS-HD MA`, `HEVC` |
| `{codec}` | codec name reported by mkvmerge |
| `{channels}` | channels, e.g. `2.0` or `5.1` |
| `{channels_name}` | `Mono`, `Stereo` or `Surround`; `{channels} {channels_name}` gives `2.0 Stereo` |
| `{bitrate}` | bitrate in kbps, e.g. `640`; empty without track statistics tags |
| `{sample_rate}` | sample rate in kHz, e.g. `48` or `44.1` |
| `{bit_depth}` | bits per sample, e.g. `24` |
| `{track_num}` | number of the track within its type |

In the name of a video track, `{video_format}`, `{resolution}`, `{height}` and `{fps}` describe that track.
`{lang}` and `{lang_name}` use the language set by this rule or the rules above, `{prev_track_name}` the name
set above. `{track_name}` and all other placeholders show the file before the run. A value the file does not
report is empty.

Example: `{lang_name} · Signs & Songs` and `{lang_name} · {format} {channels} {channels_name}`.

### Names in steps

Track names are worked out rule by rule, from the top of the list. In a track name, `{prev_track_name}` is the
name the rules above set for this track; if none did, it is the name before the run, and after a rule that
removes the name it is empty. A rule that uses it builds on the name, so the preview reports no conflict. A
rule without it replaces the name of the rules above, as before.

| Rule | Matches | Action |
|---|---|---|
| 1 | all audio tracks | language `ger` |
| 2 | all audio tracks | name `{lang_name} {channels} {channels_name}` |
| 3 | audio tracks with flag Commentary = yes | name `{prev_track_name} - Commentary` |

A stereo commentary track is then named `German 2.0 Stereo - Commentary`, the other tracks `German 2.0 Stereo`
or `German 5.1 Surround`. The previous name can go anywhere and take filters, e.g.
`Commentary: {prev_track_name|lower}`. In extra parameters, `{prev_track_name}` is the name after all rules.

Rule 1 has to be above rule 2: below it, `{lang_name}` would still be the language from the file. To mark
commentary tracks first, a rule above rule 3 can set the Commentary flag, e.g. for tracks whose name matches
`comment`; rule 3 then finds them by the flag.

On the Tracks page, the result shown for a rule includes the rules above it.

### File name pattern

Under General, a regular expression can be set that is applied to the file name without extension. Each part
in parentheses becomes a placeholder, counted from the left: `{1}`, `{2}`, … `{0}` is the whole match. Case is
ignored.

| File name | Pattern | Placeholders |
|---|---|---|
| `Show - S01E03 [BD]` | `(S\d+E\d+)` | `{1}` = `S01E03` |
| `Show - S01E03 [BD]` | `S(\d+)E(\d+)` | `{1}` = `01`, `{2}` = `03` |
| `[Group] Show - 03 (1080p)` | `\] (.+) - (\d+)` | `{1}` = `Show`, `{2}` = `03` |

Title template `{1} – Episode {2}` with the last pattern gives `Show – Episode 03`. If the pattern does not
match a file, the groups stay empty and the preview shows a warning. The General page shows what the pattern
finds in the first file of the list.

### Filters

A placeholder can be followed by filters, separated by `|`. They are applied from left to right.

| Filter | Effect | Example | Result |
|---|---|---|---|
| `upper` | upper case | `{lang\|upper}` | `GER` |
| `lower` | lower case | `{audio_langs\|lower}` | `jpn/ger` |
| `title` | first letter of every word in upper case | `{track_name\|title}` | `Signs & Songs` |
| `pad:N` | fill a number with zeros to N digits | `{track_num\|pad:2}` | `03` |
| `replace:OLD:NEW` | replace a text; NEW may be empty | `{file_name\|replace:_: }` | `Show 01` |
| `prefix:TEXT` | put TEXT in front, only if the value is not empty | `{1\|prefix:Part }` | `Part 2` |
| `suffix:TEXT` | put TEXT after it, only if the value is not empty | `{bitrate\|suffix: kbps}` | `640 kbps` |
| `or:TEXT` | use TEXT if the value is empty | `{track_name\|or:Unnamed}` | `Unnamed` |

Filters can be chained: `{track_name|or:unnamed|upper}` gives `UNNAMED` for a track without a name. The text
of a filter may contain spaces and colons, but no `|`, `{` or `}`. In extra parameters, put a placeholder
whose filter contains spaces in quotes, e.g. `"title={1|prefix:Part }"`. Unknown placeholders and filters are
left as they are, and the preview shows a warning.

## Presets and settings

- **Global presets** contain everything: General, Attachments and all track rules. They are loaded and saved
  with the bar at the top of the window.
- **Track presets** contain the actions for one track, optionally with the match. They can be applied to a
  rule on the Tracks page or used to create a new rule.

The Presets page renames, duplicates, deletes, exports and imports presets as JSON. A preset can read local
files (attachments, chapter and tag files) and pass extra parameters to mkvpropedit, which could copy a private
file into the MKVs. Before such a preset is imported, the program lists these files and parameters and asks.
The preview always shows the full path of every file that is added. The current state is saved
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
2. After updating a dependency in `.venv`, run `tools/lock_build_requirements.py` and commit
   `requirements-build.txt`.
3. Publish a release on GitHub with the tag `v<version>`, e.g. `v0.2.0`.

The workflow `.github/workflows/release.yml` then builds the exe and the AppImage and attaches both to the
release, each with a `.sha256` file. It stops if the tag does not match the version. "Run workflow" on the
Actions page builds both files without a release.

Everything the build uses is pinned, so a release only contains what was tested:

- the Python packages by version and hash in `requirements-build.txt`, installed with `--require-hashes`;
  `tools/lock_build_requirements.py` writes it from the versions in `.venv`, for Windows and Linux
- the GitHub Actions by commit; Dependabot (`.github/dependabot.yml`) proposes updates once a month
- appimagetool by version and SHA256 in the workflow

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
- [regex](https://github.com/mrabarnett/mrab-regex) (Apache-2.0 and CNRI-Python)
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
