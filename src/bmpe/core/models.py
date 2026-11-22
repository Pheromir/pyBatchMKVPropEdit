"""Data model: probed files, rules, actions and presets."""

from __future__ import annotations

import re
import uuid
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from . import userregex
from .languages import language_key

SCHEMA_VERSION = 1


class TrackType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLES = "subtitles"

    @property
    def label(self) -> str:
        return {"video": "Video", "audio": "Audio", "subtitles": "Subtitles"}[self.value]

    @property
    def short(self) -> str:
        return {"video": "V", "audio": "A", "subtitles": "S"}[self.value]


class TriState(str, Enum):
    UNCHANGED = "unchanged"
    YES = "yes"
    NO = "no"


# internal key -> (mkvpropedit property, key in mkvmerge -J output, label)
FLAGS: dict[str, tuple[str, str, str]] = {
    "enabled": ("flag-enabled", "enabled_track", "Enabled"),
    "default": ("flag-default", "default_track", "Default"),
    "forced": ("flag-forced", "forced_track", "Forced"),
    "hearing_impaired": ("flag-hearing-impaired", "flag_hearing_impaired", "Hearing impaired"),
    "visual_impaired": ("flag-visual-impaired", "flag_visual_impaired", "Visual impaired"),
    "text_descriptions": ("flag-text-descriptions", "flag_text_descriptions", "Text descriptions"),
    "original": ("flag-original", "flag_original", "Original language"),
    "commentary": ("flag-commentary", "flag_commentary", "Commentary"),
}
FLAG_DEFAULTS = {"enabled": True}  # Matroska default values when the element is missing
# flags a condition can check besides "default" and "forced", which have their own fields
FLAG_CONDITIONS = [k for k in FLAGS if k not in ("default", "forced")]


# --------------------------------------------------------------------------- probed data


class TrackInfo(BaseModel):
    id: int
    uid: int = 0
    number: int = 0
    type: TrackType
    index_in_type: int = 1  # 1-based within the track type
    codec: str = ""
    codec_id: str = ""
    language: str = "und"
    language_ietf: str = ""
    name: str = ""
    flags: dict[str, bool] = Field(default_factory=dict)
    channels: int | None = None
    dimensions: str = ""  # display size, falls back to the pixel size
    pixel_dimensions: str = ""  # e.g. "1920x1080"
    bitrate: int | None = None  # bit/s, from the statistics tag BPS
    sample_rate: int | None = None  # Hz
    bit_depth: int | None = None
    frame_duration: int | None = None  # ns per frame (default duration)

    def flag(self, key: str) -> bool:
        return self.flags.get(key, FLAG_DEFAULTS.get(key, False))

    @property
    def size(self) -> tuple[int, int] | None:
        m = re.fullmatch(r"(\d+)x(\d+)", self.pixel_dimensions or self.dimensions)
        return (int(m.group(1)), int(m.group(2))) if m else None

    @property
    def height(self) -> int | None:
        return self.size[1] if self.size else None

    @property
    def fps(self) -> float | None:
        return round(1e9 / self.frame_duration, 3) if self.frame_duration else None

    @property
    def bitrate_kbps(self) -> int | None:
        return round(self.bitrate / 1000) if self.bitrate else None

    @property
    def sample_rate_khz(self) -> float | None:
        return round(self.sample_rate / 1000, 3) if self.sample_rate else None

    @property
    def lang_display(self) -> str:
        return self.language_ietf or self.language or "und"

    def describe(self) -> str:
        parts = [f"#{self.index_in_type} {self.type.label}", self.lang_display, self.codec]
        if self.name:
            parts.append(f"\"{self.name}\"")
        return " · ".join(p for p in parts if p)


class AttachmentInfo(BaseModel):
    id: int
    uid: int = 0
    file_name: str = ""
    mime_type: str = ""
    description: str = ""
    size: int = 0


class FileInfo(BaseModel):
    path: str
    title: str = ""
    tracks: list[TrackInfo] = Field(default_factory=list)
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    chapter_entries: int = 0
    global_tags: int = 0
    track_tags: int = 0  # including the statistics tags (BPS, DURATION, ...)
    duration: int | None = None  # ns
    error: str = ""

    def tracks_of(self, track_type: TrackType) -> list[TrackInfo]:
        return [t for t in self.tracks if t.type == track_type]

    @property
    def summary(self) -> str:
        if self.error:
            return "Error"
        parts = []
        for tt in TrackType:
            n = len(self.tracks_of(tt))
            if n:
                parts.append(f"{n}{tt.short}")
        return " ".join(parts) or "no tracks"


# --------------------------------------------------------------------------- track rules


class NameMode(str, Enum):
    UNCHANGED = "unchanged"
    SET = "set"
    CLEAR = "clear"


def _default_flags() -> dict[str, TriState]:
    return {k: TriState.UNCHANGED for k in FLAGS}


class TrackActions(BaseModel):
    flags: dict[str, TriState] = Field(default_factory=_default_flags)
    name_mode: NameMode = NameMode.UNCHANGED
    name_template: str = ""
    language: str | None = None  # None = unchanged
    exclusive_default: bool = False
    extra_args: str = ""

    @field_validator("flags", mode="before")
    @classmethod
    def _fill_flags(cls, v):
        result = _default_flags()
        if isinstance(v, dict):
            for k, val in v.items():
                if k in result:
                    result[k] = TriState(val)
        return result

    def is_empty(self) -> bool:
        return (
            all(v == TriState.UNCHANGED for v in self.flags.values())
            and self.name_mode == NameMode.UNCHANGED
            and not self.language
            and not self.exclusive_default
            and not self.extra_args.strip()
        )

    def describe(self) -> str:
        parts = []
        for key, state in self.flags.items():
            if state != TriState.UNCHANGED:
                parts.append(f"{FLAGS[key][2]}={'yes' if state == TriState.YES else 'no'}")
        if self.exclusive_default:
            parts.append("exclusive default")
        if self.name_mode == NameMode.SET:
            parts.append(f"name=\"{self.name_template}\"")
        elif self.name_mode == NameMode.CLEAR:
            parts.append("remove name")
        if self.language:
            parts.append(f"language={self.language}")
        if self.extra_args.strip():
            parts.append(f"extra: {self.extra_args.strip()}")
        return ", ".join(parts) or "no changes"


class MatchMode(str, Enum):
    FIRST = "first"
    ALL = "all"


def language_matches(wanted: str, track: TrackInfo) -> bool:
    """A plain code (ger, deu, de) matches the language in any spelling and with any region.

    A tag with subtags (de-DE) only matches tracks that carry exactly that tag or a longer one.
    """
    wanted = wanted.strip().lower()
    if "-" in wanted:
        ietf = track.language_ietf.lower()
        return ietf == wanted or ietf.startswith(wanted + "-")
    return language_key(wanted) in {language_key(c) for c in (track.language, track.language_ietf) if c}


def language_differs(new: str, track: TrackInfo) -> bool:
    """Whether setting `new` would change the track (mkvpropedit writes the legacy and the IETF element)."""
    new = new.strip().lower()
    current = (track.language_ietf or track.language or "und").lower()
    if "-" in new or "-" in current:
        return new != current
    return language_key(new) != language_key(current)


def parse_positions(text: str) -> tuple[list[int], list[str]]:
    """"1, 3, 5-7" -> ([1, 3, 5, 6, 7], []); invalid parts are returned in the second list."""
    result: set[int] = set()
    invalid: list[str] = []
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", text.strip())  # "2 - 4" is a range, not three parts
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            if a >= 1 and b - a <= 999:
                result.update(range(a, b + 1))
                continue
        elif part.isdigit() and int(part) >= 1:
            result.add(int(part))
            continue
        invalid.append(part)
    return sorted(result), invalid


def format_positions(positions: list[int]) -> str:
    """[1, 3, 5, 6, 7] -> "1, 3, 5-7"."""
    nums = sorted(set(positions))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if j - i < 2 else f"{nums[i]}-{nums[j]}")
        if j - i == 1:
            parts.append(str(nums[j]))
        i = j + 1
    return ", ".join(parts)


class NameOp(str, Enum):
    MATCHES = "matches"
    NOT_MATCHES = "not_matches"
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"


class TextOp(str, Enum):
    """How a path or file name condition compares; always case-insensitive."""

    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"  # regular expression
    NOT_MATCHES = "not_matches"

    @property
    def is_regex(self) -> bool:
        return self in (TextOp.MATCHES, TextOp.NOT_MATCHES)

    @property
    def negated(self) -> bool:
        return self in (TextOp.NOT_CONTAINS, TextOp.NOT_MATCHES)


class TextCondition(BaseModel):
    op: TextOp = TextOp.CONTAINS
    value: str = ""

    @property
    def active(self) -> bool:
        return bool(self.value)

    def regex_error(self) -> str:
        if not self.op.is_regex or not self.value:
            return ""
        return userregex.compile_error(self.value)

    def test(self, text: str) -> bool:
        """May raise userregex.RegexTimeout."""
        if not self.value:
            return True
        if self.op.is_regex:
            try:
                hit = bool(userregex.search(self.value, text))
            except userregex.error:
                return False
        else:
            hit = self.value.lower() in text.lower()
        return hit != self.op.negated


class NumOp(str, Enum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"

    @property
    def symbol(self) -> str:
        return {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[self.value]

    def test(self, actual: float, wanted: float) -> bool:
        same = abs(actual - wanted) < 1e-6
        return {
            NumOp.EQ: same,
            NumOp.NE: not same,
            NumOp.LT: actual < wanted and not same,
            NumOp.LE: actual < wanted or same,
            NumOp.GT: actual > wanted and not same,
            NumOp.GE: actual > wanted or same,
        }[self]


class NumCondition(BaseModel):
    op: NumOp = NumOp.GE
    value: float = 0


# technical values a rule can compare: key -> (label, unit, track types that have it)
NUMERIC: dict[str, tuple[str, str, tuple[TrackType, ...]]] = {
    "channels": ("Channels", "", (TrackType.AUDIO,)),
    "bitrate": ("Bitrate", "kbps", (TrackType.AUDIO, TrackType.VIDEO)),
    "sample_rate": ("Sample rate", "kHz", (TrackType.AUDIO,)),
    "bit_depth": ("Bit depth", "bit", (TrackType.AUDIO,)),
    "height": ("Height", "px", (TrackType.VIDEO,)),
    "fps": ("Frame rate", "fps", (TrackType.VIDEO,)),
}


def numeric_value(track: TrackInfo, key: str) -> float | None:
    """The value a numeric condition compares, in the unit shown in the editor; None if unknown."""
    return {
        "channels": track.channels,
        "bitrate": track.bitrate_kbps,
        "sample_rate": track.sample_rate_khz,
        "bit_depth": track.bit_depth,
        "height": track.height,
        "fps": track.fps,
    }[key]


class TrackMatcher(BaseModel):
    track_type: TrackType
    positions: list[int] = Field(default_factory=list)  # nth track(s) of this type, 1-based; empty = any
    languages: list[str] = Field(default_factory=list)
    languages_not: bool = False  # the track must have none of the languages
    codec_contains: str = ""
    codec_not: bool = False
    name_regex: str = ""
    name_op: NameOp = NameOp.MATCHES
    is_default: bool | None = None
    is_forced: bool | None = None
    flags: dict[str, bool] = Field(default_factory=dict)  # the other flags (FLAG_CONDITIONS) -> wanted state
    numbers: dict[str, NumCondition] = Field(default_factory=dict)  # key: see NUMERIC
    path: TextCondition | None = None  # full path of the file
    file_name: TextCondition | None = None  # file name with extension
    match_mode: MatchMode = MatchMode.FIRST

    @property
    def takes_all(self) -> bool:
        """Whether the rule applies to every matching track.

        Positions name the tracks themselves, so "first match only" does not apply to them: "1, 3" means
        track 1 and track 3 (as far as they meet the other conditions).
        """
        return bool(self.positions) or self.match_mode == MatchMode.ALL

    @property
    def uses_name(self) -> bool:
        return bool(self.name_regex) or self.name_op in (NameOp.EMPTY, NameOp.NOT_EMPTY)

    def regex_error(self) -> str:
        """Why a regular expression of the rule cannot be used, or "" if all are fine."""
        if self.name_regex and self.name_op in (NameOp.MATCHES, NameOp.NOT_MATCHES):
            error = userregex.compile_error(self.name_regex)
            if error:
                return f"name: {error}"
        for label, cond in (("path", self.path), ("file name", self.file_name)):
            error = cond.regex_error() if cond else ""
            if error:
                return f"{label}: {error}"
        return ""

    def numeric_keys(self) -> list[str]:
        """The numeric conditions that apply to the track type (others are ignored)."""
        return [k for k in self.numbers if k in NUMERIC and self.track_type in NUMERIC[k][2]]

    def file_matches(self, path: str) -> bool:
        """The conditions on the file itself; if they fail, the rule matches no track in this file."""
        if self.path and not self.path.test(path):
            return False
        if self.file_name and not self.file_name.test(Path(path).name):
            return False
        return True

    def unknown_values(self, track: TrackInfo) -> list[str]:
        """Labels of the numeric conditions whose value this track does not report."""
        return [NUMERIC[k][0] for k in self.numeric_keys() if numeric_value(track, k) is None]

    def matches(self, track: TrackInfo) -> bool:
        """May raise userregex.RegexTimeout."""
        if track.type != self.track_type:
            return False
        if self.positions and track.index_in_type not in self.positions:
            return False
        wanted = [lang for lang in self.languages if lang.strip()]
        if wanted and any(language_matches(lang, track) for lang in wanted) == self.languages_not:
            return False
        if self.codec_contains.strip():
            needle = self.codec_contains.strip().lower()
            hit = needle in track.codec.lower() or needle in track.codec_id.lower()
            if hit == self.codec_not:
                return False
        if self.name_op == NameOp.EMPTY and track.name:
            return False
        if self.name_op == NameOp.NOT_EMPTY and not track.name:
            return False
        if self.name_regex and self.name_op in (NameOp.MATCHES, NameOp.NOT_MATCHES):
            try:
                hit = bool(userregex.search(self.name_regex, track.name))
            except userregex.error:
                return False
            if hit == (self.name_op == NameOp.NOT_MATCHES):
                return False
        if self.is_default is not None and track.flag("default") != self.is_default:
            return False
        if self.is_forced is not None and track.flag("forced") != self.is_forced:
            return False
        for key, wanted in self.flags.items():
            if key in FLAGS and track.flag(key) != wanted:
                return False
        for key in self.numeric_keys():
            actual = numeric_value(track, key)
            cond = self.numbers[key]
            if actual is None or not cond.op.test(float(actual), cond.value):
                return False
        return True

    def describe(self) -> str:
        parts = [self.track_type.label]
        if self.positions:
            parts.append(f"no. {format_positions(self.positions)}")
        if self.languages:
            parts.append(("not " if self.languages_not else "") + "language " + "/".join(self.languages))
        if self.codec_contains:
            parts.append(f"codec {'!~' if self.codec_not else '~'} {self.codec_contains}")
        if self.name_op == NameOp.EMPTY:
            parts.append("no name")
        elif self.name_op == NameOp.NOT_EMPTY:
            parts.append("has a name")
        elif self.name_regex:
            parts.append(f"name {'!~' if self.name_op == NameOp.NOT_MATCHES else '~'} /{self.name_regex}/")
        for key in self.numeric_keys():
            parts.append(numeric_chip(key, self.numbers[key]))
        for label, cond in (("path", self.path), ("file", self.file_name)):
            if cond and cond.active:
                parts.append(text_chip(label, cond))
        if self.is_default is not None:
            parts.append("default" if self.is_default else "not default")
        if self.is_forced is not None:
            parts.append("forced" if self.is_forced else "not forced")
        for key, wanted in self.flags.items():
            if key in FLAGS:
                parts.append(("" if wanted else "not ") + FLAGS[key][2].lower())
        if not self.positions:  # positions name the tracks themselves
            parts.append("all matches" if self.match_mode == MatchMode.ALL else "first match")
        return ", ".join(parts)


def text_chip(label: str, cond: TextCondition) -> str:
    """'path ~ Anime', 'file !~ OVA', 'file ~ /S\\d+E\\d+/' (slashes mark a regular expression)."""
    value = f"/{cond.value}/" if cond.op.is_regex else cond.value
    return f"{label} {'!~' if cond.op.negated else '~'} {value}"


def numeric_chip(key: str, cond: NumCondition) -> str:
    label, unit, _ = NUMERIC[key]
    return f"{label.lower()} {cond.op.symbol} {format_value(cond.value)}{' ' + unit if unit else ''}"


def format_value(value: float) -> str:
    """48.0 -> "48", 23.976 -> "23.976"."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


class TrackRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    label: str = ""
    enabled: bool = True
    matcher: TrackMatcher
    actions: TrackActions = Field(default_factory=TrackActions)

    @property
    def display_label(self) -> str:
        return self.label or self.matcher.describe()


class TrackPreset(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    actions: TrackActions = Field(default_factory=TrackActions)
    matcher: TrackMatcher | None = None


# --------------------------------------------------------------------------- general


class TitleMode(str, Enum):
    UNCHANGED = "unchanged"
    SET = "set"
    CLEAR = "clear"


class SourceMode(str, Enum):
    UNCHANGED = "unchanged"
    REMOVE = "remove"
    FILE = "file"  # one fixed file for all MKVs
    PER_MKV = "per_mkv"  # <mkv without extension><suffix><ext> next to the MKV


class ExternalSource(BaseModel):
    mode: SourceMode = SourceMode.UNCHANGED
    file_path: str = ""
    suffix: str = ""
    extension: str = ".xml"
    target: str = "all"  # tags only: all | global


class StatsTagsMode(str, Enum):
    UNCHANGED = "unchanged"
    ADD = "add"
    DELETE = "delete"


class GeneralSettings(BaseModel):
    title_mode: TitleMode = TitleMode.UNCHANGED
    title_template: str = "{file_name}"
    num_start: int = 1
    num_padding: int = 2
    # regular expression on the file name (without extension); its groups become {1}, {2}, ...
    name_pattern: str = ""
    chapters: ExternalSource = Field(default_factory=ExternalSource)
    tags: ExternalSource = Field(default_factory=ExternalSource)
    stats_tags: StatsTagsMode = StatsTagsMode.UNCHANGED
    extra_args: str = ""


# --------------------------------------------------------------------------- attachments


class AttachmentSelector(str, Enum):
    NAME = "name"
    ID = "id"
    UID = "uid"
    MIME = "mime-type"

    @property
    def label(self) -> str:
        return {"name": "Name", "id": "ID", "uid": "UID", "mime-type": "MIME type"}[self.value]


class AttachmentAdd(BaseModel):
    path: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


class AttachmentReplace(BaseModel):
    selector: AttachmentSelector = AttachmentSelector.NAME
    value: str
    path: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


class AttachmentDelete(BaseModel):
    selector: AttachmentSelector = AttachmentSelector.NAME
    value: str


class AttachmentOps(BaseModel):
    add: list[AttachmentAdd] = Field(default_factory=list)
    replace: list[AttachmentReplace] = Field(default_factory=list)
    delete: list[AttachmentDelete] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.add or self.replace or self.delete)


# --------------------------------------------------------------------------- presets & settings


class GlobalPreset(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str = ""
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    rules: list[TrackRule] = Field(default_factory=list)
    attachments: AttachmentOps = Field(default_factory=AttachmentOps)


DEFAULT_DROPDOWN_LANGUAGES = ["und", "ger", "eng", "jpn", "fre", "spa", "ita"]


class AppSettings(BaseModel):
    mkvtoolnix_dir: str = ""
    theme: str = "auto"  # auto | light | dark
    workers: int = 1
    slow_file_minutes: int = 10  # ask what to do when mkvpropedit takes longer for one file; 0 = never ask
    recursive: bool = True
    only_changes: bool = True
    # languages offered in the dropdown of the rule editor; any other one can still be typed there
    dropdown_languages: list[str] = Field(default_factory=lambda: list(DEFAULT_DROPDOWN_LANGUAGES))
    last_preset: str = ""
    preset_modified: bool = False  # the restored state differs from the saved preset `last_preset`
    last_dir: str = ""
