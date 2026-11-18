from pathlib import Path

import pytest

from bmpe.core.command import attachment_selector, plan_file, render_args, split_args
from bmpe.core.matcher import resolve
from bmpe.core.models import (
    AttachmentDelete,
    AttachmentInfo,
    AttachmentSelector,
    GeneralSettings,
    GlobalPreset,
    MatchMode,
    NameMode,
    SourceMode,
    TitleMode,
    TrackActions,
    TrackMatcher,
    TrackPreset,
    TrackRule,
    TrackType,
    TriState,
)
from bmpe.core.placeholders import render
from bmpe.core.presets import PresetStore


def rule(tt, actions=None, **kw):
    return TrackRule(matcher=TrackMatcher(track_type=tt, **kw), actions=actions or TrackActions())


def acts(**flags):
    a = TrackActions()
    for k, v in flags.items():
        a.flags[k] = TriState.YES if v else TriState.NO
    return a


# ----------------------------------------------------------------------- Matcher


def test_matcher_language_and_position(anime_file):
    m = TrackMatcher(track_type=TrackType.AUDIO, languages=["ger"])
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [2]
    m = TrackMatcher(track_type=TrackType.AUDIO, languages=["de"])  # short IETF form
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [2]
    m = TrackMatcher(track_type=TrackType.SUBTITLES, positions=[3])
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [5]


def test_matcher_regex_codec_flags(anime_file):
    m = TrackMatcher(track_type=TrackType.SUBTITLES, name_regex="signs")
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [3]
    m = TrackMatcher(track_type=TrackType.SUBTITLES, codec_contains="srt")
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [5]
    m = TrackMatcher(track_type=TrackType.SUBTITLES, is_default=False, languages=["ger"])
    assert [t.id for t in anime_file.tracks if m.matches(t)] == [4]
    m = TrackMatcher(track_type=TrackType.SUBTITLES, name_regex="[invalid")
    assert not any(m.matches(t) for t in anime_file.tracks)


def test_resolve_first_vs_all(anime_file):
    r1 = rule(TrackType.SUBTITLES, acts(forced=True), languages=["ger"])
    assert list(resolve([r1], anime_file).tracks) == [3]
    r1.matcher.match_mode = MatchMode.ALL
    assert list(resolve([r1], anime_file).tracks) == [3, 4]


def test_resolve_no_match_warning(anime_file):
    res = resolve([rule(TrackType.AUDIO, acts(default=True), languages=["fre"])], anime_file)
    assert not res.tracks
    assert "matches no track" in res.warnings[0]


def test_resolve_conflict_later_wins(anime_file):
    r1 = rule(TrackType.AUDIO, acts(default=True), positions=[1])
    r2 = rule(TrackType.AUDIO, acts(default=False), languages=["jpn"])
    res = resolve([r1, r2], anime_file)
    assert res.tracks[1].actions.flags["default"] == TriState.NO
    assert any("Conflict" in w for w in res.warnings)


def test_exclusive_default(anime_file):
    a = TrackActions(exclusive_default=True)
    res = resolve([rule(TrackType.AUDIO, a, languages=["ger"])], anime_file)
    assert res.tracks[2].actions.flags["default"] == TriState.YES
    assert res.tracks[1].actions.flags["default"] == TriState.NO
    assert 0 not in res.tracks  # video untouched


def test_disabled_and_empty_rules_ignored(anime_file):
    r = rule(TrackType.AUDIO, acts(default=True))
    r.enabled = False
    assert not resolve([r, rule(TrackType.AUDIO)], anime_file).tracks


# ----------------------------------------------------------------------- placeholders / arguments


def test_render_placeholders():
    out, unknown = render("{file_name} - {num} {foo}", {"file_name": "A", "num": "007"})
    assert out == "A - 007 {foo}"
    assert unknown == ["foo"]


def test_split_args():
    # non-ASCII on purpose
    assert split_args('--set "name=Ä b" --x') == ["--set", "name=Ä b", "--x"]
    assert split_args(r"--chapters C:\x\y.xml") == ["--chapters", r"C:\x\y.xml"]
    assert split_args("--chapters ''") == ["--chapters", ""]


def test_render_args_keeps_quotes_and_spaces_of_values():
    ctx = {"file_name": "Don't Look Up", "track_name": 'Stereo "Dub" mix'}
    args, unknown = render_args("--edit info --set title={file_name}", ctx)
    assert args == ["--edit", "info", "--set", "title=Don't Look Up"]
    args, unknown = render_args('--set "name={track_name} [{file_name}]" {nope}', ctx)
    assert args == ["--set", "name=Stereo \"Dub\" mix [Don't Look Up]", "{nope}"]
    assert unknown == ["nope"]


def test_extra_args_with_quote_in_file_name(anime_file):
    anime_file.path = r"C:\Series\Don't Look Up.mkv"
    preset = GlobalPreset()
    preset.general.extra_args = "--edit info --set title={file_name}"
    assert plan_file(anime_file, preset, 0).args == ["--edit", "info", "--set", "title=Don't Look Up"]


def test_attachment_selector():
    # only --replace-attachment wants the colon escaped
    assert attachment_selector(AttachmentSelector.NAME, "a:b.ttf") == "name:a:b.ttf"
    assert attachment_selector(AttachmentSelector.NAME, "a:b.ttf", replace=True) == r"name:a\cb.ttf"
    assert attachment_selector(AttachmentSelector.UID, "123") == "=123"
    assert attachment_selector(AttachmentSelector.ID, "2") == "2"


# ----------------------------------------------------------------------- command


def test_plan_title_numbering_and_tracks(anime_file):
    preset = GlobalPreset(
        general=GeneralSettings(
            title_mode=TitleMode.SET, title_template="{file_name} – Folge {num}", num_start=5, num_padding=3
        ),
        rules=[
            rule(
                TrackType.AUDIO,
                TrackActions(exclusive_default=True, name_mode=NameMode.SET, name_template="Deutsch {channels}"),
                languages=["ger"],
            ),
            rule(TrackType.SUBTITLES, acts(forced=True), name_regex="signs"),
        ],
    )
    plan = plan_file(anime_file, preset, index=2)
    a = plan.args
    assert a[:4] == ["--edit", "info", "--set", "title=Show - 01 – Folge 007"]
    # audio jpn (track number 2): default 1 -> 0
    i = a.index("track:@2")
    assert a[i + 1 : i + 3] == ["--set", "flag-default=0"]
    # audio ger (track number 3): default + name
    i = a.index("track:@3")
    assert a[i + 1 : i + 5] == ["--set", "flag-default=1", "--set", "name=Deutsch 2.0"]
    i = a.index("track:@4")
    assert a[i + 1 : i + 3] == ["--set", "flag-forced=1"]
    assert not plan.warnings


def test_only_changes_skips_identical(anime_file):
    preset = GlobalPreset(rules=[rule(TrackType.AUDIO, acts(default=True), languages=["jpn"])])
    assert plan_file(anime_file, preset, 0).args == []
    assert plan_file(anime_file, preset, 0, only_changes=False).args == [
        "--edit",
        "track:@2",
        "--set",
        "flag-default=1",
    ]


def test_language_and_clear_name(anime_file):
    a = TrackActions(language="eng", name_mode=NameMode.CLEAR)
    preset = GlobalPreset(rules=[rule(TrackType.SUBTITLES, a, positions=[1])])
    args = plan_file(anime_file, preset, 0).args
    assert args == ["--edit", "track:@4", "--delete", "name", "--set", "language=eng"]


def test_chapters_tags_attachments(anime_file, tmp_path):
    preset = GlobalPreset()
    preset.general.chapters.mode = SourceMode.REMOVE
    preset.general.tags.mode = SourceMode.REMOVE
    preset.general.tags.target = "global"
    preset.attachments.delete.append(AttachmentDelete(selector=AttachmentSelector.MIME, value="font/ttf"))
    anime_file.chapter_entries = 3
    anime_file.track_tags = 4
    # only track tags, no attachment -> nothing to remove for "global" and nothing to delete
    assert plan_file(anime_file, preset, 0).args == ["--chapters", ""]
    assert plan_file(anime_file, preset, 0, only_changes=False).args[:2] == ["--tags", "global:"]
    preset.general.tags.target = "all"
    assert plan_file(anime_file, preset, 0).args == ["--tags", "all:", "--chapters", ""]
    preset.general.tags.target = "global"
    anime_file.global_tags = 1
    assert plan_file(anime_file, preset, 0).args == ["--tags", "global:", "--chapters", ""]
    anime_file.attachments.append(AttachmentInfo(id=1, file_name="a.ttf", mime_type="font/ttf"))
    args = plan_file(anime_file, preset, 0).args
    assert args == ["--tags", "global:", "--chapters", "", "--delete-attachment", "mime-type:font/ttf"]


def test_per_mkv_chapters(anime_file, tmp_path):
    mkv = tmp_path / "Ep 01.mkv"
    (tmp_path / "Ep 01.chapters.xml").write_text("<Chapters/>", encoding="utf-8")
    anime_file.path = str(mkv)
    preset = GlobalPreset()
    preset.general.chapters.mode = SourceMode.PER_MKV
    preset.general.chapters.suffix = ".chapters"
    assert plan_file(anime_file, preset, 0).args == ["--chapters", str(tmp_path / "Ep 01.chapters.xml")]
    preset.general.chapters.suffix = ".fehlt"
    plan = plan_file(anime_file, preset, 0)
    assert plan.args == [] and plan.warnings


def test_error_file_has_no_work(anime_file):
    anime_file.error = "kaputt"
    plan = plan_file(anime_file, GlobalPreset(general=GeneralSettings(title_mode=TitleMode.CLEAR)), 0)
    assert not plan.has_work


# ----------------------------------------------------------------------- presets


def test_preset_roundtrip(tmp_path):
    store = PresetStore(tmp_path)
    gp = GlobalPreset(
        name="Anime: DE/JP",
        rules=[rule(TrackType.AUDIO, TrackActions(exclusive_default=True, language="ger"), languages=["ger"])],
    )
    store.save_global(gp)
    assert store.load_global("Anime: DE/JP") == gp
    assert [p.name for p in store.list_global()] == ["Anime: DE/JP"]
    store.rename_global("Anime: DE/JP", "Neu")
    assert [p.name for p in store.list_global()] == ["Neu"]

    tp = TrackPreset(name="Signs forced", actions=acts(forced=True, default=True))
    store.save_track(tp)
    assert store.load_track("Signs forced") == tp

    out = tmp_path / "export.json"
    store.export_to(tp, out)
    assert isinstance(PresetStore.import_file(out), TrackPreset)
    store.export_to(gp, out)
    assert isinstance(PresetStore.import_file(out), GlobalPreset)


def test_rename_changing_only_the_case_keeps_the_preset(tmp_path):
    store = PresetStore(tmp_path)
    store.save_global(GlobalPreset(name="anime", rules=[rule(TrackType.AUDIO, acts(default=True))]))
    store.rename_global("anime", "Anime")
    assert [p.name for p in store.list_global()] == ["Anime"]
    assert len(store.load_global("Anime").rules) == 1
    assert [f.name for f in store.global_dir.glob("*.json")] == ["Anime.json"]


def test_names_with_the_same_file_name_do_not_overwrite_each_other(tmp_path):
    store = PresetStore(tmp_path)
    for name in ("DE/JP", "DE:JP", "DE_JP"):
        store.save_track(TrackPreset(name=name))
    store.save_track(TrackPreset(name="DE:JP", actions=acts(forced=True)))  # same name: overwritten
    assert sorted(p.name for p in store.list_track()) == ["DE/JP", "DE:JP", "DE_JP"]
    assert store.load_track("DE:JP").actions.flags["forced"] == TriState.YES
    assert store.load_track("DE/JP").actions.is_empty()

    store.rename_track("DE/JP", "DE_JP")  # replaces the preset that already has this name
    assert sorted(p.name for p in store.list_track()) == ["DE:JP", "DE_JP"]
    store.delete_track("DE:JP")
    assert [p.name for p in store.list_track()] == ["DE_JP"]
    assert not store.has_track("DE:JP") and store.has_track("DE_JP")
    with pytest.raises(FileNotFoundError):
        store.load_track("DE:JP")


def test_reserved_device_names_can_be_saved(tmp_path):
    store = PresetStore(tmp_path)
    for name in ("NUL", "con", "COM1.backup"):
        store.save_global(GlobalPreset(name=name))
        assert store.load_global(name).name == name
    assert len(list(store.global_dir.glob("*.json"))) == 3


def test_unreadable_files_do_not_break_loading(tmp_path):
    store = PresetStore(tmp_path)
    store.save_global(GlobalPreset(name="ok"))
    # a BOM (Notepad) is fine, everything else is skipped
    (store.global_dir / "bom.json").write_text(GlobalPreset(name="bom").model_dump_json(), encoding="utf-8-sig")
    (store.global_dir / "latin1.json").write_bytes(b'{"name": "\xff"}')
    (store.global_dir / "broken.json").write_text("{", encoding="utf-8")
    (store.global_dir / "list.json").write_text("[]", encoding="utf-8")
    assert [p.name for p in store.list_global()] == ["bom", "ok"]
    assert store.load_global("bom").name == "bom"

    store.settings_path.write_bytes(b"\xff\xfe")
    store.autosave_path.write_bytes(b"\xff\xfe")
    assert store.load_settings().workers == 1
    assert store.load_autosave() is None
    with pytest.raises(ValueError):
        PresetStore.import_file(store.global_dir / "list.json")


def test_flags_validator_fills_missing():
    a = TrackActions.model_validate({"flags": {"default": "yes", "bogus": "no"}})
    assert a.flags["default"] == TriState.YES
    assert a.flags["forced"] == TriState.UNCHANGED
    assert "bogus" not in a.flags


def test_find_tools_prefers_config_dir(tmp_path, monkeypatch):
    from bmpe.core import mkvtoolnix

    for n in ("mkvmerge", "mkvpropedit"):
        (tmp_path / (n + mkvtoolnix.EXE_SUFFIX)).write_bytes(b"")
    tools = mkvtoolnix.find_tools(str(tmp_path))
    assert tools["mkvpropedit"].source == "config"
    assert tools["mkvmerge"].path.parent == tmp_path
    assert mkvtoolnix.dir_has_tools(str(tmp_path))
    assert not mkvtoolnix.dir_has_tools(str(tmp_path / "fehlt"))


# ----------------------------------------------------------------------- language name / format


def test_language_name_lookup():
    from bmpe.core.languages import language_name, register_names

    register_names(
        "\n".join(
            [
                "English language name | ISO 639-3 code | ISO 639-2 code | ISO 639-1 code",
                "-----+-----+-----+-----",
                "Greek (modern, 1453-)   | gre | gre | el",
                "Zulu                    | zul | zul | zu",
                "'Are'are                | alu |     |   ",
            ]
        )
    )
    assert language_name("ger") == "German"
    assert language_name("de") == "German"
    assert language_name("de-DE") == "German"
    assert language_name("el") == "Greek"
    assert language_name("zu") == "Zulu"
    assert language_name("alu") == "'Are'are"
    assert language_name("xx-YY") == "xx-YY"


def test_language_codes_match_in_every_spelling(anime_file):
    def hits(*langs, tt=TrackType.SUBTITLES):
        m = TrackMatcher(track_type=tt, languages=list(langs), match_mode=MatchMode.ALL)
        return [t.id for t in anime_file.tracks if m.matches(t)]

    # tracks 3 and 4 only have the legacy code "ger" (no IETF element, like files from older muxers)
    assert hits("ger") == hits("de") == hits("deu") == hits("DE") == [3, 4]
    assert hits("de-DE") == []  # a region can only match a track that carries it
    anime_file.tracks[4].language_ietf = "de-DE"
    assert hits("de") == [3, 4]
    assert hits("de-DE") == hits("de-de") == [4]
    assert hits("de-AT") == []
    assert hits("fr", "en") == [5]


def test_language_is_only_written_when_it_differs(anime_file):
    def planned(lang, ietf=""):
        anime_file.tracks[4].language_ietf = ietf
        preset = GlobalPreset(rules=[rule(TrackType.SUBTITLES, TrackActions(language=lang), positions=[2])])
        return plan_file(anime_file, preset, 0).args

    assert planned("ger") == planned("de") == planned("deu") == []  # legacy "ger"
    assert planned("de", ietf="de") == planned("ger", ietf="de") == []
    # the region would get lost, so this is a change
    assert planned("de", ietf="de-DE") == ["--edit", "track:@5", "--set", "language=de"]
    assert planned("de-DE", ietf="de-DE") == planned("de-de", ietf="de-DE") == []
    assert planned("de-AT", ietf="de-DE") == ["--edit", "track:@5", "--set", "language=de-AT"]
    assert planned("eng") == ["--edit", "track:@5", "--set", "language=eng"]


def test_malformed_language_is_left_out_with_a_warning(anime_file):
    from bmpe.core.languages import language_problem

    a = TrackActions(language="Germ")
    a.flags["forced"] = TriState.YES
    plan = plan_file(anime_file, GlobalPreset(rules=[rule(TrackType.SUBTITLES, a, positions=[2])]), 0)
    assert plan.args == ["--edit", "track:@5", "--set", "flag-forced=1"]
    assert len(plan.warnings) == 1 and "'Germ'" in plan.warnings[0]
    for bad in ("german", "d", "de_DE", "German (ger, de)", "de-"):
        assert language_problem(bad)[1] is True, bad
    for good in ("ger", "de", "DE", "deu", "de-DE", "de-Latn-DE", "pt-br", "x-foo", "qaa", "und"):
        assert language_problem(good) is None, good


def test_short_format():
    from bmpe.core.models import TrackInfo
    from bmpe.core.placeholders import short_format

    def t(cid, codec="", tt=TrackType.SUBTITLES):
        return TrackInfo(id=0, type=tt, codec_id=cid, codec=codec)

    assert short_format(t("S_TEXT/ASS")) == "ASS"
    assert short_format(t("S_HDMV/PGS")) == "PGS"
    assert short_format(t("S_TEXT/UTF8")) == "SRT"
    assert short_format(t("A_FLAC", tt=TrackType.AUDIO)) == "FLAC"
    assert short_format(t("A_AAC/MPEG4/LC", tt=TrackType.AUDIO)) == "AAC"
    assert short_format(t("A_DTS", "DTS-HD Master Audio", TrackType.AUDIO)) == "DTS-HD MA"
    assert short_format(t("V_MPEGH/ISO/HEVC", tt=TrackType.VIDEO)) == "HEVC"
    assert short_format(t("X_UNKNOWN", "Foo/Bar")) == "Foo"


def test_name_template_with_lang_name_and_format(anime_file):
    anime_file.tracks[3].codec_id = "S_TEXT/ASS"
    anime_file.tracks[4].codec_id = "S_TEXT/ASS"
    signs = TrackActions(name_mode=NameMode.SET, name_template="{lang_name} · Signs & Songs · {format}")
    full = TrackActions(name_mode=NameMode.SET, name_template="{lang_name} · Full · BD", language="eng")
    preset = GlobalPreset(
        rules=[
            rule(TrackType.SUBTITLES, signs, name_regex="sign"),
            rule(TrackType.SUBTITLES, full, name_regex="^full$", languages=["ger"]),
        ]
    )
    args = plan_file(anime_file, preset, 0).args
    assert "name=German · Signs & Songs · ASS" in args
    # new language set by the same rule -> {lang_name} follows the new language
    assert "name=English · Full · BD" in args


# ----------------------------------------------------------------------- multiple positions


def test_parse_and_format_positions():
    from bmpe.core.models import format_positions, parse_positions

    assert parse_positions("") == ([], [])
    assert parse_positions("1, 3 5-7") == ([1, 3, 5, 6, 7], [])
    assert parse_positions("4-2;2") == ([2, 3, 4], [])
    assert parse_positions("2 - 4, 7 -9") == ([2, 3, 4, 7, 8, 9], [])
    assert parse_positions("2 -") == ([2], ["-"])
    assert parse_positions("0, x, 2") == ([2], ["0", "x"])
    assert format_positions([1, 3, 5, 6, 7]) == "1, 3, 5-7"
    assert format_positions([2, 3]) == "2, 3"
    assert format_positions([]) == ""


def test_multiple_positions_match(anime_file):
    r = rule(TrackType.SUBTITLES, acts(forced=True), positions=[1, 3], match_mode=MatchMode.ALL)
    assert list(resolve([r], anime_file).tracks) == [3, 5]
    # positions name the tracks themselves, "first match only" does not apply to them
    r.matcher.match_mode = MatchMode.FIRST
    assert list(resolve([r], anime_file).tracks) == [3, 5]
    r.matcher.languages = ["eng"]  # the other conditions still have to be met
    assert list(resolve([r], anime_file).tracks) == [5]
    r.matcher.languages = []
    assert "no. 1, 3" in r.matcher.describe()


# ----------------------------------------------------------------------- probing / running


def test_parse_identification():
    from bmpe.core.probe import parse_identification

    data = {
        "container": {"type": "Matroska", "recognized": True, "supported": True, "properties": {"title": "T"}},
        "tracks": [
            {"id": 0, "type": "video", "codec": "HEVC", "properties": {"number": 1, "uid": 11, "default_track": True}},
            {
                "id": 1, "type": "audio", "codec": "AAC",
                "properties": {
                    "number": 2, "language": "ger", "language_ietf": "de-DE", "track_name": "Stereo",
                    "audio_channels": 2, "default_track": False, "forced_track": True, "enabled_track": False,
                    "flag_commentary": True, "tag_bps": "128000", "tag_duration": "00:01:00.000",
                },
            },
            {"id": 2, "type": "buttons", "codec": "x", "properties": {}},
            {"id": 3, "type": "audio", "codec": "AAC", "properties": {"number": 4}},
        ],
        "attachments": [{"id": 1, "file_name": "a.ttf", "content_type": "font/ttf", "size": 5, "properties": {"uid": 9}}],
        "chapters": [{"num_entries": 3}, {"num_entries": 2}],
        "global_tags": [{"num_entries": 4}],
        "track_tags": [],
    }
    info = parse_identification("x.mkv", data)
    assert not info.error and info.title == "T"
    assert [(t.id, t.type, t.index_in_type, t.number) for t in info.tracks] == [
        (0, TrackType.VIDEO, 1, 1), (1, TrackType.AUDIO, 1, 2), (3, TrackType.AUDIO, 2, 4),
    ]
    audio = info.tracks[1]
    assert (audio.language, audio.language_ietf, audio.name, audio.channels) == ("ger", "de-DE", "Stereo", 2)
    assert audio.flag("forced") and audio.flag("commentary")
    assert not audio.flag("default") and not audio.flag("enabled")
    assert info.tracks[2].flag("enabled") and info.tracks[2].language == "und"  # defaults
    assert [(a.id, a.uid, a.file_name, a.mime_type, a.size) for a in info.attachments] == [(1, 9, "a.ttf", "font/ttf", 5)]
    assert (info.chapter_entries, info.global_tags, info.track_tags) == (5, 4, 2)

    assert "Not a Matroska" in parse_identification("x.mp4", {"container": {"type": "QuickTime/MP4"}}).error
    assert parse_identification("x.txt", {"container": {"recognized": False}}).error


def test_collect_files(tmp_path):
    from bmpe.core.probe import collect_files

    (tmp_path / "sub").mkdir()
    for name in ("b.mkv", "A.MKV", "note.txt", "sub/c.mka"):
        (tmp_path / name).write_bytes(b"")
    names = lambda files: [Path(f).name for f in files]  # noqa: E731
    assert names(collect_files([str(tmp_path)])) == ["A.MKV", "b.mkv", "c.mka"]
    assert names(collect_files([str(tmp_path)], recursive=False)) == ["A.MKV", "b.mkv"]
    assert names(collect_files([str(tmp_path / "b.mkv"), str(tmp_path / "note.txt"), str(tmp_path / "nope")])) == ["b.mkv"]


def test_cancelled_runner_starts_nothing(anime_file, tmp_path):
    from bmpe.core.command import FilePlan
    from bmpe.core.runner import BatchRunner, RunStatus

    started = []
    plans = [FilePlan(file=anime_file, args=["--edit", "info", "--delete", "title"]) for _ in range(3)]
    runner = BatchRunner(tmp_path / "does-not-exist.exe", plans, on_start=started.append)
    runner.cancel()
    assert [r.status for r in runner.run()] == [RunStatus.CANCELLED] * 3
    assert not started


def test_settings_folder(tmp_path, monkeypatch):
    from bmpe.core import presets

    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert presets.default_base_dir() == tmp_path / "pyBatchMKVPropEdit"
    monkeypatch.delenv("APPDATA")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert presets.default_base_dir() == tmp_path / "xdg" / "pyBatchMKVPropEdit"
