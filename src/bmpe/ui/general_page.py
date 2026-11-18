"""General page: title, numbering, chapters, tags, extra parameters."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, LineEdit

from ..core.models import ExternalSource, SourceMode, StatsTagsMode, TitleMode
from .state import AppState
from .track_editor import placeholder_button
from .widgets.common import Card, EnumCombo, IntSpin, PathEdit, ScrollPage

SOURCE_ITEMS = [
    (SourceMode.UNCHANGED, "unchanged"),
    (SourceMode.REMOVE, "remove"),
    (SourceMode.FILE, "from one file (for all MKVs)"),
    (SourceMode.PER_MKV, "per MKV: file with the same name next to it"),
]


class SourceEditor:
    """Chapter or tag source (adds rows to a card)."""

    def __init__(self, card: Card, kind: str, on_change, with_target: bool = False):
        self.on_change = on_change
        self._loading = False
        self.mode = EnumCombo(SOURCE_ITEMS, card)
        card.addRow("Action", self.mode, stretch=False)
        self.target = None
        if with_target:
            self.target = EnumCombo([("all", "all tags (all)"), ("global", "global tags only (global)")], card)
            card.addRow("Scope", self.target, stretch=False)
        self.path = PathEdit("file", "XML/text (*.xml *.txt);;All files (*)", card)
        self.row_path = card.addRow(f"{kind} file", self.path)
        per = QWidget(card)
        pl = QHBoxLayout(per)
        pl.setContentsMargins(0, 0, 0, 0)
        self.suffix = LineEdit(per)
        self.suffix.setPlaceholderText("suffix, e.g. .chapters (optional)")
        self.ext = EnumCombo([(".xml", ".xml"), (".txt", ".txt")], per)
        pl.addWidget(BodyLabel("<MKV name> +", per))
        pl.addWidget(self.suffix, 1)
        pl.addWidget(self.ext)
        self.row_per = card.addRow("File name", per)
        self.mode.currentIndexChanged.connect(self._changed)
        if self.target:
            self.target.currentIndexChanged.connect(self._changed)
        self.path.changed.connect(self._changed)
        self.suffix.textChanged.connect(self._changed)
        self.ext.currentIndexChanged.connect(self._changed)

    def load(self, src: ExternalSource):
        self._loading = True
        self.mode.setValue(src.mode)
        if self.target:
            self.target.setValue(src.target)
        self.path.setText(src.file_path)
        self.suffix.setText(src.suffix)
        self.ext.setValue(src.extension)
        self._loading = False
        self._visibility()

    def save(self, src: ExternalSource):
        src.mode = self.mode.value()
        if self.target:
            src.target = self.target.value()
        src.file_path = self.path.text()
        src.suffix = self.suffix.text()
        src.extension = self.ext.value()

    def _visibility(self):
        m = self.mode.value()
        self.row_path.setVisible(m == SourceMode.FILE)
        self.row_per.setVisible(m == SourceMode.PER_MKV)
        if self.target:
            self.target.setEnabled(m != SourceMode.UNCHANGED)

    def _changed(self, *_):
        self._visibility()
        if not self._loading:
            self.on_change()


class GeneralPage(ScrollPage):
    def __init__(self, state: AppState, parent=None):
        super().__init__("General", "generalPage", parent)
        self.state = state
        self._loading = False
        v = self.view

        # ---------------- title
        card = Card("Title (segment title)", "Placeholders: {file_name}, {dir_name}, {num}, {title}", v)
        self.title_mode = EnumCombo(
            [(TitleMode.UNCHANGED, "unchanged"), (TitleMode.SET, "set"), (TitleMode.CLEAR, "remove")], card
        )
        card.addRow("Action", self.title_mode, stretch=False)
        trow = QWidget(card)
        tl = QHBoxLayout(trow)
        tl.setContentsMargins(0, 0, 0, 0)
        self.title = LineEdit(trow)
        self.title.setPlaceholderText("e.g. {dir_name} - Episode {num}")
        tl.addWidget(self.title, 1)
        tl.addWidget(placeholder_button(self.title, False, trow))
        self.row_title = card.addRow("Template", trow)
        self.body.addWidget(card)

        # ---------------- numbering
        card = Card(
            "Numbering {num}",
            "Applies to titles, track names and extra parameters. Counts in the order of the file list.",
            v,
        )
        self.num_start = IntSpin(card)
        self.num_start.setRange(0, 999999)
        card.addRow("Start value", self.num_start, stretch=False)
        self.num_pad = IntSpin(card)
        self.num_pad.setRange(0, 10)
        card.addRow("Digits (padding)", self.num_pad, stretch=False)
        self.num_example = BodyLabel("", card)
        card.addRow("Example", self.num_example)
        self.body.addWidget(card)

        # ---------------- chapters / tags
        card = Card("Chapters", "", v)
        self.chapters = SourceEditor(card, "Chapter", self._sync)
        self.body.addWidget(card)
        card = Card("Tags", "", v)
        self.tags = SourceEditor(card, "Tag", self._sync, with_target=True)
        self.stats = EnumCombo(
            [
                (StatsTagsMode.UNCHANGED, "unchanged"),
                (StatsTagsMode.ADD, "calculate and add/update"),
                (StatsTagsMode.DELETE, "remove"),
            ],
            card,
        )
        card.addRow("Track statistics tags", self.stats, stretch=False)
        self.body.addWidget(card)

        # ---------------- Extra
        card = Card(
            "Extra parameters",
            "Appended to the end of every mkvpropedit command line (placeholders allowed).",
            v,
        )
        erow = QWidget(card)
        el = QHBoxLayout(erow)
        el.setContentsMargins(0, 0, 0, 0)
        self.extra = LineEdit(erow)
        self.extra.setPlaceholderText('e.g. --edit info --set "muxing-application=..."')
        el.addWidget(self.extra, 1)
        el.addWidget(placeholder_button(self.extra, False, erow))
        card.addRow("Parameters", erow)
        self.body.addWidget(card)
        self.body.addStretch(1)

        self.title_mode.currentIndexChanged.connect(self._sync)
        self.title.textChanged.connect(self._sync)
        self.num_start.valueChanged.connect(self._sync)
        self.num_pad.valueChanged.connect(self._sync)
        self.stats.currentIndexChanged.connect(self._sync)
        self.extra.textChanged.connect(self._sync)
        state.preset_replaced.connect(self.load)
        self.load()

    def load(self):
        self._loading = True
        g = self.state.preset.general
        self.title_mode.setValue(g.title_mode)
        self.title.setText(g.title_template)
        self.num_start.setValue(g.num_start)
        self.num_pad.setValue(g.num_padding)
        self.chapters.load(g.chapters)
        self.tags.load(g.tags)
        self.stats.setValue(g.stats_tags)
        self.extra.setText(g.extra_args)
        self._loading = False
        self._update_ui()

    def _update_ui(self):
        self.row_title.setVisible(self.title_mode.value() == TitleMode.SET)
        s, p = self.num_start.value(), self.num_pad.value()
        self.num_example.setText(", ".join(str(s + i).zfill(p) for i in range(3)) + ", …")

    def _sync(self, *_):
        self._update_ui()
        if self._loading:
            return
        g = self.state.preset.general
        g.title_mode = self.title_mode.value()
        g.title_template = self.title.text()
        g.num_start = self.num_start.value()
        g.num_padding = self.num_pad.value()
        self.chapters.save(g.chapters)
        self.tags.save(g.tags)
        g.stats_tags = self.stats.value()
        g.extra_args = self.extra.text()
        self.state.mark_dirty()
