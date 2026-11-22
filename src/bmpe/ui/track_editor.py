"""Editor for a track rule: match (which track) + actions (what to change).

Only the conditions and actions a rule actually uses are shown; further ones are added through
"+ Condition" / "+ Action" and removed again with the x next to them. Match and actions sit side by side
as long as there is room for it.
"""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    DropDownPushButton,
    LineEdit,
    PushButton,
    RoundMenu,
    SimpleCardWidget,
    StrongBodyLabel,
    ToolButton,
    ToolTipFilter,
    TransparentToolButton,
    getFont,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from ..core.languages import Language
from ..core.models import (
    FLAG_CONDITIONS,
    FLAGS,
    NUMERIC,
    MatchMode,
    NameMode,
    NameOp,
    NumCondition,
    NumOp,
    TextCondition,
    TextOp,
    TrackRule,
    TrackType,
    TriState,
    format_positions,
    format_value,
    parse_positions,
)
from ..core.placeholders import FILE_PLACEHOLDERS, FILTERS, PATTERN_PLACEHOLDERS, TRACK_PLACEHOLDERS
from ..core.summary import rule_sentence
from .widgets.common import EnumCombo, FlowLayout, LanguageCombo, plain_text

# key -> (entry in the "+" menu, label of the form row)
CONDITIONS = {
    "positions": ("Position(s) in type", "Position"),
    "languages": ("Language(s)", "Language"),
    "codec": ("Codec", "Codec"),
    "name_regex": ("Name", "Name"),
    "is_default": ("Default", "Flag"),
    "is_forced": ("Forced", "Flag"),
    **{f"flag:{key}": (FLAGS[key][2], "Flag") for key in FLAG_CONDITIONS},
    **{f"num:{key}": (f"{label} ({unit})" if unit else label, label) for key, (label, unit, _) in NUMERIC.items()},
    "path": ("Path of the file", "Path"),
    "file_name": ("File name", "File"),
}
CONDITION_GROUPS = [
    ("Track", ["positions", "languages", "codec", "name_regex"]),
    ("Flags", ["is_default", "is_forced", *(f"flag:{key}" for key in FLAG_CONDITIONS)]),
    ("Technical values", [f"num:{key}" for key in NUMERIC]),
    ("File", ["path", "file_name"]),
]
TEXT_OPS = [
    (TextOp.CONTAINS, "contains"),
    (TextOp.NOT_CONTAINS, "doesn't contain"),
    (TextOp.MATCHES, "matches"),
    (TextOp.NOT_MATCHES, "doesn't match"),
]
NAME_OPS = [
    (NameOp.MATCHES, "matches"),
    (NameOp.NOT_MATCHES, "doesn't match"),
    (NameOp.EMPTY, "is empty"),
    (NameOp.NOT_EMPTY, "isn't empty"),
]
NUM_OPS = [(op, op.symbol) for op in NumOp]
REGEX_TIP = "“matches” and “doesn't match” take a regular expression; case is ignored."
FILE_TIP = (
    "Checked once per file: in a file that does not meet it, the rule matches no track. " + REGEX_TIP
)
ACTION_ROWS = {
    "name": ("Track name", "Name"),
    "language": ("Language", "Language"),
    "extra": ("Extra parameters", "Extra"),
}
MATCH_MODE_TIP = "Apply the rule to the first matching track only, or to all matching tracks"
MATCH_MODE_LOCKED_TIP = (
    "Not used while a position is set: the rule then applies to exactly the listed positions "
    "(as far as they meet the other conditions)."
)
EXCLUSIVE_TIP = "This track becomes the default track; all other tracks of the same type lose the default flag."

# one grid for every form row, so that labels, fields and the x buttons line up in both columns
LABEL_WIDTH = 72
FIELD_HEIGHT = 30
GUTTER = 24  # room for the x to the right of a field
SPACING = 6
MATCH_COLUMN_WIDTH = 390  # fixed while the columns are side by side
TWO_COLUMNS_FROM = 810  # narrower than this, the actions go below the match
QWIDGETSIZE_MAX = (1 << 24) - 1  # Qt's "no maximum width"; PySide6 does not export the constant


def placeholder_button(target: LineEdit, include_track: bool, parent=None) -> ToolButton:
    """"+" next to a template field: inserts placeholders and filters, grouped in submenus."""
    btn = ToolButton(FIF.ADD_TO, parent)
    btn.setToolTip("Insert placeholder or filter")
    btn.installEventFilter(ToolTipFilter(btn))
    menu = RoundMenu(parent=btn)

    def add_group(title: str, items: dict[str, str], text) -> None:
        sub = RoundMenu(title, menu)
        for key, desc in items.items():
            act = Action(f"{text(key)}  –  {desc}")
            act.triggered.connect(lambda _=False, s=text(key): (target.insert(s), target.setFocus()))
            sub.addAction(act)
        menu.addMenu(sub)

    add_group("File", FILE_PLACEHOLDERS, lambda k: f"{{{k}}}")
    if include_track:
        add_group("Track", TRACK_PLACEHOLDERS, lambda k: f"{{{k}}}")
    add_group("File name pattern", PATTERN_PLACEHOLDERS, lambda k: f"{{{k}}}")
    # a filter goes inside the braces, e.g. {track_name|upper}
    add_group("Filters (inside the braces)", FILTERS, lambda k: "|" + k.split(":")[0] + (":" if ":" in k else ""))
    btn.clicked.connect(lambda: menu.exec(btn.mapToGlobal(btn.rect().bottomLeft())))
    return btn


def remove_button(tip: str, parent=None, width: int = GUTTER, height: int = FIELD_HEIGHT) -> TransparentToolButton:
    btn = TransparentToolButton(FIF.CLOSE, parent)
    btn.setFixedSize(QSize(width, height))
    btn.setIconSize(QSize(9, 9))
    btn.setToolTip(tip)
    btn.installEventFilter(ToolTipFilter(btn))
    return btn


class AddButton(DropDownPushButton):
    """"+" button whose menu is put together the moment it opens, so it lists exactly what can still be added.

    A new menu is created every time: RoundMenu.clear() leaves separators behind, which piled up as stray
    lines at the top when one menu was refilled again and again.
    """

    build = None  # callable(menu) that fills the menu; set after creating the button

    def _showMenu(self):
        old = self.menu()
        menu = RoundMenu(parent=self)
        if self.build is not None:
            self.build(menu)
        self.setMenu(menu)
        if old is not None:
            old.deleteLater()
        super()._showMenu()


def menu_heading(menu: RoundMenu, title: str) -> None:
    """Small heading above a group of menu entries; it cannot be clicked."""
    label = QLabel(title, menu)
    font = getFont(11, QFont.DemiBold)
    font.setCapitalization(QFont.AllUppercase)
    font.setLetterSpacing(QFont.PercentageSpacing, 108)
    label.setFont(font)
    label.setStyleSheet(f"color: {'#9d9d9d' if isDarkTheme() else '#6e6e6e'}; background: transparent;")
    label.setContentsMargins(3, 4, 12, 0)  # lines the heading up with the text of the entries
    label.setFixedSize(QSize(max(label.sizeHint().width(), 150), 24))
    menu.addWidget(label, selectable=False)


class ActionChip(QWidget):
    """A set flag such as "Forced: yes": a click switches between yes and no, the x removes it."""

    toggled = Signal()
    removed = Signal()

    def __init__(self, tip: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.button = PushButton("", self)
        self.button.setFixedHeight(28)
        self.button.setFont(getFont(13))
        if tip:
            self.button.setToolTip(tip)
            self.button.installEventFilter(ToolTipFilter(self.button))
        self.close_button = remove_button("Remove (leave unchanged)", self, width=20, height=28)
        lay.addWidget(self.button)
        lay.addWidget(self.close_button)
        self.button.clicked.connect(self.toggled)
        self.close_button.clicked.connect(self.removed)

    def setText(self, text: str) -> None:
        self.button.setText(text)
        self.button.adjustSize()
        self.updateGeometry()


class TrackRuleEditor(QWidget):
    changed = Signal()

    def __init__(self, languages: list[Language], parent=None, shortlist: list[str] | None = None):
        super().__init__(parent)
        self.rule: TrackRule | None = None
        self._loading = False
        self._positions_error = False
        self._shown: set[str] = set()  # keys of CONDITIONS / ACTION_ROWS that have a row
        self._flags: dict[str, TriState] = {k: TriState.UNCHANGED for k in FLAGS}
        self._exclusive = False
        self._rows: dict[str, QWidget] = {}
        self._focus: dict[str, QWidget] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.card = SimpleCardWidget(self)
        self._cards = [self.card]
        box = QVBoxLayout(self.card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(10)

        # ---------------- header: label + the rule as a sentence
        head = QHBoxLayout()
        head.setSpacing(12)
        self.label_edit = self._compact(LineEdit(self.card))
        self.label_edit.setPlaceholderText("Label (optional)")
        self.label_edit.setFixedWidth(190)
        self.summary = BodyLabel("", self.card)
        self.summary.setFont(getFont(13))
        self.summary.setWordWrap(True)
        plain_text(self.summary)  # contains names and patterns, possibly from an imported preset
        head.addWidget(self.label_edit, 0, Qt.AlignTop)
        head.addWidget(self.summary, 1)
        box.addLayout(head)
        line = QFrame(self.card)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(128, 128, 128, 55); border: none;")
        box.addWidget(line)

        self.columns = QBoxLayout(QBoxLayout.LeftToRight)
        self.columns.setSpacing(22)
        # side by side, the match column keeps its width and the actions get all the extra room
        self.match_column = QWidget(self.card)
        match = QVBoxLayout(self.match_column)
        match.setContentsMargins(0, 0, 0, 0)
        match.setSpacing(SPACING)
        actions = QVBoxLayout()
        actions.setSpacing(SPACING)
        self.match_column.setFixedWidth(MATCH_COLUMN_WIDTH)
        self.columns.addWidget(self.match_column, 0)
        self.columns.addLayout(actions, 1)
        box.addLayout(self.columns)

        # ---------------- match
        self.btn_add_condition = AddButton(FIF.ADD, "Condition", self.card)
        self.btn_add_condition.build = self._build_condition_menu
        self._column_head(match, "Match", self.btn_add_condition)

        type_row = QWidget(self.card)
        tl = QHBoxLayout(type_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(SPACING)
        self.type_combo = self._compact(EnumCombo([(t, t.label) for t in TrackType], type_row).fit_to_items())
        self.match_mode = self._compact(
            EnumCombo([(MatchMode.FIRST, "first match"), (MatchMode.ALL, "all matches")], type_row).fit_to_items()
        )
        self.match_mode.setToolTip(MATCH_MODE_TIP)
        self.match_mode.installEventFilter(ToolTipFilter(self.match_mode))
        type_row.installEventFilter(ToolTipFilter(type_row))  # shows the tip while the choice is greyed out
        self.type_row = type_row
        tl.addWidget(self.type_combo)
        tl.addWidget(self.match_mode)
        tl.addStretch(1)
        self._row(match, "Type", type_row)

        self.positions = self._compact(LineEdit(self.card))
        self.positions.setPlaceholderText("e.g. 1  or  1, 3  or  2-4")
        self._optional_row(match, "positions", self.positions)
        self.positions_hint = CaptionLabel("", self.card)
        self.positions_hint.setWordWrap(True)
        plain_text(self.positions_hint)
        self.positions_hint_row = self._row(match, "", self.positions_hint)
        self.positions_hint_row.hide()
        self.languages_op = self._op_combo([(False, "is"), (True, "is not")])
        self.languages = self._compact(LineEdit(self.card))
        self.languages.setPlaceholderText("e.g. ger, jpn")
        self._optional_row(match, "languages", self._pair(self.languages_op, self.languages), focus=self.languages)
        self.codec_op = self._op_combo([(False, "contains"), (True, "doesn't contain")])
        self.codec = self._compact(LineEdit(self.card))
        self.codec.setPlaceholderText("e.g. AAC, PGS")
        self._optional_row(match, "codec", self._pair(self.codec_op, self.codec), focus=self.codec)
        self.name_op = self._op_combo(NAME_OPS, "“matches” and “doesn't match” take a regular expression.")
        self.name_regex = self._compact(LineEdit(self.card))
        self.name_regex.setPlaceholderText("e.g. sign|song")
        self._optional_row(match, "name_regex", self._pair(self.name_op, self.name_regex), focus=self.name_regex)
        # flags: "Flag | Commentary | yes"; the flag name lines up with the word choices of the rows above
        self._flag_names: list[BodyLabel] = []

        def flag_row(key: str, label: str) -> EnumCombo:
            combo = self._compact(EnumCombo([(True, "yes"), (False, "no")], self.card).fit_to_items())
            name = BodyLabel(label, self.card)
            name.setFont(getFont(13))
            self._flag_names.append(name)
            self._optional_row(match, key, self._pair(name, combo, stretch=False), focus=combo)
            return combo

        self.is_default = flag_row("is_default", FLAGS["default"][2])
        self.is_forced = flag_row("is_forced", FLAGS["forced"][2])
        self.flag_conds = {key: flag_row(f"flag:{key}", FLAGS[key][2]) for key in FLAG_CONDITIONS}

        number = QRegularExpressionValidator(QRegularExpression(r"\d{0,7}([.,]\d{0,3})?"), self)
        self.num_ops: dict[str, EnumCombo] = {}
        self.num_values: dict[str, LineEdit] = {}
        for key, (_, unit, _) in NUMERIC.items():
            op = self._op_combo(NUM_OPS)
            value = self._compact(LineEdit(self.card))
            value.setValidator(number)
            value.setFixedWidth(90)
            unit_label = CaptionLabel(unit, self.card)
            unit_label.setTextColor("#606060", "#a0a0a0")
            self.num_ops[key], self.num_values[key] = op, value
            self._optional_row(match, f"num:{key}", self._pair(op, value, unit_label, stretch=False), focus=value)

        self.path_op = self._op_combo(TEXT_OPS, FILE_TIP)
        self.path_value = self._compact(LineEdit(self.card))
        self.path_value.setPlaceholderText("e.g. Anime")
        self._optional_row(match, "path", self._pair(self.path_op, self.path_value), focus=self.path_value)
        self.file_op = self._op_combo(TEXT_OPS, FILE_TIP)
        self.file_value = self._compact(LineEdit(self.card))
        self.file_value.setPlaceholderText("e.g. S01E")
        self._optional_row(match, "file_name", self._pair(self.file_op, self.file_value), focus=self.file_value)

        # one width for the word choices, so the values below each other start at the same place
        word_ops = (self.languages_op, self.codec_op, self.name_op, self.path_op, self.file_op)
        widest = max(op.width() for op in word_ops)
        for w in (*word_ops, *self._flag_names):
            w.setFixedWidth(widest)

        self.regex_hint = CaptionLabel("", self.card)
        self.regex_hint.setWordWrap(True)
        plain_text(self.regex_hint)
        self.regex_hint.setTextColor("#c42b1c", "#ff99a4")
        self.regex_hint_row = self._row(match, "", self.regex_hint)
        self.regex_hint_row.hide()
        self.match_info = self._note(match)
        match.addStretch(1)

        # ---------------- actions
        self.btn_add_action = AddButton(FIF.ADD, "Action", self.card)
        self.btn_add_action.build = self._build_action_menu
        self._column_head(actions, "Actions", self.btn_add_action)

        flags_holder = QWidget(self.card)
        self.flag_flow = FlowLayout(flags_holder, h_spacing=4, v_spacing=4)
        self.exclusive_chip = ActionChip(EXCLUSIVE_TIP, flags_holder)
        self.exclusive_chip.setText("Exclusive default")
        self.exclusive_chip.removed.connect(lambda: self._set_exclusive(False))
        self.flag_flow.addWidget(self.exclusive_chip)
        self.flag_chips: dict[str, ActionChip] = {}
        for key in FLAGS:
            chip = ActionChip("Click to switch between yes and no", flags_holder)
            chip.toggled.connect(lambda k=key: self._toggle_flag(k))
            chip.removed.connect(lambda k=key: self._set_flag(k, TriState.UNCHANGED))
            self.flag_flow.addWidget(chip)
            self.flag_chips[key] = chip
        self.flags_row = self._row(actions, "Flags", flags_holder)

        name_row = QWidget(self.card)
        nl = QHBoxLayout(name_row)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(SPACING)
        self.name_mode = self._compact(
            EnumCombo([(NameMode.SET, "set to"), (NameMode.CLEAR, "remove")], name_row).fit_to_items()
        )
        self.name_template = self._compact(LineEdit(name_row))
        self.name_template.setPlaceholderText("e.g. {lang_name} · {format} {channels} {channels_name}")
        nl.addWidget(self.name_mode)
        nl.addWidget(self.name_template, 1)
        nl.addWidget(self._compact(placeholder_button(self.name_template, True, name_row), square=True))
        self._optional_row(actions, "name", name_row, focus=self.name_template)

        self.lang_combo = self._compact(LanguageCombo(languages, self.card, shortlist))
        self._optional_row(actions, "language", self.lang_combo)

        extra_row = QWidget(self.card)
        el = QHBoxLayout(extra_row)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(SPACING)
        self.extra = self._compact(LineEdit(extra_row))
        self.extra.setPlaceholderText('e.g. --set "codec-name=..."')
        el.addWidget(self.extra, 1)
        el.addWidget(self._compact(placeholder_button(self.extra, True, extra_row), square=True))
        self._optional_row(actions, "extra", extra_row, focus=self.extra)
        self.result = self._note(actions)
        actions.addStretch(1)

        root.addWidget(self.card)
        self.placeholder = CaptionLabel("Select a rule on the left to edit it, or create a new one.", self)
        self.placeholder.setTextColor("#606060", "#a0a0a0")
        self.placeholder.setContentsMargins(4, 8, 0, 0)
        root.addWidget(self.placeholder)
        root.addStretch(1)

        # ---------------- signals
        self.positions.editingFinished.connect(self._normalize_positions)
        line_edits = (
            self.label_edit, self.positions, self.languages, self.codec, self.name_regex, self.name_template,
            self.extra, self.path_value, self.file_value, *self.num_values.values(),
        )
        for w in line_edits:
            w.textChanged.connect(self._sync)
        combos = (
            self.type_combo, self.match_mode, self.is_default, self.is_forced, self.name_mode, self.languages_op,
            self.codec_op, self.name_op, self.path_op, self.file_op, *self.num_ops.values(),
            *self.flag_conds.values(),
        )
        for w in combos:
            w.currentIndexChanged.connect(self._sync)
        self.lang_combo.textChanged.connect(self._sync)
        self._refresh()
        self.load(None)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        wanted = QBoxLayout.LeftToRight if self.width() >= TWO_COLUMNS_FROM else QBoxLayout.TopToBottom
        if self.columns.direction() != wanted:
            self.columns.setDirection(wanted)
            if wanted == QBoxLayout.LeftToRight:
                self.match_column.setFixedWidth(MATCH_COLUMN_WIDTH)
            else:  # one below the other: both use the full width
                self.match_column.setMinimumWidth(0)
                self.match_column.setMaximumWidth(QWIDGETSIZE_MAX)

    # ------------------------------------------------------------------ building blocks
    @staticmethod
    def _compact(widget, square: bool = False):
        """Brings an input down to the height all form rows share."""
        if square:
            widget.setFixedSize(QSize(FIELD_HEIGHT, FIELD_HEIGHT))
        else:
            widget.setFixedHeight(FIELD_HEIGHT)
        return widget

    def _op_combo(self, items, tip: str = "") -> EnumCombo:
        """Fixed-width choice in front of a condition's value, e.g. "is" / "is not"."""
        combo = self._compact(EnumCombo(items, self.card).fit_to_items())
        if tip:
            combo.setToolTip(tip)
            combo.installEventFilter(ToolTipFilter(combo))
        return combo

    def _pair(self, *widgets: QWidget, stretch: bool = True) -> QWidget:
        """Puts the widgets of one condition side by side; the last one takes the room left (`stretch`)."""
        holder = QWidget(self.card)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING)
        for i, w in enumerate(widgets):
            last = i == len(widgets) - 1
            lay.addWidget(w, 1 if (last and stretch) else 0)
        # keeps the rest at the left when the stretching widget is hidden (name "is empty")
        lay.addStretch(0 if stretch else 1)
        return holder

    def _column_head(self, column: QVBoxLayout, title: str, button: DropDownPushButton) -> None:
        """Heading with the "+" button; the button ends where the fields below it end."""
        button.setFixedHeight(28)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 2)
        bar.setSpacing(SPACING)
        bar.addWidget(StrongBodyLabel(title, self.card))
        bar.addStretch(1)
        bar.addWidget(button)
        bar.addSpacing(GUTTER + SPACING)
        column.addLayout(bar)

    def _row(self, column: QVBoxLayout, label: str, editor: QWidget, key: str = "") -> QWidget:
        """Form row: label, field and, for a row that can be removed (`key`), the x in the gutter."""
        row = QWidget(self.card)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING)
        lbl = BodyLabel(label, row)
        lbl.setFont(getFont(13))
        lbl.setTextColor("#5c5c5c", "#c8c8c8")
        lbl.setFixedWidth(LABEL_WIDTH)
        lay.addWidget(lbl, 0, Qt.AlignTop)
        lbl.setFixedHeight(FIELD_HEIGHT)
        # a field with a fixed width stays at the left; the x keeps its place in the gutter
        fixed = editor.maximumWidth() < QWIDGETSIZE_MAX
        lay.addWidget(editor, 1, Qt.AlignLeft if fixed else Qt.Alignment())
        if key:
            btn = remove_button("Remove", row)
            btn.clicked.connect(lambda: self._remove(key))
            lay.addWidget(btn, 0, Qt.AlignTop)
        else:
            gutter = QWidget(row)
            gutter.setFixedWidth(GUTTER)
            lay.addWidget(gutter)
        column.addWidget(row)
        return row

    def _optional_row(self, column: QVBoxLayout, key: str, editor: QWidget, focus=None) -> None:
        """A form row that can be removed again; hidden until the rule uses it."""
        label = (CONDITIONS.get(key) or ACTION_ROWS[key])[1]
        self._rows[key] = self._row(column, label, editor, key)
        self._focus[key] = focus or editor

    def _note(self, column: QVBoxLayout) -> CaptionLabel:
        note = CaptionLabel("", self.card)
        note.setWordWrap(True)
        plain_text(note)  # shows track names, which come from the files
        note.setTextColor("#606060", "#a0a0a0")
        column.addWidget(note)
        return note

    def _addable_conditions(self) -> list[tuple[str, list[tuple[str, object]]]]:
        """The conditions the rule does not use yet, as (heading, [(menu text, what to do)]) groups.

        Technical values are only offered for the track types that have them.
        """
        track_type = self.type_combo.value()
        groups = []
        for title, keys in CONDITION_GROUPS:
            entries = [
                (CONDITIONS[k][0], lambda key=k: self._add(key))
                for k in keys
                if k not in self._shown and (not k.startswith("num:") or track_type in NUMERIC[k[4:]][2])
            ]
            if entries:
                groups.append((title, entries))
        return groups

    def _addable_actions(self) -> list[tuple[str, list[tuple[str, object]]]]:
        """The actions the rule does not use yet, as (heading, [(menu text, what to do)]) groups."""
        flags = [
            (label, lambda k=key: self._set_flag(k, TriState.YES))
            for key, (_, _, label) in FLAGS.items()
            if self._flags[key] == TriState.UNCHANGED and not (key == "default" and self._exclusive)
        ]
        if not self._exclusive:
            flags.append(("Exclusive default", lambda: self._set_exclusive(True)))
        rows = {key: (ACTION_ROWS[key][0], lambda k=key: self._add(k)) for key in ACTION_ROWS if key not in self._shown}
        groups = [
            ("Flags", flags),
            ("Properties", [rows[k] for k in ("name", "language") if k in rows]),
            ("Advanced", [rows[k] for k in ("extra",) if k in rows]),
        ]
        return [(title, entries) for title, entries in groups if entries]

    def _build_condition_menu(self, menu: RoundMenu) -> None:
        for n, (title, entries) in enumerate(self._addable_conditions()):
            if n:
                menu.addSeparator()
            menu_heading(menu, title)
            for text, slot in entries:
                self._menu_item(menu, text, slot)

    def _build_action_menu(self, menu: RoundMenu) -> None:
        for n, (title, entries) in enumerate(self._addable_actions()):
            if n:
                menu.addSeparator()
            menu_heading(menu, title)
            for text, slot in entries:
                self._menu_item(menu, text, slot)

    @staticmethod
    def _menu_item(menu: RoundMenu, text: str, slot) -> None:
        act = Action(text)
        act.triggered.connect(lambda _=False: slot())
        menu.addAction(act)

    # ------------------------------------------------------------------ load / store
    def set_languages(self, languages: list[Language], shortlist: list[str] | None = None) -> None:
        self._loading = True
        self.lang_combo.setLanguages(languages, shortlist)
        self._loading = False

    def load(self, rule: TrackRule | None) -> None:
        self.rule = rule
        self.setEnabled(rule is not None)
        for card in self._cards:
            card.setVisible(rule is not None)
        self.placeholder.setVisible(rule is None)
        if rule is None:
            return
        self._loading = True
        m, a = rule.matcher, rule.actions
        self.label_edit.setText(rule.label)
        self.type_combo.setValue(m.track_type)
        self.match_mode.setValue(m.match_mode)
        self.positions.setText(format_positions(m.positions))
        self.positions_hint_row.hide()
        self._positions_error = False
        self.languages_op.setValue(m.languages_not)
        self.languages.setText(", ".join(m.languages))
        self.codec_op.setValue(m.codec_not)
        self.codec.setText(m.codec_contains)
        self.name_op.setValue(m.name_op)
        self.name_regex.setText(m.name_regex)
        for key in NUMERIC:
            cond = m.numbers.get(key)
            self.num_ops[key].setValue(cond.op if cond else NumOp.GE)
            self.num_values[key].setText(format_value(cond.value) if cond else "")
        for op, edit, cond in ((self.path_op, self.path_value, m.path), (self.file_op, self.file_value, m.file_name)):
            op.setValue(cond.op if cond else TextOp.CONTAINS)
            edit.setText(cond.value if cond else "")
        self.is_default.setValue(m.is_default is not False)
        self.is_forced.setValue(m.is_forced is not False)
        for key, combo in self.flag_conds.items():
            combo.setValue(m.flags.get(key, True))
        self.name_mode.setValue(NameMode.CLEAR if a.name_mode == NameMode.CLEAR else NameMode.SET)
        self.name_template.setText(a.name_template)
        self.lang_combo.setCode(a.language or "")
        self.extra.setText(a.extra_args)
        for edit in (self.label_edit, self.name_template, self.extra):  # show the beginning of long texts
            edit.setCursorPosition(0)
        self._flags = {k: a.flags.get(k, TriState.UNCHANGED) for k in FLAGS}
        self._exclusive = a.exclusive_default
        used = {
            "positions": bool(m.positions),
            "languages": bool(m.languages),
            "codec": bool(m.codec_contains),
            "name_regex": m.uses_name,
            "is_default": m.is_default is not None,
            "is_forced": m.is_forced is not None,
            **{f"flag:{key}": key in m.flags for key in FLAG_CONDITIONS},
            **{f"num:{key}": key in m.numeric_keys() for key in NUMERIC},
            "path": bool(m.path and m.path.active),
            "file_name": bool(m.file_name and m.file_name.active),
            "name": a.name_mode != NameMode.UNCHANGED,
            "language": bool(a.language),
            "extra": bool(a.extra_args.strip()),
        }
        self._shown = {key for key, on in used.items() if on}
        self._loading = False
        self._refresh()

    def _refresh(self) -> None:
        """Shows exactly the rows and chips that are in use."""
        for key, row in self._rows.items():
            row.setVisible(key in self._shown)
        if "positions" not in self._shown:
            self.positions_hint_row.hide()
        # with positions the first/all choice does not apply; the stored choice comes back when they are removed
        by_position = bool(self.rule and self.rule.matcher.positions)
        self.match_mode.setEnabled(not by_position)
        self.type_row.setToolTip(MATCH_MODE_LOCKED_TIP if by_position else "")
        self.name_regex.setVisible(self.name_op.value() in (NameOp.MATCHES, NameOp.NOT_MATCHES))
        regex_error = self.rule.matcher.regex_error() if self.rule else ""
        self.regex_hint.setText(f"Not a valid regular expression, the rule is skipped ({regex_error})")
        self.regex_hint_row.setVisible(bool(regex_error))
        any_flag = self._exclusive
        for key, chip in self.flag_chips.items():
            state = self._flags[key]
            on = state != TriState.UNCHANGED and not (key == "default" and self._exclusive)
            any_flag = any_flag or on
            chip.setVisible(on)
            chip.setText(f"{FLAGS[key][2]}: {'yes' if state == TriState.YES else 'no'}")
        self.exclusive_chip.setVisible(self._exclusive)
        self.flags_row.setVisible(any_flag)
        self.flag_flow.invalidate()
        self.name_template.setEnabled(self.name_mode.value() == NameMode.SET)
        self.summary.setText(rule_sentence(self.rule) if self.rule else "")
        self.btn_add_condition.setEnabled(bool(self._addable_conditions()))
        self.btn_add_action.setEnabled(bool(self._addable_actions()))

    def _sync(self, *_):
        if self._loading or self.rule is None:
            return
        shown = self._shown
        m, a = self.rule.matcher, self.rule.actions
        self.rule.label = self.label_edit.text().strip()
        m.track_type = self.type_combo.value()
        for key in [k for k in shown if k.startswith("num:") and m.track_type not in NUMERIC[k[4:]][2]]:
            shown.discard(key)  # e.g. a frame rate after switching to audio

        positions, invalid = parse_positions(self.positions.text()) if "positions" in shown else ([], [])
        if invalid:
            self._show_positions_hint(f"Invalid and ignored: {', '.join(invalid)}", error=True)
        else:
            self.positions_hint_row.hide()
        m.positions = positions
        m.languages = [x.strip() for x in self.languages.text().split(",") if x.strip()] if "languages" in shown else []
        m.languages_not = bool(m.languages) and self.languages_op.value()
        m.codec_contains = self.codec.text().strip() if "codec" in shown else ""
        m.codec_not = bool(m.codec_contains) and self.codec_op.value()
        m.name_op = self.name_op.value() if "name_regex" in shown else NameOp.MATCHES
        uses_regex = m.name_op in (NameOp.MATCHES, NameOp.NOT_MATCHES)
        m.name_regex = self.name_regex.text().strip() if "name_regex" in shown and uses_regex else ""
        m.is_default = self.is_default.value() if "is_default" in shown else None
        m.is_forced = self.is_forced.value() if "is_forced" in shown else None
        m.flags = {key: combo.value() for key, combo in self.flag_conds.items() if f"flag:{key}" in shown}
        numbers: dict[str, NumCondition] = {}
        for key in NUMERIC:
            text = self.num_values[key].text().strip().replace(",", ".")
            if f"num:{key}" in shown and text and text != ".":
                numbers[key] = NumCondition(op=self.num_ops[key].value(), value=float(text))
        m.numbers = numbers
        m.path = self._text_condition("path", self.path_op, self.path_value)
        m.file_name = self._text_condition("file_name", self.file_op, self.file_value)
        m.match_mode = self.match_mode.value()

        for key, state in self._flags.items():
            a.flags[key] = state
        a.exclusive_default = self._exclusive
        a.name_mode = self.name_mode.value() if "name" in shown else NameMode.UNCHANGED
        a.name_template = self.name_template.text() if "name" in shown else ""
        a.language = (self.lang_combo.code() or None) if "language" in shown else None
        a.extra_args = self.extra.text() if "extra" in shown else ""
        self._refresh()
        self.changed.emit()

    def _text_condition(self, key: str, op: EnumCombo, edit: LineEdit) -> TextCondition | None:
        value = edit.text().strip()
        return TextCondition(op=op.value(), value=value) if key in self._shown and value else None

    # ------------------------------------------------------------------ adding / removing
    def _add(self, key: str) -> None:
        self._shown.add(key)
        self._sync()
        self._focus[key].setFocus()

    def _remove(self, key: str) -> None:
        self._shown.discard(key)
        self._loading = True  # empty the field without storing every step
        if key in ("is_default", "is_forced"):
            getattr(self, key).setValue(True)
        elif key == "name":
            self.name_mode.setValue(NameMode.SET)
            self.name_template.setText("")
        elif key == "language":
            self.lang_combo.setCode("")
        elif key.startswith("flag:"):
            self.flag_conds[key[5:]].setValue(True)
        elif key.startswith("num:"):
            self.num_ops[key[4:]].setValue(NumOp.GE)
            self.num_values[key[4:]].setText("")
        elif key in ("path", "file_name"):
            op, edit = (self.path_op, self.path_value) if key == "path" else (self.file_op, self.file_value)
            op.setValue(TextOp.CONTAINS)
            edit.setText("")
        else:
            getattr(self, key).setText("")
            if key in ("languages", "codec"):
                getattr(self, f"{key}_op").setValue(False)
            elif key == "name_regex":
                self.name_op.setValue(NameOp.MATCHES)
        self._loading = False
        self._sync()

    def _set_flag(self, key: str, state: TriState) -> None:
        self._flags[key] = state
        self._sync()

    def _toggle_flag(self, key: str) -> None:
        self._set_flag(key, TriState.NO if self._flags[key] == TriState.YES else TriState.YES)

    def _set_exclusive(self, on: bool) -> None:
        self._exclusive = on
        if on:  # "exclusive default" already decides the default flag
            self._flags["default"] = TriState.UNCHANGED
        self._sync()

    # ------------------------------------------------------------------ hints
    def _show_positions_hint(self, text: str, error: bool) -> None:
        self._positions_error = error
        if error:
            self.positions_hint.setTextColor("#c42b1c", "#ff99a4")
        else:
            self.positions_hint.setTextColor("#606060", "#a0a0a0")
        self.positions_hint.setText(text)
        self.positions_hint_row.show()

    def _normalize_positions(self) -> None:
        """Normalize after editing, e.g. "3,1, 2" -> "1-3"."""
        if self.rule is None:
            return
        positions, invalid = parse_positions(self.positions.text())
        if not invalid:
            text = format_positions(positions)
            if text != self.positions.text():
                self._loading = True
                self.positions.setText(text)
                self._loading = False

    def set_match_info(self, text: str) -> None:
        self.match_info.setText(text)
        self.match_info.setVisible(bool(text))

    def set_result(self, text: str) -> None:
        """What this rule changes in the reference file."""
        self.result.setText(text)
        self.result.setVisible(bool(text))
