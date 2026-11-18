"""Placeholders like {file_name} or {num} in titles, track names and extra parameters."""

from __future__ import annotations

import re
from pathlib import Path

from .languages import language_name
from .models import FileInfo, GeneralSettings, TrackInfo

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

FILE_PLACEHOLDERS = {
    "file_name": "file name without extension",
    "dir_name": "folder name",
    "num": "running number (start/padding under General)",
    "title": "current title",
}
TRACK_PLACEHOLDERS = {
    "track_name": "current track name",
    "lang_name": "language name, e.g. German, Japanese",
    "lang": "language code, e.g. ger, de-DE",
    "format": "short format, e.g. ASS, PGS, FLAC, HEVC",
    "codec": "codec name reported by mkvmerge",
    "channels": "audio channels (e.g. 2.0, 5.1)",
    "track_num": "number of the track within its type",
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


def file_context(file: FileInfo, index: int, general: GeneralSettings) -> dict[str, str]:
    p = Path(file.path)
    return {
        "file_name": p.stem,
        "dir_name": p.parent.name,
        "num": pad_number(general.num_start + index, general.num_padding),
        "title": file.title,
    }


def track_context(track: TrackInfo, new_language: str | None = None) -> dict[str, str]:
    """Track placeholders; if the rule sets a new language, {lang}/{lang_name} refer to it."""
    lang = new_language.strip() if new_language and new_language.strip() else track.lang_display
    return {
        "track_name": track.name,
        "lang": lang,
        "lang_name": language_name(lang),
        "format": short_format(track),
        "codec": track.codec,
        "channels": channel_layout(track.channels),
        "track_num": str(track.index_in_type),
    }


def render(template: str, ctx: dict[str, str]) -> tuple[str, list[str]]:
    """Replaces known placeholders; unknown ones are left as they are and returned."""
    unknown: list[str] = []

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return ctx[key]
        unknown.append(key)
        return m.group(0)

    return PLACEHOLDER_RE.sub(repl, template), unknown
