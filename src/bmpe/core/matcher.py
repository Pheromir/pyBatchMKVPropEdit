"""Resolves track rules for a specific file into actions per track."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import FileInfo, NameMode, TrackActions, TrackInfo, TrackRule, TriState


@dataclass
class ResolvedTrack:
    track: TrackInfo
    actions: TrackActions


@dataclass
class Resolution:
    tracks: dict[int, ResolvedTrack] = field(default_factory=dict)  # key: track ID
    warnings: list[str] = field(default_factory=list)

    def ordered(self) -> list[ResolvedTrack]:
        return [self.tracks[k] for k in sorted(self.tracks)]


def matching_tracks(rule: TrackRule, file: FileInfo) -> list[TrackInfo]:
    hits = [t for t in file.tracks if rule.matcher.matches(t)]
    return hits if rule.matcher.takes_all else hits[:1]


def _merge(target: TrackActions, src: TrackActions, label: str, track: TrackInfo, warnings: list[str]) -> None:
    where = track.describe()
    for key, state in src.flags.items():
        if state == TriState.UNCHANGED:
            continue
        cur = target.flags[key]
        if cur != TriState.UNCHANGED and cur != state:
            warnings.append(f"Conflict at {where}: flag '{key}' is overridden by rule '{label}'.")
        target.flags[key] = state
    if src.name_mode != NameMode.UNCHANGED:
        if target.name_mode != NameMode.UNCHANGED and (
            target.name_mode != src.name_mode or target.name_template != src.name_template
        ):
            warnings.append(f"Conflict at {where}: name is overridden by rule '{label}'.")
        target.name_mode = src.name_mode
        target.name_template = src.name_template
    if src.language:
        if target.language and target.language != src.language:
            warnings.append(f"Conflict at {where}: language is overridden by rule '{label}'.")
        target.language = src.language
    if src.exclusive_default:
        target.exclusive_default = True
    if src.extra_args.strip():
        target.extra_args = (target.extra_args + " " + src.extra_args.strip()).strip()


def resolve(rules: list[TrackRule], file: FileInfo) -> Resolution:
    res = Resolution()
    for rule in rules:
        if not rule.enabled or rule.actions.is_empty():
            continue
        regex_error = rule.matcher.regex_error()
        if regex_error:
            res.warnings.append(
                f"Rule '{rule.display_label}' is skipped: its name condition is not a valid regular expression "
                f"({regex_error})."
            )
            continue
        hits = matching_tracks(rule, file)
        if not hits:
            res.warnings.append(f"Rule '{rule.display_label}' matches no track.")
            continue
        for track in hits:
            entry = res.tracks.get(track.id)
            if entry is None:
                entry = ResolvedTrack(track=track, actions=TrackActions())
                res.tracks[track.id] = entry
            _merge(entry.actions, rule.actions, rule.display_label, track, res.warnings)

    # Exclusive default: the matched track becomes default, all others of the same type do not.
    exclusive = [e for e in res.tracks.values() if e.actions.exclusive_default]
    by_type: dict = {}
    for e in exclusive:
        by_type.setdefault(e.track.type, []).append(e)
    for track_type, entries in by_type.items():
        if len(entries) > 1:
            res.warnings.append(
                f"Several {track_type.label.lower()} tracks are marked as 'exclusive default'; "
                "only the first one becomes default."
            )
        winner = entries[0]
        winner.actions.flags["default"] = TriState.YES
        for e in entries[1:]:
            e.actions.flags["default"] = TriState.NO
        for track in file.tracks_of(track_type):
            if track.id == winner.track.id:
                continue
            entry = res.tracks.get(track.id)
            if entry is None:
                entry = ResolvedTrack(track=track, actions=TrackActions())
                res.tracks[track.id] = entry
            if entry.actions.flags["default"] == TriState.YES:
                res.warnings.append(
                    f"{track.describe()}: 'Default=yes' is overridden by 'exclusive default'."
                )
            entry.actions.flags["default"] = TriState.NO
    return res
