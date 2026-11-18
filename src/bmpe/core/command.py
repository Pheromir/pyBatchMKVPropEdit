"""Builds the mkvpropedit arguments and a readable list of changes for each file."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .languages import language_problem
from .matcher import resolve
from .models import (
    FLAGS,
    AttachmentSelector,
    ExternalSource,
    FileInfo,
    GlobalPreset,
    NameMode,
    SourceMode,
    StatsTagsMode,
    TitleMode,
    TrackInfo,
    TriState,
    language_differs,
)
from .placeholders import file_context, render, track_context

SCOPE_GENERAL = "General"
SCOPE_ATTACHMENTS = "Attachments"
FIELD_NAME = "Name"
FIELD_LANGUAGE = "Language"
FIELD_EXTRA = "Extra parameters"
YES, NO = "yes", "no"


@dataclass
class Change:
    scope: str  # SCOPE_GENERAL, SCOPE_ATTACHMENTS or a track description
    field: str
    old: str
    new: str


@dataclass
class FilePlan:
    file: FileInfo
    args: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        return bool(self.args) and not self.file.error

    def command_line(self, exe: str = "mkvpropedit") -> str:
        return subprocess.list2cmdline([exe, self.file.path, *self.args])


def split_args(text: str) -> list[str]:
    """Splits free-form parameters at whitespace; "..." and '...' group. Backslashes are kept."""
    args: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    has_token = False
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch in "\"'":
            quote = ch
            has_token = True
        elif ch.isspace():
            if cur or has_token:
                args.append("".join(cur))
                cur, has_token = [], False
        else:
            cur.append(ch)
    if cur or has_token:
        args.append("".join(cur))
    return args


def render_args(template: str, ctx: dict[str, str]) -> tuple[list[str], list[str]]:
    """Splits free-form parameters first and fills in the placeholders afterwards.

    That way quotes and spaces inside a value (a file name like "Don't Look Up") stay untouched.
    """
    args: list[str] = []
    unknown: list[str] = []
    for token in split_args(template):
        text, missing = render(token, ctx)
        args.append(text)
        unknown += missing
    return args, unknown


def _bool_str(value: bool) -> str:
    return YES if value else NO


def _external_path(src: ExternalSource, mkv: Path) -> str:
    if src.mode == SourceMode.FILE:
        return src.file_path
    if src.mode == SourceMode.PER_MKV:
        ext = src.extension if src.extension.startswith(".") else "." + src.extension
        return str(mkv.with_name(mkv.stem + src.suffix + ext))
    return ""


def attachment_selector(selector: AttachmentSelector, value: str, replace: bool = False) -> str:
    """Selector for --delete-attachment, or for --replace-attachment (`replace`).

    Only --replace-attachment wants colons in a name escaped, because a file name follows the selector;
    --delete-attachment takes the name literally.
    """
    value = value.strip()
    if selector == AttachmentSelector.NAME:
        return "name:" + (value.replace(":", r"\c") if replace else value)
    if selector == AttachmentSelector.MIME:
        return "mime-type:" + value
    if selector == AttachmentSelector.UID:
        return "=" + value
    return value


def attachment_matches(file: FileInfo, selector: AttachmentSelector, value: str) -> bool:
    value = value.strip()
    for a in file.attachments:
        if selector == AttachmentSelector.NAME and a.file_name == value:
            return True
        if selector == AttachmentSelector.MIME and a.mime_type.lower() == value.lower():
            return True
        if selector == AttachmentSelector.ID and str(a.id) == value:
            return True
        if selector == AttachmentSelector.UID and str(a.uid) == value:
            return True
    return False


def _track_selector(track: TrackInfo) -> str:
    if track.number:
        return f"track:@{track.number}"
    return f"track:{track.id + 1}"


def plan_file(file: FileInfo, preset: GlobalPreset, index: int, only_changes: bool = True) -> FilePlan:
    plan = FilePlan(file=file)
    if file.error:
        plan.warnings.append(f"File could not be read: {file.error}")
        return plan

    g = preset.general
    mkv = Path(file.path)
    fctx = file_context(file, index, g)
    args = plan.args

    def warn_unknown(unknown: list[str], where: str) -> None:
        for key in unknown:
            plan.warnings.append(f"Unknown placeholder {{{key}}} in {where}.")

    # --- tags
    tags = g.tags
    target = tags.target if tags.target in ("all", "global") else "all"
    if tags.mode == SourceMode.REMOVE:
        present = file.global_tags + (file.track_tags if target == "all" else 0)
        if present or not only_changes:
            args += ["--tags", f"{target}:"]
            plan.changes.append(Change(SCOPE_GENERAL, "Tags", f"{present} entries", f"remove ({target})"))
    elif tags.mode in (SourceMode.FILE, SourceMode.PER_MKV):
        path = _external_path(tags, mkv)
        if path and Path(path).is_file():
            args += ["--tags", f"{target}:{path}"]
            plan.changes.append(Change(SCOPE_GENERAL, "Tags", "", f"from {Path(path).name}"))
        else:
            plan.warnings.append(f"Tag file not found: {path or '(empty)'}")

    # --- chapters
    chaps = g.chapters
    if chaps.mode == SourceMode.REMOVE:
        if file.chapter_entries or not only_changes:
            args += ["--chapters", ""]
            plan.changes.append(Change(SCOPE_GENERAL, "Chapters", f"{file.chapter_entries} entries", "remove"))
    elif chaps.mode in (SourceMode.FILE, SourceMode.PER_MKV):
        path = _external_path(chaps, mkv)
        if path and Path(path).is_file():
            args += ["--chapters", path]
            plan.changes.append(Change(SCOPE_GENERAL, "Chapters", "", f"from {Path(path).name}"))
        else:
            plan.warnings.append(f"Chapter file not found: {path or '(empty)'}")

    # --- track statistics tags
    if g.stats_tags == StatsTagsMode.ADD:
        args.append("--add-track-statistics-tags")
        plan.changes.append(Change(SCOPE_GENERAL, "Statistics tags", "", "add/update"))
    elif g.stats_tags == StatsTagsMode.DELETE:
        args.append("--delete-track-statistics-tags")
        plan.changes.append(Change(SCOPE_GENERAL, "Statistics tags", "", "remove"))

    # --- title
    if g.title_mode == TitleMode.SET:
        title, unknown = render(g.title_template, fctx)
        warn_unknown(unknown, "title")
        if title != file.title or not only_changes:
            args += ["--edit", "info", "--set", f"title={title}"]
            plan.changes.append(Change(SCOPE_GENERAL, "Title", file.title, title))
    elif g.title_mode == TitleMode.CLEAR:
        if file.title or not only_changes:
            args += ["--edit", "info", "--delete", "title"]
            plan.changes.append(Change(SCOPE_GENERAL, "Title", file.title, "(removed)"))

    # --- attachments
    att = preset.attachments
    for d in att.delete:
        if not d.value.strip():
            continue
        if only_changes and not attachment_matches(file, d.selector, d.value):
            continue
        args += ["--delete-attachment", attachment_selector(d.selector, d.value)]
        plan.changes.append(Change(SCOPE_ATTACHMENTS, "Delete", f"{d.selector.label}: {d.value}", ""))
    for a in att.add:
        if not Path(a.path).is_file():
            plan.warnings.append(f"Attachment not found: {a.path}")
            continue
        args += _attachment_meta(a.name, a.description, a.mime_type)
        args += ["--add-attachment", a.path]
        plan.changes.append(Change(SCOPE_ATTACHMENTS, "Add", "", a.name or Path(a.path).name))
    for r in att.replace:
        if not r.value.strip():
            continue
        if not Path(r.path).is_file():
            plan.warnings.append(f"Replacement attachment not found: {r.path}")
            continue
        if not attachment_matches(file, r.selector, r.value):
            plan.warnings.append(f"No attachment to replace found ({r.selector.label}: {r.value}).")
            continue
        args += _attachment_meta(r.name, r.description, r.mime_type)
        args += ["--replace-attachment", f"{attachment_selector(r.selector, r.value, replace=True)}:{r.path}"]
        plan.changes.append(Change(SCOPE_ATTACHMENTS, "Replace", f"{r.selector.label}: {r.value}", Path(r.path).name))

    # --- tracks
    resolution = resolve(preset.rules, file)
    plan.warnings.extend(resolution.warnings)
    for entry in resolution.ordered():
        track, actions = entry.track, entry.actions
        scope = track.describe()
        props: list[str] = []
        for key, state in actions.flags.items():
            if state == TriState.UNCHANGED:
                continue
            new = state == TriState.YES
            old = track.flag(key)
            if new == old and only_changes:
                continue
            props += ["--set", f"{FLAGS[key][0]}={int(new)}"]
            plan.changes.append(Change(scope, FLAGS[key][2], _bool_str(old), _bool_str(new)))
        tctx = {**fctx, **track_context(track, actions.language)}
        if actions.name_mode == NameMode.SET:
            name, unknown = render(actions.name_template, tctx)
            warn_unknown(unknown, f"track name ({scope})")
            if name != track.name or not only_changes:
                props += ["--set", f"name={name}"]
                plan.changes.append(Change(scope, FIELD_NAME, track.name, name))
        elif actions.name_mode == NameMode.CLEAR:
            if track.name or not only_changes:
                props += ["--delete", "name"]
                plan.changes.append(Change(scope, FIELD_NAME, track.name, "(removed)"))
        if actions.language and actions.language.strip():
            lang = actions.language.strip()
            message, malformed = language_problem(lang) or ("", False)
            if message:
                skipped = "; the language is left unchanged" if malformed else ""
                plan.warnings.append(f"{scope}: {message}{skipped}.")
            # a malformed code is left out, mkvpropedit would reject the whole file because of it
            if not malformed and (language_differs(lang, track) or not only_changes):
                props += ["--set", f"language={lang}"]
                plan.changes.append(Change(scope, FIELD_LANGUAGE, track.lang_display, lang))
        if actions.extra_args.strip():
            extra, unknown = render_args(actions.extra_args, tctx)
            warn_unknown(unknown, f"extra parameters ({scope})")
            props += extra
            plan.changes.append(Change(scope, FIELD_EXTRA, "", subprocess.list2cmdline(extra)))
        if props:
            args += ["--edit", _track_selector(track), *props]

    # --- global extra parameters
    if g.extra_args.strip():
        extra, unknown = render_args(g.extra_args, fctx)
        warn_unknown(unknown, "global extra parameters")
        args += extra
        plan.changes.append(Change(SCOPE_GENERAL, FIELD_EXTRA, "", subprocess.list2cmdline(extra)))

    return plan


def _attachment_meta(name: str, description: str, mime: str) -> list[str]:
    out: list[str] = []
    if name.strip():
        out += ["--attachment-name", name.strip()]
    if description.strip():
        out += ["--attachment-description", description.strip()]
    if mime.strip():
        out += ["--attachment-mime-type", mime.strip()]
    return out


def plan_batch(files: list[FileInfo], preset: GlobalPreset, only_changes: bool = True) -> list[FilePlan]:
    return [plan_file(f, preset, i, only_changes) for i, f in enumerate(files)]
