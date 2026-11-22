"""Short descriptions of a rule: chips for the rule list and one plain sentence for the editor."""

from __future__ import annotations

from .languages import language_name
from .models import (
    FLAGS,
    NUMERIC,
    MatchMode,
    NameMode,
    NameOp,
    NumOp,
    TextOp,
    TrackActions,
    TrackMatcher,
    TrackRule,
    TrackType,
    TriState,
    format_positions,
    format_value,
    numeric_chip,
    text_chip,
)

# flag -> (text when set, text when cleared)
_FLAG_CHIPS = {
    "enabled": ("enabled", "disabled"),
    "default": ("default", "not default"),
    "forced": ("forced", "not forced"),
    "hearing_impaired": ("HI", "not HI"),
    "visual_impaired": ("VI", "not VI"),
    "text_descriptions": ("TD", "not TD"),
    "original": ("original", "not original"),
    "commentary": ("commentary", "not commentary"),
}
_TYPE_NOUN = {TrackType.VIDEO: "video", TrackType.AUDIO: "audio", TrackType.SUBTITLES: "subtitle"}
# flag condition -> words after "that is" (set, not set)
_FLAG_STATES = {
    "enabled": ("enabled", "disabled"),
    "hearing_impaired": ("marked hearing impaired", "not marked hearing impaired"),
    "visual_impaired": ("marked visual impaired", "not marked visual impaired"),
    "text_descriptions": ("marked text descriptions", "not marked text descriptions"),
    "original": ("marked original language", "not marked original language"),
    "commentary": ("marked commentary", "not marked commentary"),
}
_NUM_PHRASE = {
    NumOp.EQ: "of exactly",
    NumOp.NE: "other than",
    NumOp.LT: "below",
    NumOp.LE: "of at most",
    NumOp.GT: "above",
    NumOp.GE: "of at least",
}
_NUM_NOUN = {
    "channels": "a channel count",
    "bitrate": "a bitrate",
    "sample_rate": "a sample rate",
    "bit_depth": "a bit depth",
    "height": "a height",
    "fps": "a frame rate",
}
_TEXT_PHRASE = {
    TextOp.CONTAINS: "contains",
    TextOp.NOT_CONTAINS: "does not contain",
    TextOp.MATCHES: "matches",
    TextOp.NOT_MATCHES: "does not match",
}


def match_chips(m: TrackMatcher) -> list[str]:
    """What the rule looks for, apart from the track type."""
    chips: list[str] = []
    if m.languages:
        chips.append(("not " if m.languages_not else "") + ", ".join(m.languages))
    if m.positions:
        chips.append("no. " + format_positions(m.positions))
    if m.codec_contains.strip():
        chips.append(("not " if m.codec_not else "") + m.codec_contains.strip())
    if m.name_op == NameOp.EMPTY:
        chips.append("no name")
    elif m.name_op == NameOp.NOT_EMPTY:
        chips.append("has a name")
    elif m.name_regex:
        chips.append(f"name {'!~' if m.name_op == NameOp.NOT_MATCHES else '~'} {m.name_regex}")
    if m.is_default is not None:
        chips.append("default" if m.is_default else "not default")
    if m.is_forced is not None:
        chips.append("forced" if m.is_forced else "not forced")
    for key, wanted in m.flags.items():
        if key in _FLAG_CHIPS:
            chips.append(_FLAG_CHIPS[key][0 if wanted else 1])
    for key in m.numeric_keys():
        chips.append(numeric_chip(key, m.numbers[key]))
    for label, cond in (("path", m.path), ("file", m.file_name)):
        if cond and cond.active:
            chips.append(text_chip(label, cond))
    # "first match" is the usual case and goes without saying; positions name the tracks themselves
    if m.match_mode == MatchMode.ALL and not m.positions:
        chips.append("all")
    return chips


def action_chips(a: TrackActions) -> list[str]:
    """What the rule changes."""
    chips: list[str] = []
    if a.exclusive_default:
        chips.append("only default")
    for key, state in a.flags.items():
        if state == TriState.UNCHANGED or (key == "default" and a.exclusive_default):
            continue
        chips.append(_FLAG_CHIPS[key][0 if state == TriState.YES else 1])
    if a.name_mode == NameMode.SET:
        chips.append("name")
    elif a.name_mode == NameMode.CLEAR:
        chips.append("no name")
    if a.language and a.language.strip():
        chips.append(f"→ {a.language.strip()}")
    if a.extra_args.strip():
        chips.append("extra")
    return chips


def _subject(m: TrackMatcher) -> str:
    many = len(m.positions) > 1 if m.positions else m.match_mode == MatchMode.ALL
    words = ["The" if m.positions else "All" if many else "The first"]
    languages = [language_name(code) for code in m.languages if code.strip()]
    if languages and not m.languages_not:
        words.append("/".join(languages))
    words.append(_TYPE_NOUN[m.track_type] + (" tracks" if many else " track"))

    conditions: list[str] = []
    if m.positions:
        conditions.append(("at positions " if len(m.positions) > 1 else "at position ") + format_positions(m.positions))
    if languages and m.languages_not:
        conditions.append("in a language other than " + "/".join(languages))
    if m.codec_contains.strip():
        verb = "not containing" if m.codec_not else "containing"
        conditions.append(f'with a codec {verb} "{m.codec_contains.strip()}"')
    if m.name_op == NameOp.EMPTY:
        conditions.append("without a name")
    elif m.name_op == NameOp.NOT_EMPTY:
        conditions.append("with a name")
    elif m.name_regex:
        verb = "does not match" if m.name_op == NameOp.NOT_MATCHES else "matches"
        conditions.append(f'whose name {verb} "{m.name_regex}"')
    for key in m.numeric_keys():
        cond = m.numbers[key]
        unit = NUMERIC[key][1]
        conditions.append(
            f"with {_NUM_NOUN[key]} {_NUM_PHRASE[cond.op]} {format_value(cond.value)}{' ' + unit if unit else ''}"
        )
    file_parts = [
        f'{noun} {_TEXT_PHRASE[cond.op]} "{cond.value}"'
        for noun, cond in (("path", m.path), ("name", m.file_name))
        if cond and cond.active
    ]
    if file_parts:
        conditions.append("in files whose " + " and whose ".join(file_parts))
    states = []
    if m.is_default is not None:
        states.append("default" if m.is_default else "not default")
    if m.is_forced is not None:
        states.append("forced" if m.is_forced else "not forced")
    for key, wanted in m.flags.items():
        if key in _FLAG_STATES:
            states.append(_FLAG_STATES[key][0 if wanted else 1])
    if states:
        conditions.append(("that are " if many else "that is ") + " and ".join(states))
    return " ".join(words) + (" " + ", ".join(conditions) if conditions else "")


def _changes(a: TrackActions) -> list[str]:
    out: list[str] = []
    if a.exclusive_default:
        out.append("make it the only default track")
    for key, state in a.flags.items():
        if state == TriState.UNCHANGED or (key == "default" and a.exclusive_default):
            continue
        out.append(("set " if state == TriState.YES else "clear ") + FLAGS[key][2].lower())
    if a.name_mode == NameMode.SET:
        out.append(f'rename to "{a.name_template}"')
    elif a.name_mode == NameMode.CLEAR:
        out.append("remove the name")
    if a.language and a.language.strip():
        code = a.language.strip()
        name = language_name(code)
        out.append(f"set the language to {name} ({code})" if name != code else f"set the language to {code}")
    if a.extra_args.strip():
        out.append("pass extra parameters")
    return out


def rule_sentence(rule: TrackRule) -> str:
    """The whole rule in plain words, e.g. 'All German subtitle tracks ...: set forced, rename to "..."'."""
    changes = _changes(rule.actions)
    return f"{_subject(rule.matcher)}: {', '.join(changes) if changes else 'nothing is changed yet'}."
