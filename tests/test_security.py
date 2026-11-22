"""Protection against presets and files from untrusted sources."""

from pathlib import Path

from bmpe.core.command import plan_file
from bmpe.core.matcher import resolve
from bmpe.core.models import (
    AttachmentAdd,
    AttachmentOps,
    AttachmentReplace,
    ExternalSource,
    FileInfo,
    GeneralSettings,
    GlobalPreset,
    MatchMode,
    SourceMode,
    TextCondition,
    TextOp,
    TrackActions,
    TrackInfo,
    TrackMatcher,
    TrackPreset,
    TrackRule,
    TrackType,
    TriState,
)
from bmpe.core.placeholders import pattern_groups
from bmpe.core.presets import external_references

SLOW = r"^(a|aa)+$"  # catastrophic backtracking on "aaaa...!"
SLOW_TEXT = "a" * 60 + "!"


def test_a_plain_preset_has_no_external_references():
    rule = TrackRule(matcher=TrackMatcher(track_type=TrackType.AUDIO), actions=TrackActions(language="ger"))
    assert external_references(GlobalPreset(rules=[rule])) == []
    assert external_references(TrackPreset(name="x")) == []


def test_external_references_are_listed():
    preset = GlobalPreset(
        general=GeneralSettings(
            chapters=ExternalSource(mode=SourceMode.FILE, file_path="C:/x/chapters.xml"),
            tags=ExternalSource(mode=SourceMode.PER_MKV),  # next to each MKV: no fixed file
            extra_args="--add-attachment C:/secret.txt",
        ),
        attachments=AttachmentOps(
            add=[AttachmentAdd(path="C:/Users/me/notes.txt", name="cover.jpg")],
            replace=[AttachmentReplace(value="font.ttf", path="C:/x/font.ttf")],
        ),
        rules=[TrackRule(label="Rule A", matcher=TrackMatcher(track_type=TrackType.AUDIO),
                         actions=TrackActions(extra_args="--set x=1"))],
    )
    assert external_references(preset) == [
        "Chapters from C:/x/chapters.xml",
        'Add attachment C:/Users/me/notes.txt named "cover.jpg"',
        "Replace attachment font.ttf with C:/x/font.ttf",
        "Extra parameters: --add-attachment C:/secret.txt",
        "Extra parameters of rule 'Rule A': --set x=1",
    ]
    track = TrackPreset(name="t", actions=TrackActions(extra_args="--chapters C:/x.xml"))
    assert external_references(track) == ["Extra parameters of the track preset: --chapters C:/x.xml"]


def test_the_change_list_shows_where_an_attachment_comes_from(tmp_path):
    secret = tmp_path / "private-notes.txt"
    secret.write_text("x")
    preset = GlobalPreset(attachments=AttachmentOps(add=[AttachmentAdd(path=str(secret), name="cover.jpg")]))
    plan = plan_file(FileInfo(path=str(Path("/x/a.mkv"))), preset, 0)
    assert [c.new for c in plan.changes] == [f"cover.jpg ← {secret}"]


def test_a_runaway_name_regex_is_stopped_with_a_warning():
    file = FileInfo(path="x.mkv", tracks=[TrackInfo(id=0, type=TrackType.AUDIO, name=SLOW_TEXT)])
    rule = TrackRule(
        label="Slow",
        matcher=TrackMatcher(track_type=TrackType.AUDIO, match_mode=MatchMode.ALL, name_regex=SLOW),
        actions=TrackActions(flags={"forced": TriState.YES}),
    )
    res = resolve([rule], file)
    assert res.hits[rule.id] == []
    assert any("took too long" in w and "Slow" in w for w in res.warnings)


def test_a_runaway_file_condition_is_stopped():
    file = FileInfo(path=SLOW_TEXT + ".mkv", tracks=[TrackInfo(id=0, type=TrackType.AUDIO)])
    rule = TrackRule(
        matcher=TrackMatcher(track_type=TrackType.AUDIO, file_name=TextCondition(op=TextOp.MATCHES, value=SLOW)),
        actions=TrackActions(flags={"forced": TriState.YES}),
    )
    res = resolve([rule], file)
    assert not res.tracks and any("took too long on the path or file name" in w for w in res.warnings)


def test_a_runaway_file_name_pattern_is_stopped():
    groups, problem = pattern_groups(r"(a|aa)+$", SLOW_TEXT)
    assert groups == {"0": "", "1": ""} and "took too long" in problem


def test_regex_syntax_is_unchanged():
    """The regex package (VERSION0) understands the same patterns as Python's re module."""
    m = TrackMatcher(track_type=TrackType.AUDIO, name_regex=r"(?i)^sign\w*\s*(&|and)\s*songs?$")
    assert m.regex_error() == ""
    assert m.matches(TrackInfo(id=0, type=TrackType.AUDIO, name="Signs & Songs"))
    groups, _ = pattern_groups(r"\[(?P<group>[^]]+)\] (.+) - (\d+)", "[Grp] Show - 03")
    assert groups == {"0": "[Grp] Show - 03", "1": "Grp", "2": "Show", "3": "03"}
