"""End-to-end test with the real mkvmerge/mkvpropedit (skipped if they are missing)."""

import subprocess

import pytest

from bmpe.core.command import plan_batch
from bmpe.core.mkvtoolnix import find_tools
from bmpe.core.models import (
    AttachmentDelete,
    AttachmentReplace,
    AttachmentSelector,
    GeneralSettings,
    GlobalPreset,
    MatchMode,
    NameMode,
    SourceMode,
    TitleMode,
    TrackActions,
    TrackMatcher,
    TrackRule,
    TrackType,
    TriState,
)
from bmpe.core.probe import probe
from bmpe.core.runner import BatchRunner, RunStatus

_TOOLS = find_tools()
MKVMERGE = _TOOLS["mkvmerge"]
MKVPROPEDIT = _TOOLS["mkvpropedit"]

pytestmark = pytest.mark.skipif(not (MKVMERGE and MKVPROPEDIT), reason="MKVToolNix not found")


def make_mkv(folder, name, extra=()):
    srt = folder / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    out = folder / name
    subprocess.run(
        [
            str(MKVMERGE.path), "-q", "-o", str(out), "--title", "Alt", *extra,
            "--language", "0:jpn", "--default-track-flag", "0:1", str(srt),
            "--language", "0:ger", "--track-name", "0:Signs & Songs", "--default-track-flag", "0:0", str(srt),
            "--language", "0:ger", "--track-name", "0:Full", "--default-track-flag", "0:0", str(srt),
        ],
        check=True,
    )
    return out


def test_end_to_end(tmp_path):
    # non-ASCII file names and titles on purpose
    files = [make_mkv(tmp_path, f"Episode ü {i}.mkv") for i in range(1, 4)]
    infos = [probe(MKVMERGE.path, str(f), use_cache=False) for f in files]
    assert all(not i.error for i in infos)
    assert [t.language for t in infos[0].tracks] == ["jpn", "ger", "ger"]

    signs = TrackActions(name_mode=NameMode.SET, name_template="Signs [{num}]")
    signs.flags["forced"] = TriState.YES
    full = TrackActions(exclusive_default=True, language="de-DE")
    full.flags["hearing_impaired"] = TriState.YES
    preset = GlobalPreset(
        general=GeneralSettings(title_mode=TitleMode.SET, title_template="«{file_name}» #{num}", num_padding=2),
        rules=[
            TrackRule(matcher=TrackMatcher(track_type=TrackType.SUBTITLES, name_regex="signs"), actions=signs),
            TrackRule(
                matcher=TrackMatcher(track_type=TrackType.SUBTITLES, name_regex="^full$", match_mode=MatchMode.ALL),
                actions=full,
            ),
        ],
    )
    plans = plan_batch(infos, preset)
    results = BatchRunner(MKVPROPEDIT.path, plans, workers=2).run()
    assert [r.status for r in results] == [RunStatus.OK] * 3, [r.output for r in results]

    after = probe(MKVMERGE.path, str(files[1]), use_cache=False)
    assert after.title == "«Episode ü 2» #02"
    s = after.tracks
    assert s[0].flag("default") is False
    assert s[1].name == "Signs [02]" and s[1].flag("forced") is True
    assert s[2].flag("default") is True and s[2].flag("hearing_impaired") is True
    assert s[2].language_ietf == "de-DE" and s[2].language == "ger"

    # second run: nothing left to do
    again = plan_batch([probe(MKVMERGE.path, str(f), use_cache=False) for f in files], preset)
    assert not any(p.has_work for p in again)


def run_plan(mkv, preset):
    info = probe(MKVMERGE.path, str(mkv), use_cache=False)
    result = BatchRunner(MKVPROPEDIT.path, plan_batch([info], preset)).run()[0]
    return result, probe(MKVMERGE.path, str(mkv), use_cache=False)


def test_attachment_name_with_colon(tmp_path):
    old = tmp_path / "old.txt"
    old.write_text("old", encoding="utf-8")
    new = tmp_path / "new.txt"
    new.write_text("new content", encoding="utf-8")
    attach = ["--attachment-name", "a:b.txt", "--attach-file", str(old)]

    mkv = make_mkv(tmp_path, "replace.mkv", attach)
    preset = GlobalPreset()
    preset.attachments.replace.append(AttachmentReplace(value="a:b.txt", path=str(new), name="c.txt"))
    result, after = run_plan(mkv, preset)
    assert result.status == RunStatus.OK, result.output
    assert [(a.file_name, a.size) for a in after.attachments] == [("c.txt", len("new content"))]

    mkv = make_mkv(tmp_path, "delete.mkv", attach)
    preset = GlobalPreset()
    preset.attachments.delete.append(AttachmentDelete(selector=AttachmentSelector.NAME, value="a:b.txt"))
    result, after = run_plan(mkv, preset)
    assert result.status == RunStatus.OK, result.output
    assert after.attachments == []


def test_language_codes_on_file_without_ietf_element(tmp_path):
    mkv = make_mkv(tmp_path, "legacy.mkv", ["--disable-language-ietf"])
    info = probe(MKVMERGE.path, str(mkv), use_cache=False)
    assert [(t.language, t.language_ietf) for t in info.tracks] == [("jpn", ""), ("ger", ""), ("ger", "")]
    for code in ("ger", "deu", "de"):
        m = TrackMatcher(track_type=TrackType.SUBTITLES, languages=[code], match_mode=MatchMode.ALL)
        assert [t.index_in_type for t in info.tracks if m.matches(t)] == [2, 3], code

    # "de" on a "ger" track is no change; a real change is written once and then left alone
    actions = TrackActions(language="de")
    rule = TrackRule(matcher=TrackMatcher(track_type=TrackType.SUBTITLES, match_mode=MatchMode.ALL), actions=actions)
    preset = GlobalPreset(rules=[rule])
    result, after = run_plan(mkv, preset)
    assert result.status == RunStatus.OK, result.output
    assert [(t.language, t.language_ietf) for t in after.tracks] == [("ger", "de"), ("ger", ""), ("ger", "")]
    assert not plan_batch([after], preset)[0].has_work


def test_cancel_finishes_the_running_file_and_skips_the_rest(tmp_path):
    files = [make_mkv(tmp_path, f"{i}.mkv") for i in range(1, 4)]
    infos = [probe(MKVMERGE.path, str(f), use_cache=False) for f in files]
    preset = GlobalPreset(general=GeneralSettings(title_mode=TitleMode.SET, title_template="Neu {num}"))
    runner = BatchRunner(MKVPROPEDIT.path, plan_batch(infos, preset), workers=1)
    runner.on_start = lambda plan: runner.cancel()  # cancel while the first file is being processed
    results = runner.run()
    assert [r.status for r in results] == [RunStatus.OK, RunStatus.CANCELLED, RunStatus.CANCELLED]
    assert [probe(MKVMERGE.path, str(f), use_cache=False).title for f in files] == ["Neu 01", "Alt", "Alt"]


def test_removing_tags_is_only_planned_when_there_are_tags(tmp_path):
    mkv = make_mkv(tmp_path, "tags.mkv")  # mkvmerge writes statistics tags for every track
    info = probe(MKVMERGE.path, str(mkv), use_cache=False)
    assert info.global_tags == 0 and info.track_tags > 0
    preset = GlobalPreset()
    preset.general.tags.mode = SourceMode.REMOVE
    preset.general.tags.target = "global"
    assert not plan_batch([info], preset)[0].has_work
    preset.general.tags.target = "all"
    result, after = run_plan(mkv, preset)
    assert result.status == RunStatus.OK, result.output
    assert after.track_tags == 0
    assert not plan_batch([after], preset)[0].has_work
