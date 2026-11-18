from bmpe.core.command import plan_file
from bmpe.core.matcher import resolve
from bmpe.core.models import GlobalPreset, TrackActions, TrackMatcher, TrackRule, TrackType, TriState


def forced_rule(**matcher):
    actions = TrackActions()
    actions.flags["forced"] = TriState.YES
    return TrackRule(matcher=TrackMatcher(track_type=TrackType.SUBTITLES, **matcher), actions=actions)


def test_regex_error():
    assert TrackMatcher(track_type=TrackType.AUDIO).regex_error() == ""
    assert TrackMatcher(track_type=TrackType.AUDIO, name_regex="sign|song").regex_error() == ""
    assert TrackMatcher(track_type=TrackType.AUDIO, name_regex="(sign").regex_error()
    assert TrackMatcher(track_type=TrackType.AUDIO, name_regex="[a-").regex_error()


def test_rule_with_invalid_regex_is_skipped_with_a_warning(anime_file):
    broken = forced_rule(name_regex="(sign")
    broken.label = "Signs"
    res = resolve([broken, forced_rule(name_regex="^full$")], anime_file)
    assert list(res.tracks) == [4]  # only the valid rule was applied
    assert len(res.warnings) == 1
    assert "Signs" in res.warnings[0] and "not a valid regular expression" in res.warnings[0]

    plan = plan_file(anime_file, GlobalPreset(rules=[broken]), 0)
    assert plan.args == [] and len(plan.warnings) == 1
