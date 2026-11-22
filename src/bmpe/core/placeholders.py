"""Placeholders like {file_name} or {num} in titles, track names and extra parameters.

A placeholder can carry filters, applied from left to right: {track_name|upper}, {bitrate|suffix: kbps},
{1|or:unknown}. {1}, {2}, ... are the groups of the file name pattern under General.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import userregex
from .languages import language_name
from .models import FileInfo, GeneralSettings, TrackInfo, TrackType

# {key} or {key|filter|filter:argument}; an argument may contain anything but "|", "{" and "}"
PLACEHOLDER_RE = re.compile(r"\{(\w+)((?:\|[^{}|]*)*)\}")

FILE_PLACEHOLDERS = {
    "file_name": "file name without extension",
    "ext": "file extension without the dot, e.g. mkv",
    "dir_name": "folder name",
    "parent_dir": "name of the folder above the folder",
    "num": "running number (start/padding under General)",
    "title": "current title",
    "duration": "duration of the file, e.g. 23:40 or 1:52:08",
    "audio_langs": "languages of all audio tracks, e.g. GER/JPN",
    "sub_langs": "languages of all subtitle tracks, e.g. GER/ENG",
    "video_format": "format of the first video track, e.g. HEVC",
    "resolution": "size of the first video track, e.g. 1920x1080",
    "height": "height of the first video track, e.g. 1080",
    "fps": "frame rate of the first video track, e.g. 23.976",
}
TRACK_PLACEHOLDERS = {
    "track_name": "name of the track before the run",
    "prev_track_name": "name set by the rules above (otherwise the name before the run)",
    "lang_name": "language name, e.g. German, Japanese",
    "lang": "language code, e.g. ger, de-DE",
    "format": "short format, e.g. ASS, PGS, FLAC, HEVC",
    "codec": "codec name reported by mkvmerge",
    "channels": "audio channels, e.g. 2.0, 5.1",
    "channels_name": "Mono, Stereo or Surround",
    "bitrate": "bitrate in kbps, e.g. 640 (needs statistics tags)",
    "sample_rate": "sample rate in kHz, e.g. 48",
    "bit_depth": "bits per sample, e.g. 24",
    "track_num": "number of the track within its type",
}
PATTERN_PLACEHOLDERS = {
    "1": "group 1 of the file name pattern (General); {2}, {3}, ... likewise",
    "0": "the whole match of the file name pattern",
}
# filter -> description; filters with an argument are written as filter:argument
FILTERS = {
    "upper": "upper case",
    "lower": "lower case",
    "title": "first letter of every word in upper case",
    "pad:N": "fill a number with zeros to N digits",
    "replace:OLD:NEW": "replace OLD with NEW (NEW may be empty)",
    "prefix:TEXT": "put TEXT in front, only if the value is not empty",
    "suffix:TEXT": "put TEXT after it, only if the value is not empty",
    "or:TEXT": "use TEXT if the value is empty",
}

# CodecID (prefix) -> short name
_FORMATS = [
    ("S_TEXT/ASS", "ASS"),
    ("S_TEXT/SSA", "SSA"),
    ("S_ASS", "ASS"),
    ("S_SSA", "SSA"),
    ("S_HDMV/PGS", "PGS"),
    ("S_HDMV/TEXTST", "TextST"),
    ("S_TEXT/UTF8", "SRT"),
    ("S_TEXT/ASCII", "SRT"),
    ("S_TEXT/WEBVTT", "WebVTT"),
    ("S_TEXT/USF", "USF"),
    ("S_VOBSUB", "VobSub"),
    ("S_DVBSUB", "DVB"),
    ("S_KATE", "Kate"),
    ("A_FLAC", "FLAC"),
    ("A_AAC", "AAC"),
    ("A_AC3", "AC-3"),
    ("A_EAC3", "E-AC-3"),
    ("A_TRUEHD", "TrueHD"),
    ("A_MLP", "MLP"),
    ("A_OPUS", "Opus"),
    ("A_VORBIS", "Vorbis"),
    ("A_MPEG/L3", "MP3"),
    ("A_MPEG/L2", "MP2"),
    ("A_PCM", "PCM"),
    ("A_ALAC", "ALAC"),
    ("V_MPEGH/ISO/HEVC", "HEVC"),
    ("V_MPEG4/ISO/AVC", "AVC"),
    ("V_AV1", "AV1"),
    ("V_VP9", "VP9"),
    ("V_VP8", "VP8"),
    ("V_MPEG2", "MPEG-2"),
    ("V_MPEG4/ISO", "MPEG-4"),
    ("V_MS/VFW/FOURCC", "VfW"),
]


def short_format(track: TrackInfo) -> str:
    cid = track.codec_id.upper()
    if cid.startswith("A_DTS"):
        codec = track.codec.lower()
        if "master audio" in codec:
            return "DTS-HD MA"
        if "high resolution" in codec or "dts-hd" in codec:
            return "DTS-HD"
        if "express" in codec:
            return "DTS Express"
        return "DTS"
    for prefix, name in _FORMATS:
        if cid.startswith(prefix):
            return name
    return track.codec.split("/")[0].strip() or cid


def pad_number(value: int, padding: int) -> str:
    return str(value).zfill(max(padding, 0))


def channel_layout(channels: int | None) -> str:
    if not channels:
        return ""
    return {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}.get(channels, str(channels))


def channel_name(channels: int | None) -> str:
    """Mono / Stereo / Surround, meant to follow {channels}: "2.0 Stereo", "5.1 Surround"."""
    if not channels:
        return ""
    return {1: "Mono", 2: "Stereo"}.get(channels, "Surround")


def format_number(value: float | None) -> str:
    """23.976 -> "23.976", 48.0 -> "48", None -> ""."""
    if value is None:
        return ""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def format_duration(ns: int | None) -> str:
    if not ns:
        return ""
    total = round(ns / 1e9)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def languages_of(file: FileInfo, track_type: TrackType) -> str:
    """Language codes of all tracks of a type, each once and in track order, e.g. "GER/JPN"."""
    seen: list[str] = []
    for t in file.tracks_of(track_type):
        code = (t.language or "und").upper()
        if code != "UND" and code not in seen:
            seen.append(code)
    return "/".join(seen)


def pattern_groups(pattern: str, file_name: str) -> tuple[dict[str, str] | None, str]:
    """{"0": whole match, "1": group 1, ...} of the file name pattern, and what went wrong.

    Without a pattern: (None, ""). If the pattern is invalid or does not match, the groups are empty and the
    second value says why.
    """
    if not pattern.strip():
        return None, ""
    error = userregex.compile_error(pattern)
    if error:
        return {}, f"The file name pattern is not a valid regular expression ({error})."
    empty = {str(i): "" for i in range(userregex.group_count(pattern) + 1)}
    try:
        m = userregex.search(pattern, file_name)
    except userregex.RegexTimeout:
        return empty, f'The file name pattern took too long on "{file_name}" and was stopped.'
    if not m:
        return empty, f'The file name pattern does not match "{file_name}".'
    return {k: m.group(int(k)) or "" for k in empty}, ""


def file_context(file: FileInfo, index: int, general: GeneralSettings) -> dict[str, str]:
    p = Path(file.path)
    video = file.tracks_of(TrackType.VIDEO)
    first = video[0] if video else None
    ctx = {
        "file_name": p.stem,
        "ext": p.suffix.lstrip("."),
        "dir_name": p.parent.name,
        "parent_dir": p.parent.parent.name,
        "num": pad_number(general.num_start + index, general.num_padding),
        "title": file.title,
        "duration": format_duration(file.duration),
        "audio_langs": languages_of(file, TrackType.AUDIO),
        "sub_langs": languages_of(file, TrackType.SUBTITLES),
        "video_format": short_format(first) if first else "",
        "resolution": "x".join(map(str, first.size)) if first and first.size else "",
        "height": str(first.height) if first and first.height else "",
        "fps": format_number(first.fps) if first else "",
    }
    groups, _ = pattern_groups(general.name_pattern, p.stem)
    ctx.update(groups or {})
    return ctx


def track_context(track: TrackInfo, new_language: str | None = None) -> dict[str, str]:
    """Track placeholders; if the rule sets a new language, {lang}/{lang_name} refer to it."""
    lang = new_language.strip() if new_language and new_language.strip() else track.lang_display
    ctx = {
        "track_name": track.name,
        "lang": lang,
        "lang_name": language_name(lang),
        "format": short_format(track),
        "codec": track.codec,
        "channels": channel_layout(track.channels),
        "channels_name": channel_name(track.channels),
        "bitrate": str(track.bitrate_kbps or ""),
        "sample_rate": format_number(track.sample_rate_khz),
        "bit_depth": str(track.bit_depth or ""),
        "track_num": str(track.index_in_type),
    }
    if track.type == TrackType.VIDEO:  # a video track describes itself, not the first video track
        ctx["video_format"] = ctx["format"]
        ctx["resolution"] = "x".join(map(str, track.size)) if track.size else ""
        ctx["height"] = str(track.height or "")
        ctx["fps"] = format_number(track.fps)
    return ctx


def apply_filter(value: str, spec: str) -> str | None:
    """One filter such as "upper" or "pad:3"; None if the filter is unknown or its argument is invalid."""
    name, _, arg = spec.partition(":")
    name = name.strip().lower()
    if name == "upper":
        return value.upper()
    if name == "lower":
        return value.lower()
    if name == "title":
        return " ".join(w[:1].upper() + w[1:] for w in value.split(" "))
    if name == "pad":
        if not arg.strip().isdigit():
            return None
        return value.zfill(int(arg)) if value.isdigit() else value
    if name == "replace":
        old, sep, new = arg.partition(":")
        if not sep or not old:
            return None
        return value.replace(old, new)
    if name == "prefix":
        return arg + value if value else value
    if name == "suffix":
        return value + arg if value else value
    if name == "or":
        return value or arg
    return None


def render(template: str, ctx: dict[str, str]) -> tuple[str, list[str]]:
    """Replaces known placeholders and applies their filters.

    Unknown placeholders and placeholders with an unknown filter are left as they are and returned
    (without the braces).
    """
    unknown: list[str] = []

    def repl(m: re.Match) -> str:
        key, chain = m.group(1), m.group(2)
        if key not in ctx:
            unknown.append(m.group(0)[1:-1])
            return m.group(0)
        value = ctx[key]
        for spec in chain.split("|")[1:]:
            result = apply_filter(value, spec)
            if result is None:
                unknown.append(m.group(0)[1:-1])
                return m.group(0)
            value = result
        return value

    return PLACEHOLDER_RE.sub(repl, template), unknown
