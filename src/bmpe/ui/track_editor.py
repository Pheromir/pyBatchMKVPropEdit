"""Editor for a track rule: match (which track) + actions (what to change).

Only the conditions and actions a rule actually uses are shown; further ones are added through
"+ Condition" / "+ Action" and removed again with the x next to them. Match and actions sit side by side
as long as there is room for it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
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
    FLAGS,
    MatchMode,
    NameMode,
    TrackRule,
    TrackType,
    TriState,
    format_positions,
    parse_positions,
)
from ..core.placeholders import FILE_PLACEHOLDERS, TRACK_PLACEHOLDERS
from ..core.summary import rule_sentence
from .widgets.common import EnumCombo, FlowLayout, LanguageCombo

# key -> (entry in the "+" menu, label of the form row)
CONDITIONS = {
    "positions": ("Position(s) in type", "Position"),
    "languages": ("Language(s)", "Language"),
    "codec": ("Codec contains", "Codec"),
    "name_regex": ("Name (regex)", "Name"),
    "is_default": ("Is default", "Default"),
    "is_forced": ("Is forced", "Forced"),
}
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
TWO_COLUMNS_FROM = 680  # narrower than this, the actions go below the match


def placeholder_button(target: LineEdit, include_track: bool, parent=None) -> ToolButton:
    btn = ToolButton(FIF.ADD_TO, parent)
    btn.setToolTip("Insert placeholder")
    btn.installEventFilter(ToolTipFilter(btn))
    menu = RoundMenu(parent=btn)
    items = dict(FILE_PLACEHOLDERS)
    if include_track:
        items.update(TRACK_PLACEHOLDERS)
    for key, desc in items.items():
        act = Action(f"{{{key}}}  –  {desc}")
        act.triggered.connect(lambda _=False, k=key: (target.insert(f"{{{k}}}"), target.setFocus()))
        menu.addAction(act)
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
        head.addWidget(self.label_edit, 0, Qt.AlignTop)
        head.addWidget(self.summary, 1)
        box.addLayout(head)
        line = QFrame(self.card)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(128, 128, 128, 55); border: none;")
        box.addWidget(line)

        self.columns = QBoxLayout(QBoxLayout.LeftToRight)
        self.columns.setSpacing(22)
        match = QVBoxLayout()
        match.setSpacing(SPACING)
        actions = QVBoxLayout()
        actions.setSpacing(SPACING)
        self.columns.addLayout(match, 1)
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
        self.type_combo = self._compact(EnumCombo([(t, t.label) for t in TrackType], type_row))
        self.match_mode = self._compact(
            EnumCombo([(MatchMode.FIRST, "first match"), (MatchMode.ALL, "all matches")], type_row)
        )
        self.match_mode.setToolTip(MATCH_MODE_TIP)
        self.match_mode.installEventFilter(ToolTipFilter(self.match_mode))
        type_row.installEventFilter(ToolTipFilter(type_row))  # shows the tip while the choice is greyed out
        self.type_row = type_row
        tl.addWidget(self.type_combo, 1)
        tl.addWidget(self.match_mode, 1)
        self._row(match, "Type", type_row)

        self.positions = self._compact(LineEdit(self.card))
        self.positions.setPlaceholderText("e.g. 1  or  1, 3  or  2-4")
        self._optional_row(match, "positions", self.positions)
        self.positions_hint = CaptionLabel("", self.card)
        self.positions_hint.setWordWrap(True)
        self.positions_hint_row = self._row(match, "", self.positions_hint)
        self.positions_hint_row.hide()
        self.languages = self._compact(LineEdit(self.card))
        self.languages.setPlaceholderText("e.g. ger, jpn")
        self._optional_row(match, "languages", self.languages)
        self.codec = self._compact(LineEdit(self.card))
        self.codec.setPlaceholderText("e.g. AAC, PGS")
        self._optional_row(match, "codec", self.codec)
        self.name_regex = self._compact(LineEdit(self.card))
        self.name_regex.setPlaceholderText("regular expression, e.g. sign|song")
        self._optional_row(match, "name_regex", self.name_regex)
        self.regex_hint = CaptionLabel("", self.card)
        self.regex_hint.setWordWrap(True)
        self.regex_hint.setTextColor("#c42b1c", "#ff99a4")
        self.regex_hint_row = self._row(match, "", self.regex_hint)
        self.regex_hint_row.hide()
        self.is_default = self._compact(EnumCombo([(True, "yes"), (False, "no")], self.card))
        self._optional_row(match, "is_default", self.is_default)
        self.is_forced = self._compact(EnumCombo([(True, "yes"), (False, "no")], self.card))
        self._optional_row(match, "is_forced", self.is_forced)
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
        self.name_mode = self._compact(EnumCombo([(NameMode.SET, "set to"), (NameMode.CLEAR, "remove")], name_row))
        self.name_template = self._compact(LineEdit(name_row))
        self.name_template.setPlaceholderText("e.g. {lang_name} · Signs & Songs · CR")
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
            self.label_edit, self.positions, self.languages, self.codec, self.name_regex, self.name_template, self.extra
        )
        for w in line_edits:
            w.textChanged.connect(self._sync)
        for w in (self.type_combo, self.match_mode, self.is_default, self.is_forced, self.name_mode):
            w.currentIndexChanged.connect(self._sync)
        self.lang_combo.textChanged.connect(self._sync)
        self._refresh()
        self.load(None)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        wanted = QBoxLayout.LeftToRight if self.width() >= TWO_COLUMNS_FROM else QBoxLayout.TopToBottom
        if self.columns.direction() != wanted:
            self.columns.setDirection(wanted)

    # ------------------------------------------------------------------ building blocks
    @staticmethod
    def _compact(widget, square: bool = False):
        """Brings an input down to the height all form rows share."""
        if square:
            widget.setFixedSize(QSize(FIELD_HEIGHT, FIELD_HEIGHT))
        else:
            widget.setFixedHeight(FIELD_HEIGHT)
        return widget

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
        lay.addWidget(editor, 1)
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
        note.setTextColor("#606060", "#a0a0a0")
        column.addWidget(note)
        return note

    def _addable_conditions(self) -> list[tuple[str, object]]:
        """(menu text, what to do) for every condition the rule does not use yet."""
        return [(label, lambda k=key: self._add(k)) for key, (label, _) in CONDITIONS.items() if key not in self._shown]

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
        for text, slot in self._addable_conditions():
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
        self.languages.setText(", ".join(m.languages))
        self.codec.setText(m.codec_contains)
        self.name_regex.setText(m.name_regex)
        self.is_default.setValue(m.is_default is not False)
        self.is_forced.setValue(m.is_forced is not False)
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
            "name_regex": bool(m.name_regex),
            "is_default": m.is_default is not None,
            "is_forced": m.is_forced is not None,
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
        regex_error = self.rule.matcher.regex_error() if self.rule and "name_regex" in self._shown else ""
        self.regex_hint.setText(f"Not a valid regular expression, the rule is skipped: {regex_error}")
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

        positions, invalid = parse_positions(self.positions.text()) if "positions" in shown else ([], [])
        if invalid:
            self._show_positions_hint(f"Invalid and ignored: {', '.join(invalid)}", error=True)
        else:
            self.positions_hint_row.hide()
        m.positions = positions
        m.languages = [x.strip() for x in self.languages.text().split(",") if x.strip()] if "languages" in shown else []
        m.codec_contains = self.codec.text().strip() if "codec" in shown else ""
        m.name_regex = self.name_regex.text().strip() if "name_regex" in shown else ""
        m.is_default = self.is_default.value() if "is_default" in shown else None
        m.is_forced = self.is_forced.value() if "is_forced" in shown else None
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
        else:
            getattr(self, key).setText("")
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
