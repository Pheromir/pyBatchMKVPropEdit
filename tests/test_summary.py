from bmpe.core.models import MatchMode, NameMode, TrackActions, TrackMatcher, TrackRule, TrackType, TriState
from bmpe.core.summary import action_chips, match_chips, rule_sentence


def actions(**flags):
    a = TrackActions()
    for key, value in flags.items():
        a.flags[key] = TriState.YES if value else TriState.NO
    return a


def test_match_chips():
    assert match_chips(TrackMatcher(track_type=TrackType.AUDIO)) == []  # "first match" is not spelled out
    m = TrackMatcher(
        track_type=TrackType.SUBTITLES,
        languages=["ger", "jpn"],
        positions=[1, 3, 4, 5],
        codec_contains=" PGS ",
        name_regex="sign|song",
        is_default=True,
        is_forced=False,
        match_mode=MatchMode.ALL,
    )
    # no "all" chip: the positions already say which tracks are meant
    assert match_chips(m) == ["ger, jpn", "no. 1, 3-5", "PGS", "name ~ sign|song", "default", "not forced"]
    m.positions = []
    assert match_chips(m)[-1] == "all"


def test_action_chips():
    assert action_chips(TrackActions()) == []
    a = actions(forced=True, default=False, hearing_impaired=True, enabled=False)
    a.name_mode = NameMode.SET
    a.language = " eng "
    a.extra_args = "--set x=y"
    assert action_chips(a) == ["disabled", "not default", "forced", "HI", "name", "→ eng", "extra"]

    # "exclusive default" decides the default flag, so the flag itself is not listed
    a = actions(default=False)
    a.exclusive_default = True
    a.name_mode = NameMode.CLEAR
    assert action_chips(a) == ["only default", "no name"]


def test_rule_sentence():
    rule = TrackRule(matcher=TrackMatcher(track_type=TrackType.VIDEO))
    assert rule_sentence(rule) == "The first video track: nothing is changed yet."

    a = actions(forced=True, default=False)
    a.name_mode, a.name_template = NameMode.SET, "{lang_name} · Signs"
    rule = TrackRule(
        matcher=TrackMatcher(
            track_type=TrackType.SUBTITLES, languages=["ger"], name_regex="sign", match_mode=MatchMode.ALL
        ),
        actions=a,
    )
    assert rule_sentence(rule) == (
        'All German subtitle tracks whose name matches "sign": '
        'clear default, set forced, rename to "{lang_name} · Signs".'
    )

    a = TrackActions(exclusive_default=True, language="jpn")
    rule = TrackRule(
        matcher=TrackMatcher(
            track_type=TrackType.AUDIO, languages=["de", "en"], positions=[2], codec_contains="AAC", is_default=False
        ),
        actions=a,
    )
    assert rule_sentence(rule) == (
        'The German/English audio track at position 2, with a codec containing "AAC", that is not default: '
        "make it the only default track, set the language to Japanese (jpn)."
    )

    a = TrackActions(name_mode=NameMode.CLEAR, language="xx-YY", extra_args="--set a=b")
    rule = TrackRule(
        matcher=TrackMatcher(
            track_type=TrackType.SUBTITLES, positions=[1, 2], is_default=True, is_forced=True, match_mode=MatchMode.ALL
        ),
        actions=a,
    )
    assert rule_sentence(rule) == (
        "The subtitle tracks at positions 1, 2, that are default and forced: "
        "remove the name, set the language to xx-YY, pass extra parameters."
    )
