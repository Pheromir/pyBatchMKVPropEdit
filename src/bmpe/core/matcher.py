"""Resolves track rules for a specific file into actions per track.

The rules are evaluated from the top of the list. Every rule sees the tracks as the rules above it left them:
flags, language and name set further up count for its conditions and its placeholders, and what it sets counts
for the rules below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import FileInfo, GeneralSettings, NameMode, TrackActions, TrackInfo, TrackRule, TriState
from .placeholders import file_context, render, track_context
from .userregex import RegexTimeout

# a name template that uses the name of the rules above builds on it instead of replacing it
PREV_NAME_RE = re.compile(r"\{prev_track_name[|}]")


@dataclass
class ResolvedTrack:
    track: TrackInfo  # as it is in the file
    actions: TrackActions  # merged actions of all rules
    name: str = ""  # the name after all rules (only meaningful if `renamed`)
    renamed: bool = False  # a rule set or removed the name
    name_removed: bool = False  # the last name change removes the name


@dataclass
class Resolution:
    tracks: dict[int, ResolvedTrack] = field(default_factory=dict)  # key: track ID
    warnings: list[str] = field(default_factory=list)
    # rule id -> the tracks the rule matches at its place in the list (also for switched-off or empty rules)
    hits: dict[str, list[TrackInfo]] = field(default_factory=dict)

    def ordered(self) -> list[ResolvedTrack]:
        return [self.tracks[k] for k in sorted(self.tracks)]


def _hits_on(rule: TrackRule, file: FileInfo, tracks: list[TrackInfo], stopped: list[str] | None = None):
    """The matching tracks. A regular expression that runs too long counts as no match and is noted in `stopped`."""

    def check(test, what: str) -> bool:
        try:
            return test()
        except RegexTimeout:
            if stopped is not None:
                stopped.append(what)
            return False

    if not check(lambda: rule.matcher.file_matches(file.path), "the path or file name"):
        return []
    hits = [t for t in tracks if check(lambda t=t: rule.matcher.matches(t), t.describe())]
    return hits if rule.matcher.takes_all else hits[:1]


def matching_tracks(rule: TrackRule, file: FileInfo) -> list[TrackInfo]:
    """The tracks a rule matches on its own, in the file as it is (without the rules above)."""
    return _hits_on(rule, file, file.tracks)


def _no_match_hint(rule: TrackRule, file: FileInfo) -> str:
    """Why a rule may have found nothing: tracks of its type that do not report a compared value."""
    try:
        file_ok = rule.matcher.file_matches(file.path)
    except RegexTimeout:
        return ""  # reported separately
    if not file_ok:
        return " (the file does not meet its path or file name condition)"
    missing: dict[str, int] = {}
    for t in file.tracks_of(rule.matcher.track_type):
        for label in rule.matcher.unknown_values(t):
            missing[label] = missing.get(label, 0) + 1
    if not missing:
        return ""
    text = ", ".join(f"{label} is unknown for {n} track(s)" for label, n in missing.items())
    if "Bitrate" in missing:
        text += "; the bitrate comes from the track statistics tags"
    return f" ({text})"


def _set_flag(entry: ResolvedTrack, state_now: TrackInfo, key: str, state: TriState, label: str, warnings) -> None:
    cur = entry.actions.flags[key]
    if cur != TriState.UNCHANGED and cur != state:
        warnings.append(f"Conflict at {entry.track.describe()}: flag '{key}' is overridden by rule '{label}'.")
    entry.actions.flags[key] = state
    state_now.flags[key] = state == TriState.YES


def _apply(
    entry: ResolvedTrack, now: TrackInfo, src: TrackActions, label: str, fctx: dict[str, str], warnings: list[str]
) -> None:
    """Adds one rule's actions to a track; `now` is the running state the rules below will see."""
    target, track = entry.actions, entry.track
    where = track.describe()
    for key, state in src.flags.items():
        if state != TriState.UNCHANGED:
            _set_flag(entry, now, key, state, label, warnings)
    if src.language:
        if target.language and target.language != src.language:
            warnings.append(f"Conflict at {where}: language is overridden by rule '{label}'.")
        target.language = src.language
        now.language = now.language_ietf = src.language.strip()
    if src.name_mode != NameMode.UNCHANGED:
        builds_on = src.name_mode == NameMode.SET and PREV_NAME_RE.search(src.name_template)
        if target.name_mode != NameMode.UNCHANGED and not builds_on and (
            target.name_mode != src.name_mode or target.name_template != src.name_template
        ):
            warnings.append(f"Conflict at {where}: name is overridden by rule '{label}'.")
        target.name_mode = src.name_mode
        target.name_template = src.name_template
        if src.name_mode == NameMode.CLEAR:
            now.name, entry.name_removed = "", True
        else:
            # filled in right away: {lang}/{lang_name} are the language so far, {prev_track_name} the name so far
            ctx = {**fctx, **track_context(track, target.language), "prev_track_name": now.name}
            now.name, unknown = render(src.name_template, ctx)
            entry.name_removed = False
            for key in unknown:
                warnings.append(f"Unknown placeholder or filter {{{key}}} in track name ({where}).")
        entry.name, entry.renamed = now.name, True
    if src.exclusive_default:
        target.exclusive_default = True
    if src.extra_args.strip():
        target.extra_args = (target.extra_args + " " + src.extra_args.strip()).strip()


def resolve(rules: list[TrackRule], file: FileInfo, fctx: dict[str, str] | None = None) -> Resolution:
    """`fctx`: the file placeholders for track names (plan_file passes them with the right {num})."""
    if fctx is None:
        fctx = file_context(file, 0, GeneralSettings())
    res = Resolution()
    now = {t.id: t.model_copy(deep=True) for t in file.tracks}  # tracks as the rules so far left them
    original = {t.id: t for t in file.tracks}

    def entry_for(track_id: int) -> ResolvedTrack:
        entry = res.tracks.get(track_id)
        if entry is None:
            entry = ResolvedTrack(track=original[track_id], actions=TrackActions(), name=original[track_id].name)
            res.tracks[track_id] = entry
        return entry

    for rule in rules:
        regex_error = rule.matcher.regex_error()
        stopped: list[str] = []
        hits = [] if regex_error else _hits_on(rule, file, [now[t.id] for t in file.tracks], stopped)
        res.hits[rule.id] = [original[t.id] for t in hits]
        for what in stopped:
            res.warnings.append(
                f"Rule '{rule.display_label}': a regular expression took too long on {what} and was stopped; "
                "it counts as no match."
            )
        if not rule.enabled or rule.actions.is_empty():
            continue
        if regex_error:
            res.warnings.append(
                f"Rule '{rule.display_label}' is skipped: a condition is not a valid regular expression "
                f"({regex_error})."
            )
            continue
        if not hits:
            res.warnings.append(f"Rule '{rule.display_label}' matches no track{_no_match_hint(rule, file)}.")
            continue
        for track in hits:
            _apply(entry_for(track.id), now[track.id], rule.actions, rule.display_label, fctx, res.warnings)

        # exclusive default: the first matched track becomes default, every other track of the type does not
        if rule.actions.exclusive_default:
            winner = hits[0]
            if len(hits) > 1:
                res.warnings.append(
                    f"Rule '{rule.display_label}' marks several tracks as 'exclusive default'; "
                    "only the first one becomes default."
                )
            for track in file.tracks_of(rule.matcher.track_type):
                state = TriState.YES if track.id == winner.id else TriState.NO
                _set_flag(entry_for(track.id), now[track.id], "default", state, rule.display_label, res.warnings)
    return res
