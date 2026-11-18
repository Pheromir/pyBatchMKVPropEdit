from pathlib import Path

import pytest

from bmpe.core.models import FileInfo, TrackInfo, TrackType


def _t(id, type, idx, lang="und", name="", codec="", default=False, forced=False, number=None, ietf=""):
    return TrackInfo(
        id=id,
        uid=1000 + id,
        number=number if number is not None else id + 1,
        type=type,
        index_in_type=idx,
        codec=codec,
        language=lang,
        language_ietf=ietf,
        name=name,
        flags={"default": default, "forced": forced},
        channels=2 if type == TrackType.AUDIO else None,
    )


@pytest.fixture
def anime_file() -> FileInfo:
    return FileInfo(
        path=str(Path("/Series/Show/Show - 01.mkv")),  # native separators, so it also works on Linux
        title="Old title",
        tracks=[
            _t(0, TrackType.VIDEO, 1, codec="AVC/H.264/MPEG-4p10", default=True),
            _t(1, TrackType.AUDIO, 1, lang="jpn", codec="AAC", default=True),
            _t(2, TrackType.AUDIO, 2, lang="ger", codec="AC-3", ietf="de"),
            _t(3, TrackType.SUBTITLES, 1, lang="ger", name="Signs & Songs", codec="SubStationAlpha", default=True),
            _t(4, TrackType.SUBTITLES, 2, lang="ger", name="Full", codec="SubStationAlpha"),
            _t(5, TrackType.SUBTITLES, 3, lang="eng", name="Full", codec="SubRip/SRT"),
        ],
    )
