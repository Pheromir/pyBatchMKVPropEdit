"""Reads MKV files with `mkvmerge -J`."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

from .mkvtoolnix import run_hidden
from .models import FLAGS, AttachmentInfo, FileInfo, TrackInfo, TrackType

MKV_EXTENSIONS = {".mkv", ".mka", ".mk3d", ".webm", ".mks"}

_cache: dict[tuple[str, int, int], FileInfo] = {}


def parse_identification(path: str, data: dict) -> FileInfo:
    info = FileInfo(path=path)
    container = data.get("container") or {}
    if not container.get("recognized", True) or not container.get("supported", True):
        info.error = "File format not recognized/supported"
        return info
    if container.get("type") and container.get("type") != "Matroska":
        info.error = f"Not a Matroska container ({container.get('type')})"
        return info
    props = container.get("properties") or {}
    info.title = props.get("title", "") or ""
    info.duration = _int(props.get("duration"))

    counters: dict[TrackType, int] = {}
    for t in data.get("tracks") or []:
        try:
            ttype = TrackType(t.get("type"))
        except ValueError:
            continue
        counters[ttype] = counters.get(ttype, 0) + 1
        p = t.get("properties") or {}
        flags = {key: bool(p[json_key]) for key, (_, json_key, _) in FLAGS.items() if json_key in p}
        info.tracks.append(
            TrackInfo(
                id=t.get("id", 0),
                uid=int(p.get("uid", 0) or 0),
                number=int(p.get("number", 0) or 0),
                type=ttype,
                index_in_type=counters[ttype],
                codec=t.get("codec", "") or "",
                codec_id=p.get("codec_id", "") or "",
                language=p.get("language", "und") or "und",
                language_ietf=p.get("language_ietf", "") or "",
                name=p.get("track_name", "") or "",
                flags=flags,
                channels=p.get("audio_channels"),
                dimensions=p.get("display_dimensions") or p.get("pixel_dimensions") or "",
                pixel_dimensions=p.get("pixel_dimensions") or "",
                bitrate=_int(p.get("tag_bps")),
                sample_rate=_int(p.get("audio_sampling_frequency")),
                bit_depth=_int(p.get("audio_bits_per_sample")),
                frame_duration=_int(p.get("default_duration")),
            )
        )
    for a in data.get("attachments") or []:
        info.attachments.append(
            AttachmentInfo(
                id=a.get("id", 0),
                uid=int((a.get("properties") or {}).get("uid", 0) or 0),
                file_name=a.get("file_name", "") or "",
                mime_type=a.get("content_type", "") or "",
                description=a.get("description", "") or "",
                size=a.get("size", 0) or 0,
            )
        )
    info.chapter_entries = _entries(data.get("chapters"))
    info.global_tags = _entries(data.get("global_tags"))
    # "track_tags" leaves out the statistics tags, but every tag shows up as a "tag_..." track property
    as_properties = sum(
        1 for t in data.get("tracks") or [] for key in (t.get("properties") or {}) if key.startswith("tag_")
    )
    info.track_tags = max(_entries(data.get("track_tags")), as_properties)
    return info


def _int(value) -> int | None:
    """Numbers come as int or, in the statistics tags, as text; missing or 0 means unknown."""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n or None


def _entries(items: list | None) -> int:
    return sum(int(i.get("num_entries", 0) or 0) for i in items or [])


def probe(mkvmerge: Path | str, path: str, use_cache: bool = True) -> FileInfo:
    try:
        st = os.stat(path)
    except OSError as e:
        return FileInfo(path=path, error=str(e))
    key = (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)
    if use_cache and key in _cache:
        return _cache[key].model_copy(deep=True)
    try:
        proc = run_hidden([str(mkvmerge), "-J", path], timeout=120)
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        return FileInfo(path=path, error=f"mkvmerge failed: {e}")
    if data.get("errors"):
        return FileInfo(path=path, error="; ".join(map(str, data["errors"])))
    info = parse_identification(path, data)
    if not info.error:
        _cache[key] = info.model_copy(deep=True)
    return info


def collect_files(paths: Iterable[str], recursive: bool = True) -> list[str]:
    """Expands folders to MKV files (sorted) and keeps the order of the input."""
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        try:
            if p.is_dir():
                found: list[str] = []
                try:
                    for f in p.rglob("*") if recursive else p.glob("*"):
                        if f.suffix.lower() in MKV_EXTENSIONS and f.is_file():
                            found.append(str(f))
                except OSError:  # a folder that cannot be read: keep what was found so far
                    pass
                out.extend(sorted(found, key=lambda s: s.lower()))
            elif p.is_file() and p.suffix.lower() in MKV_EXTENSIONS:
                out.append(str(p))
        except OSError:
            continue
    return out
