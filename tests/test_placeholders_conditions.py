from pathlib import Path

import pytest

from bmpe.core.command import plan_file
from bmpe.core.matcher import matching_tracks, resolve
from bmpe.core.models import (
    FileInfo,
    GeneralSettings,
    MatchMode,
    GlobalPreset,
    NameMode,
    NameOp,
    NumCondition,
    NumOp,
    TextCondition,
    TextOp,
    TrackActions,
    TrackInfo,
    TrackMatcher,
    TrackRule,
    TrackType,
    TriState,
)
from bmpe.core.placeholders import file_context, pattern_groups, render, track_context
from bmpe.core.probe import parse_identification
from bmpe.core.summary import match_chips, rule_sentence

PATH = str(Path("/Anime/Show/Season 1/Show - S01E03 [BD].mkv"))


def _file() -> FileInfo:
    return FileInfo(
        path=PATH,
        title="Old",
        duration=1_420_000_000_000,  # 23:40
        tracks=[
            TrackInfo(id=0, type=TrackType.VIDEO, codec_id="V_MPEGH/ISO/HEVC", codec="HEVC/H.265/MPEG-H",
                      pixel_dimensions="1920x1080", frame_duration=41_708_333, bitrate=6_000_000),
            TrackInfo(id=1, type=TrackType.AUDIO, index_in_type=1, codec_id="A_FLAC", codec="FLAC", language="jpn",
                      channels=2, sample_rate=48_000, bit_depth=24, bitrate=1_234_567),
            TrackInfo(id=2, type=TrackType.AUDIO, index_in_type=2, codec_id="A_EAC3", codec="E-AC-3", language="ger",
                      channels=6, sample_rate=48_000, name="Dub"),
            TrackInfo(id=3, type=TrackType.AUDIO, index_in_type=3, codec_id="A_AAC", codec="AAC", language="ger",
                      channels=2, sample_rate=44_100, name="Commentary"),
            TrackInfo(id=4, type=TrackType.SUBTITLES, index_in_type=1, codec_id="S_TEXT/ASS", language="ger"),
            TrackInfo(id=5, type=TrackType.SUBTITLES, index_in_type=2, codec_id="S_HDMV/PGS", language="eng"),
        ],
    )


def _hits(matcher: TrackMatcher, file: FileInfo | None = None) -> list[int]:
    matcher.match_mode = matcher.match_mode if matcher.positions else matcher.match_mode.ALL
    return [t.id for t in matching_tracks(TrackRule(matcher=matcher), file or _file())]


# ----------------------------------------------------------------------- probing


def test_technical_values_are_read():
    data = {
        "container": {"type": "Matroska", "properties": {"duration": 1420000000000}},
        "tracks": [
            {"id": 0, "type": "video", "codec": "HEVC", "properties": {
                "pixel_dimensions": "1920x1080", "display_dimensions": "1920x1080", "default_duration": 41708333,
                "tag_bps": "6000000"}},
            {"id": 1, "type": "audio", "codec": "FLAC", "properties": {
                "audio_channels": 2, "audio_sampling_frequency": 48000, "audio_bits_per_sample": 24}},
        ],
    }
    info = parse_identification("x.mkv", data)
    video, audio = info.tracks
    assert info.duration == 1420000000000
    assert (video.height, video.fps, video.bitrate_kbps) == (1080, 23.976, 6000)
    assert (audio.sample_rate_khz, audio.bit_depth, audio.bitrate) == (48, 24, None)


# ----------------------------------------------------------------------- placeholders


def test_file_placeholders():
    ctx = file_context(_file(), 0, GeneralSettings())
    assert ctx["ext"] == "mkv"
    assert ctx["dir_name"] == "Season 1" and ctx["parent_dir"] == "Show"
    assert ctx["duration"] == "23:40"
    assert ctx["audio_langs"] == "JPN/GER" and ctx["sub_langs"] == "GER/ENG"
    assert (ctx["video_format"], ctx["resolution"], ctx["height"], ctx["fps"]) == ("HEVC", "1920x1080", "1080", "23.976")


def test_track_placeholders():
    f = _file()
    flac = track_context(f.tracks[1])
    assert (flac["channels"], flac["channels_name"], flac["bitrate"], flac["sample_rate"], flac["bit_depth"]) == (
        "2.0", "Stereo", "1235", "48", "24",
    )
    eac3 = track_context(f.tracks[2])
    assert (eac3["channels"], eac3["channels_name"], eac3["bitrate"]) == ("5.1", "Surround", "")
    assert track_context(f.tracks[3])["sample_rate"] == "44.1"


def test_long_duration():
    f = _file()
    f.duration = 6_728_000_000_000
    assert file_context(f, 0, GeneralSettings())["duration"] == "1:52:08"


@pytest.mark.parametrize(
    "template, expected",
    [
        ("{x|upper}", "SIGNS & SONGS"),
        ("{x|lower}", "signs & songs"),
        ("{y|title}", "Full Subs"),
        ("{n|pad:3}", "007"),
        ("{x|pad:3}", "Signs & Songs"),  # only numbers are padded
        ("{x|replace: & :+}", "Signs+Songs"),
        ("{x|replace:Signs:}", " & Songs"),
        ("{x|prefix:[|suffix:]}", "[Signs & Songs]"),
        ("{empty|prefix:[|suffix:]}", ""),
        ("{empty|or:unknown}", "unknown"),
        ("{x|or:unknown}", "Signs & Songs"),
        ("{empty|or:none|upper}", "NONE"),
        ("{bitrate|suffix: kbps}", "640 kbps"),
    ],
)
def test_filters(template, expected):
    ctx = {"x": "Signs & Songs", "y": "full subs", "n": "7", "empty": "", "bitrate": "640"}
    assert render(template, ctx) == (expected, [])


@pytest.mark.parametrize("template", ["{x|uppr}", "{x|pad:a}", "{x|replace:a}", "{missing|upper}"])
def test_unknown_filters_are_reported(template):
    text, unknown = render(template, {"x": "a"})
    assert text == template and unknown == [template[1:-1]]


def test_file_name_pattern_groups():
    assert pattern_groups("", "x") == (None, "")
    groups, problem = pattern_groups(r"(s\d+)(e\d+)", "Show - S01E03 [BD]")
    assert problem == "" and groups == {"0": "S01E03", "1": "S01", "2": "E03"}
    groups, problem = pattern_groups(r"(S\d+)E(\d+)", "Movie")
    assert groups == {"0": "", "1": "", "2": ""} and "does not match" in problem
    groups, problem = pattern_groups("(", "Movie")
    assert groups == {} and "not a valid" in problem


def test_pattern_groups_in_title_and_warnings():
    preset = GlobalPreset(general=GeneralSettings(name_pattern=r".*(S\d+E\d+).*"))
    preset.general.title_mode = preset.general.title_mode.SET
    preset.general.title_template = "Show {1}"
    plan = plan_file(_file(), preset, 0)
    assert plan.args[-1] == "title=Show S01E03"
    assert not plan.warnings

    other = _file()
    other.path = str(Path("/Anime/Movie.mkv"))
    plan = plan_file(other, preset, 0)
    assert plan.args[-1] == "title=Show "
    assert any("does not match" in w for w in plan.warnings)


def test_unknown_filter_in_track_name_warns():
    rule = TrackRule(
        matcher=TrackMatcher(track_type=TrackType.AUDIO, positions=[2]),
        actions=TrackActions(name_mode=NameMode.SET, name_template="{lang_name|loud} {channels} {channels_name}"),
    )
    plan = plan_file(_file(), GlobalPreset(rules=[rule]), 0)
    assert any("{lang_name|loud}" in w for w in plan.warnings)


# ----------------------------------------------------------------------- conditions


def test_negated_language_and_codec():
    assert _hits(TrackMatcher(track_type=TrackType.AUDIO, languages=["jpn"], languages_not=True)) == [2, 3]
    assert _hits(TrackMatcher(track_type=TrackType.AUDIO, codec_contains="aac", codec_not=True)) == [1, 2]


def test_name_conditions():
    audio = TrackType.AUDIO
    assert _hits(TrackMatcher(track_type=audio, name_op=NameOp.EMPTY)) == [1]
    assert _hits(TrackMatcher(track_type=audio, name_op=NameOp.NOT_EMPTY)) == [2, 3]
    assert _hits(TrackMatcher(track_type=audio, name_op=NameOp.NOT_MATCHES, name_regex="comment")) == [1, 2]
    # an empty regex is no condition
    assert _hits(TrackMatcher(track_type=audio, name_op=NameOp.NOT_MATCHES)) == [1, 2, 3]


@pytest.mark.parametrize(
    "key, op, value, expected",
    [
        ("channels", NumOp.GE, 6, [2]),
        ("channels", NumOp.EQ, 2, [1, 3]),
        ("channels", NumOp.NE, 2, [2]),
        ("sample_rate", NumOp.LT, 48, [3]),
        ("sample_rate", NumOp.EQ, 44.1, [3]),
        ("bit_depth", NumOp.GE, 24, [1]),
        ("bitrate", NumOp.GT, 1000, [1]),  # the other tracks have no bitrate
        ("bitrate", NumOp.LE, 1235, [1]),
    ],
)
def test_numeric_conditions(key, op, value, expected):
    m = TrackMatcher(track_type=TrackType.AUDIO, numbers={key: NumCondition(op=op, value=value)})
    assert _hits(m) == expected


def test_video_numbers_and_ignored_numbers():
    video = TrackType.VIDEO
    assert _hits(TrackMatcher(track_type=video, numbers={"fps": NumCondition(op=NumOp.EQ, value=23.976)})) == [0]
    assert _hits(TrackMatcher(track_type=video, numbers={"height": NumCondition(op=NumOp.LT, value=1080)})) == []
    # a frame rate condition does not apply to audio tracks and is ignored there
    m = TrackMatcher(track_type=TrackType.AUDIO, numbers={"fps": NumCondition(value=100)})
    assert m.numeric_keys() == [] and _hits(m) == [1, 2, 3]


def test_unknown_value_is_explained():
    rule = TrackRule(
        matcher=TrackMatcher(track_type=TrackType.AUDIO, positions=[2], numbers={"bitrate": NumCondition(value=100)}),
        actions=TrackActions(flags={"default": TriState.YES}),
    )
    warning = resolve([rule], _file()).warnings[0]
    assert "matches no track" in warning and "Bitrate is unknown for 2 track(s)" in warning


@pytest.mark.parametrize(
    "field, op, value, expected",
    [
        ("path", TextOp.CONTAINS, "anime", True),
        ("path", TextOp.NOT_CONTAINS, "anime", False),
        ("path", TextOp.MATCHES, r"season \d", True),
        ("path", TextOp.NOT_MATCHES, r"season \d", False),
        ("file_name", TextOp.CONTAINS, "show", True),  # the file name, not the folders
        ("file_name", TextOp.CONTAINS, "season", False),
        ("file_name", TextOp.MATCHES, r"\.mkv$", True),  # with extension
        ("file_name", TextOp.NOT_MATCHES, r"s\d+e\d+", False),
    ],
)
def test_file_conditions(field, op, value, expected):
    m = TrackMatcher(track_type=TrackType.SUBTITLES, **{field: TextCondition(op=op, value=value)})
    assert m.file_matches(PATH) is expected
    assert _hits(m) == ([4, 5] if expected else [])


def test_invalid_regex_in_file_condition_skips_the_rule():
    m = TrackMatcher(track_type=TrackType.AUDIO, file_name=TextCondition(op=TextOp.MATCHES, value="("))
    assert m.regex_error().startswith("file name:")
    rule = TrackRule(matcher=m, actions=TrackActions(flags={"default": TriState.YES}))
    assert "is skipped" in resolve([rule], _file()).warnings[0]


def test_new_conditions_are_described():
    m = TrackMatcher(
        track_type=TrackType.AUDIO,
        languages=["jpn"],
        languages_not=True,
        name_op=NameOp.EMPTY,
        numbers={"channels": NumCondition(op=NumOp.GE, value=6)},
        path=TextCondition(op=TextOp.CONTAINS, value="Anime"),
        file_name=TextCondition(op=TextOp.NOT_MATCHES, value="OVA"),
    )
    sentence = rule_sentence(TrackRule(matcher=m))
    assert sentence.startswith("The first audio track in a language other than Japanese, without a name, ")
    assert "with a channel count of at least 6" in sentence
    assert 'in files whose path contains "Anime" and whose name does not match "OVA"' in sentence
    assert match_chips(m) == ["not jpn", "no name", "channels ≥ 6", "path ~ Anime", "file !~ /OVA/"]


def test_new_fields_survive_saving():
    m = TrackMatcher(
        track_type=TrackType.VIDEO,
        codec_contains="HEVC",
        codec_not=True,
        name_op=NameOp.NOT_EMPTY,
        numbers={"height": NumCondition(op=NumOp.GE, value=720)},
        path=TextCondition(op=TextOp.MATCHES, value="x"),
    )
    preset = GlobalPreset(general=GeneralSettings(name_pattern="(.+)"), rules=[TrackRule(matcher=m)])
    loaded = GlobalPreset.model_validate_json(preset.model_dump_json())
    assert loaded == preset


# ----------------------------------------------------------------------- flag conditions and {prev_track_name}


def _dub_file() -> FileInfo:
    return FileInfo(
        path="x.mkv",
        tracks=[
            TrackInfo(id=0, type=TrackType.AUDIO, index_in_type=1, language="und", channels=2, name="Main"),
            TrackInfo(id=1, type=TrackType.AUDIO, index_in_type=2, language="und", channels=2, name="Director",
                      flags={"commentary": True}),
            TrackInfo(id=2, type=TrackType.AUDIO, index_in_type=3, language="und", channels=6,
                      flags={"enabled": False, "hearing_impaired": True}),
        ],
    )


def _all_audio(**kw) -> TrackMatcher:
    return TrackMatcher(track_type=TrackType.AUDIO, match_mode=MatchMode.ALL, **kw)


def _names(rules: list[TrackRule], file: FileInfo | None = None):
    plan = plan_file(file or _dub_file(), GlobalPreset(rules=rules), 0)
    return {c.scope.split(" · ")[0]: c.new for c in plan.changes if c.field == "Name"}, plan.warnings


def test_flag_conditions():
    assert _hits(_all_audio(flags={"commentary": True}), _dub_file()) == [1]
    assert _hits(_all_audio(flags={"commentary": False}), _dub_file()) == [0, 2]
    assert _hits(_all_audio(flags={"enabled": False}), _dub_file()) == [2]  # a missing flag counts as enabled
    assert _hits(_all_audio(flags={"hearing_impaired": True, "commentary": False}), _dub_file()) == [2]


def test_flag_conditions_are_described():
    m = _all_audio(is_default=True, flags={"commentary": True, "enabled": False})
    assert match_chips(m) == ["default", "commentary", "disabled", "all"]
    assert "that are default and marked commentary and disabled" in rule_sentence(TrackRule(matcher=m))


def test_previous_name_builds_on_the_rules_above():
    lang = TrackRule(matcher=_all_audio(), actions=TrackActions(language="ger"))
    name = TrackRule(
        matcher=_all_audio(),
        actions=TrackActions(name_mode=NameMode.SET, name_template="{lang_name} {channels} {channels_name}"),
    )
    commentary = TrackRule(
        matcher=_all_audio(flags={"commentary": True}),
        actions=TrackActions(name_mode=NameMode.SET, name_template="{prev_track_name} - Commentary"),
    )
    names, warnings = _names([lang, name, commentary])
    assert names == {"#1 Audio": "German 2.0 Stereo", "#2 Audio": "German 2.0 Stereo - Commentary",
                     "#3 Audio": "German 5.1 Surround"}
    assert not warnings  # building on the previous name is no conflict

    # the previous name can go anywhere in the template, and filters work on it
    commentary.actions.name_template = "Commentary ({prev_track_name|upper})"
    assert _names([lang, name, commentary])[0]["#2 Audio"] == "Commentary (GERMAN 2.0 STEREO)"


def test_previous_name_without_rules_above_and_after_removal():
    prefix = TrackRule(
        matcher=_all_audio(flags={"commentary": True}),
        actions=TrackActions(name_mode=NameMode.SET, name_template="[{prev_track_name}] / {track_name}"),
    )
    assert _names([prefix])[0] == {"#2 Audio": "[Director] / Director"}  # nothing above: the current name
    remove = TrackRule(matcher=_all_audio(), actions=TrackActions(name_mode=NameMode.CLEAR))
    assert _names([remove, prefix])[0]["#2 Audio"] == "[] / Director"
    # a removal after it wins
    names, _ = _names([prefix, remove])
    assert names["#2 Audio"] == "(removed)"


def test_plain_override_still_warns():
    first = TrackRule(matcher=_all_audio(), actions=TrackActions(name_mode=NameMode.SET, name_template="A"))
    second = TrackRule(matcher=_all_audio(), actions=TrackActions(name_mode=NameMode.SET, name_template="B"))
    names, warnings = _names([first, second])
    assert names["#1 Audio"] == "B" and any("name is overridden" in w for w in warnings)


def test_previous_name_in_extra_parameters_is_the_final_name():
    name = TrackRule(matcher=_all_audio(), actions=TrackActions(name_mode=NameMode.SET, name_template="X"))
    extra = TrackRule(matcher=_all_audio(), actions=TrackActions(extra_args='--set "x={prev_track_name}"'))
    plan = plan_file(_dub_file(), GlobalPreset(rules=[extra, name]), 0)
    assert "x=X" in plan.args


# ----------------------------------------------------------------------- rules see what the rules above set


def _flagged(**flags) -> TrackActions:
    return TrackActions(flags={k: TriState.YES if v else TriState.NO for k, v in flags.items()})


def test_a_flag_set_above_counts_for_the_conditions_below():
    mark = TrackRule(matcher=_all_audio(name_regex="^Main$"), actions=_flagged(commentary=True))
    rename = TrackRule(
        matcher=_all_audio(flags={"commentary": True}),
        actions=TrackActions(name_mode=NameMode.SET, name_template="{prev_track_name} - Commentary"),
    )
    names, warnings = _names([mark, rename])
    assert names == {"#1 Audio": "Main - Commentary", "#2 Audio": "Director - Commentary"}
    assert not warnings
    # the other way round, the rename rule only sees the flag from the file
    assert _names([rename, mark])[0] == {"#2 Audio": "Director - Commentary"}


def test_language_and_name_set_above_count_for_the_conditions_below():
    lang = TrackRule(matcher=_all_audio(), actions=TrackActions(language="ger"))
    german = TrackRule(matcher=_all_audio(languages=["de"]), actions=_flagged(forced=True))
    res = resolve([lang, german], _dub_file())
    assert [t.id for t in res.hits[german.id]] == [0, 1, 2]

    name = TrackRule(matcher=_all_audio(positions=[3]), actions=TrackActions(name_mode=NameMode.SET, name_template="Signs"))
    by_name = TrackRule(matcher=_all_audio(name_regex="^signs$"), actions=_flagged(forced=True))
    unnamed = TrackRule(matcher=_all_audio(name_op=NameOp.EMPTY), actions=_flagged(default=True))
    res = resolve([name, by_name, unnamed], _dub_file())
    assert [t.id for t in res.hits[by_name.id]] == [2]
    assert res.hits[unnamed.id] == []  # track 3 had no name, but the rule above gave it one


def test_placeholders_use_the_language_so_far():
    name = TrackRule(matcher=_all_audio(positions=[1]), actions=TrackActions(name_mode=NameMode.SET, name_template="{lang_name}"))
    lang = TrackRule(matcher=_all_audio(positions=[1]), actions=TrackActions(language="ger"))
    assert _names([lang, name])[0]["#1 Audio"] == "German"
    assert _names([name, lang])[0]["#1 Audio"] == "Undetermined"  # the language is set below the name


def test_exclusive_default_counts_for_the_rules_below():
    exclusive = TrackRule(matcher=_all_audio(positions=[2]), actions=TrackActions(exclusive_default=True))
    default = TrackRule(
        matcher=_all_audio(is_default=True),
        actions=TrackActions(name_mode=NameMode.SET, name_template="{prev_track_name} (default)"),
    )
    assert _names([exclusive, default])[0] == {"#2 Audio": "Director (default)"}


def test_later_exclusive_default_wins_with_a_warning():
    first = TrackRule(matcher=_all_audio(positions=[1]), actions=TrackActions(exclusive_default=True))
    second = TrackRule(matcher=_all_audio(positions=[2]), actions=TrackActions(exclusive_default=True))
    res = resolve([first, second], _dub_file())
    assert {k: e.actions.flags["default"] for k, e in res.tracks.items()} == {
        0: TriState.NO, 1: TriState.YES, 2: TriState.NO,
    }
    assert any("flag 'default' is overridden" in w for w in res.warnings)


def test_hits_are_listed_for_every_rule():
    off = TrackRule(matcher=_all_audio(), actions=_flagged(forced=True), enabled=False)
    empty = TrackRule(matcher=_all_audio(positions=[2]))
    res = resolve([off, empty], _dub_file())
    assert [t.id for t in res.hits[off.id]] == [0, 1, 2] and [t.id for t in res.hits[empty.id]] == [1]
    assert not res.tracks  # neither changes anything
