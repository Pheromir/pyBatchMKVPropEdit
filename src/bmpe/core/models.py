"""Data model: probed files, rules, actions and presets."""

from __future__ import annotations

import re
import uuid
from enum import Enum

from pydantic import BaseModel, Field, field_validator

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
    dimensions: str = ""

    def flag(self, key: str) -> bool:
        return self.flags.get(key, FLAG_DEFAULTS.get(key, False))

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


class TrackMatcher(BaseModel):
    track_type: TrackType
    positions: list[int] = Field(default_factory=list)  # nth track(s) of this type, 1-based; empty = any
    languages: list[str] = Field(default_factory=list)
    codec_contains: str = ""
    name_regex: str = ""
    is_default: bool | None = None
    is_forced: bool | None = None
    match_mode: MatchMode = MatchMode.FIRST

    @property
    def takes_all(self) -> bool:
        """Whether the rule applies to every matching track.

        Positions name the tracks themselves, so "first match only" does not apply to them: "1, 3" means
        track 1 and track 3 (as far as they meet the other conditions).
        """
        return bool(self.positions) or self.match_mode == MatchMode.ALL

    def regex_error(self) -> str:
        """Why `name_regex` cannot be used, or "" if it is fine."""
        if not self.name_regex:
            return ""
        try:
            re.compile(self.name_regex)
        except re.error as e:
            return str(e)
        return ""

    def matches(self, track: TrackInfo) -> bool:
        if track.type != self.track_type:
            return False
        if self.positions and track.index_in_type not in self.positions:
            return False
        if self.languages:
            wanted = [lang for lang in self.languages if lang.strip()]
            if wanted and not any(language_matches(lang, track) for lang in wanted):
                return False
        if self.codec_contains.strip():
            needle = self.codec_contains.strip().lower()
            if needle not in track.codec.lower() and needle not in track.codec_id.lower():
                return False
        if self.name_regex:
            try:
                if not re.search(self.name_regex, track.name, re.IGNORECASE):
                    return False
            except re.error:
                return False
        if self.is_default is not None and track.flag("default") != self.is_default:
            return False
        if self.is_forced is not None and track.flag("forced") != self.is_forced:
            return False
        return True

    def describe(self) -> str:
        parts = [self.track_type.label]
        if self.positions:
            parts.append(f"no. {format_positions(self.positions)}")
        if self.languages:
            parts.append("language " + "/".join(self.languages))
        if self.codec_contains:
            parts.append(f"codec ~ {self.codec_contains}")
        if self.name_regex:
            parts.append(f"name ~ /{self.name_regex}/")
        if self.is_default is not None:
            parts.append("default" if self.is_default else "not default")
        if self.is_forced is not None:
            parts.append("forced" if self.is_forced else "not forced")
        if not self.positions:  # positions name the tracks themselves
            parts.append("all matches" if self.match_mode == MatchMode.ALL else "first match")
        return ", ".join(parts)


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
