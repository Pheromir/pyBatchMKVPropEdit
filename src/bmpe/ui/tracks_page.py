"""Tracks page: reference file, rule list, rule editor, track presets."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    ComboBox,
    DropDownPushButton,
    InfoBar,
    PushButton,
    RoundMenu,
    SmoothScrollArea,
    StrongBodyLabel,
    TableWidget,
    ToolButton,
    ToolTipFilter,
    getFont,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from ..core.command import FIELD_EXTRA, FIELD_LANGUAGE, FIELD_NAME, YES, plan_file
from ..core.matcher import matching_tracks
from ..core.models import (
    FLAGS,
    GeneralSettings,
    GlobalPreset,
    TrackInfo,
    TrackMatcher,
    TrackPreset,
    TrackRule,
    TrackType,
)
from .rule_list import RuleList
from .state import AppState
from .track_editor import TrackRuleEditor
from .widgets.common import Splitter, TextInputDialog, page_layout

REF_COLUMNS = ["Type", "No.", "Language", "Codec", "Name", "Flags"]
COL_LANG, COL_NAME, COL_FLAGS = 2, 4, 5
ARROW = "  →  "
FLAG_SHORT = {
    "default": "Default",
    "forced": "Forced",
    "hearing_impaired": "HI",
    "visual_impaired": "VI",
    "text_descriptions": "TD",
    "original": "Orig",
    "commentary": "Comm",
}


FLAG_BY_LABEL = {label: key for key, (_, _, label) in FLAGS.items()}


def flags_text(t: TrackInfo, override: dict[str, bool] | None = None) -> str:
    """Short list of the set flags; `override` holds planned new values."""
    override = override or {}

    def val(key: str) -> bool:
        return override.get(key, t.flag(key))

    parts = [short for key, short in FLAG_SHORT.items() if val(key)]
    if not val("enabled"):
        parts.insert(0, "disabled")
    return " ".join(parts)


class TracksPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("tracksPage")
        lay = page_layout(self, "Tracks")

        # ---------------- reference file
        ref_bar = QHBoxLayout()
        ref_bar.addWidget(BodyLabel("Reference file:", self))
        self.ref_combo = ComboBox(self)
        self.ref_combo.setMinimumWidth(380)
        ref_bar.addWidget(self.ref_combo, 1)
        self.btn_from_track = PushButton(FIF.ADD, "Rule from selected track", self)
        ref_bar.addWidget(self.btn_from_track)
        lay.addLayout(ref_bar)
        legend = CaptionLabel(
            "Bold = will change (old → new, details in the tooltip) · highlighted = matched by the selected rule",
            self,
        )
        lay.addWidget(legend)

        splitter = Splitter(Qt.Vertical, self)
        lay.addWidget(splitter, 1)

        self.ref_table = TableWidget(splitter)
        self.ref_table.setColumnCount(len(REF_COLUMNS))
        self.ref_table.setHorizontalHeaderLabels(REF_COLUMNS)
        self.ref_table.verticalHeader().hide()
        self.ref_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ref_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.ref_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ref_table.setBorderVisible(True)
        self.ref_table.setBorderRadius(8)
        self.ref_table.setWordWrap(False)
        h = self.ref_table.horizontalHeader()
        for c in range(len(REF_COLUMNS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_LANG, QHeaderView.Interactive)  # width set in _refresh_reference
        self.ref_table.setMinimumHeight(140)
        # item fonts don't inherit the Fluent font -> set it explicitly
        self._bold_font = getFont(13, QFont.DemiBold)

        # ---------------- bottom: rules + editor
        bottom = Splitter(Qt.Horizontal, splitter)

        left = QWidget(bottom)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("Rules", left))
        head.addStretch(1)
        self.btn_new = DropDownPushButton(FIF.ADD, "New", left)
        new_menu = RoundMenu(parent=self.btn_new)
        for tt in TrackType:
            act = Action(f"{tt.label} rule")
            act.triggered.connect(lambda _=False, t=tt: self._new_rule(TrackMatcher(track_type=t)))
            new_menu.addAction(act)
        new_menu.addSeparator()
        self.new_from_preset_menu = RoundMenu("From track preset", new_menu)
        new_menu.addMenu(self.new_from_preset_menu)
        self.btn_new.setMenu(new_menu)
        head.addWidget(self.btn_new)
        ll.addLayout(head)

        self.rule_list = RuleList(left)
        self.rule_list.setMinimumWidth(280)
        ll.addWidget(self.rule_list, 1)

        tools = QHBoxLayout()
        self.btn_up = ToolButton(FIF.UP, left)
        self.btn_down = ToolButton(FIF.DOWN, left)
        self.btn_dup = ToolButton(FIF.COPY, left)
        self.btn_del = ToolButton(FIF.DELETE, left)
        for b, tip in (
            (self.btn_up, "Move up within its track type (later rules override earlier ones)"),
            (self.btn_down, "Move down within its track type"),
            (self.btn_dup, "Duplicate"),
            (self.btn_del, "Delete"),
        ):
            b.setToolTip(tip)
            b.installEventFilter(ToolTipFilter(b))
            tools.addWidget(b)
        tools.addStretch(1)
        ll.addLayout(tools)
        hint = CaptionLabel(
            "On conflicts the later rule wins. Counter: files in which the rule finds a track.",
            left,
        )
        hint.setTextColor("#606060", "#a0a0a0")
        hint.setWordWrap(True)
        ll.addWidget(hint)

        right = QWidget(bottom)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        preset_bar = QHBoxLayout()
        preset_bar.addWidget(StrongBodyLabel("Track preset", right))
        self.track_preset_combo = ComboBox(right)
        self.track_preset_combo.setMinimumWidth(200)
        preset_bar.addWidget(self.track_preset_combo, 1)
        self.btn_apply_tp = DropDownPushButton(FIF.DOWNLOAD, "Apply", right)
        apply_menu = RoundMenu(parent=self.btn_apply_tp)
        a1 = Action("Apply actions only")
        a1.triggered.connect(lambda: self._apply_track_preset(False))
        a2 = Action("Apply actions + match")
        a2.triggered.connect(lambda: self._apply_track_preset(True))
        apply_menu.addActions([a1, a2])
        self.btn_apply_tp.setMenu(apply_menu)
        self.btn_overwrite_tp = ToolButton(FIF.SAVE, right)
        self.btn_overwrite_tp.setToolTip("Overwrite the selected track preset with the current rule")
        self.btn_save_tp = ToolButton(FIF.SAVE_AS, right)
        self.btn_save_tp.setToolTip("Save as new track preset...")
        preset_bar.addWidget(self.btn_apply_tp)
        for b in (self.btn_overwrite_tp, self.btn_save_tp):
            b.installEventFilter(ToolTipFilter(b))
            preset_bar.addWidget(b)
        rl.addLayout(preset_bar)

        scroll = SmoothScrollArea(right)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        self.editor = TrackRuleEditor(state.languages(), scroll, state.settings.dropdown_languages)
        self.editor.setStyleSheet("")
        scroll.setWidget(self.editor)
        rl.addWidget(scroll, 1)

        bottom.addWidget(left)
        bottom.addWidget(right)
        bottom.setStretchFactor(0, 1)
        bottom.setStretchFactor(1, 3)
        bottom.setSizes([340, 860])
        splitter.addWidget(self.ref_table)
        splitter.addWidget(bottom)
        splitter.setSizes([360, 490])

        # ---------------- signals
        self.ref_combo.currentIndexChanged.connect(lambda _: self._refresh_reference())
        self.btn_from_track.clicked.connect(self._rule_from_selected_track)
        self.ref_table.doubleClicked.connect(lambda _: self._rule_from_selected_track())
        self.rule_list.current_changed.connect(self._on_rule_selected)
        self.rule_list.rule_toggled.connect(self._on_rule_toggled)
        self.rule_list.rule_moved.connect(self._on_rule_moved)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_dup.clicked.connect(self._duplicate)
        self.btn_del.clicked.connect(self._delete)
        self.btn_save_tp.clicked.connect(self._save_track_preset)
        self.btn_overwrite_tp.clicked.connect(self._overwrite_track_preset)
        self.editor.changed.connect(self._on_editor_changed)
        state.files_changed.connect(self._refresh_ref_files)
        state.file_updated.connect(self._on_file_updated)
        state.preset_replaced.connect(self._reload_rules)
        state.presets_saved.connect(self._refresh_track_presets)
        state.tools_changed.connect(self._update_languages)
        state.settings_changed.connect(self._update_languages)
        # files arrive one by one while they are read; count the hits once things have settled
        self._hits_timer = QTimer(self)
        self._hits_timer.setSingleShot(True)
        self._hits_timer.setInterval(200)
        self._hits_timer.timeout.connect(self._show_rules)
        state.files_changed.connect(self._hits_timer.start)
        state.file_updated.connect(lambda _: self._hits_timer.start())

        self._refresh_ref_files()
        self._refresh_track_presets()
        self._reload_rules()

    # ------------------------------------------------------------------ helpers
    def _update_languages(self):
        self.editor.set_languages(self.state.languages(), self.state.settings.dropdown_languages)

    @property
    def rules(self) -> list[TrackRule]:
        return self.state.preset.rules

    def _rule(self, rule_id: str) -> TrackRule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def _current_rule(self) -> TrackRule | None:
        return self._rule(self.rule_list.current_id())

    def _index(self, rule: TrackRule) -> int:
        return next(i for i, r in enumerate(self.rules) if r.id == rule.id)

    def _ref_file(self):
        path = self.ref_combo.currentData()
        return next((f for f in self.state.files if f.path == path and not f.error), None)

    def _toast(self, title: str, text: str = "", error: bool = False):
        (InfoBar.error if error else InfoBar.success)(title, text, duration=2500, parent=self.window())

    # ------------------------------------------------------------------ reference file
    def _refresh_ref_files(self):
        cur = self.ref_combo.currentData()
        self.ref_combo.blockSignals(True)
        self.ref_combo.clear()
        for f in self.state.files:
            self.ref_combo.addItem(Path(f.path).name, userData=f.path)
        idx = self.ref_combo.findData(cur) if cur else -1
        self.ref_combo.setCurrentIndex(idx if idx >= 0 else (0 if self.state.files else -1))
        self.ref_combo.blockSignals(False)
        self._refresh_reference()

    def _on_file_updated(self, path: str):
        if path == self.ref_combo.currentData():
            self._refresh_reference()

    def _refresh_reference(self):
        f = self._ref_file()
        tracks = f.tracks if f else []
        changes: dict[str, dict[str, tuple[str, str]]] = {}  # track -> field -> (old, new)
        if f:
            ready = self.state.ready_files()
            index = next((i for i, x in enumerate(ready) if x.path == f.path), 0)
            plan = plan_file(f, self.state.preset, index, self.state.settings.only_changes)
            for ch in plan.changes:
                changes.setdefault(ch.scope, {})[ch.field] = (ch.old, ch.new)
        current = self._current_rule()
        hits = {t.id for t in matching_tracks(current, f)} if (f and current) else set()
        highlight = QBrush(QColor(0, 120, 212, 70 if isDarkTheme() else 40))
        accent = QColor("#60cdff") if isDarkTheme() else QColor("#005fb8")
        self.ref_table.setRowCount(len(tracks))
        for r, t in enumerate(tracks):
            ch = changes.get(t.describe(), {})
            cells = [t.type.label, str(t.index_in_type), t.lang_display, t.codec, t.name, flags_text(t)]
            tips = list(cells)
            changed: set[int] = set()

            if FIELD_LANGUAGE in ch:
                old, new = ch[FIELD_LANGUAGE]
                cells[COL_LANG] = f"{old}{ARROW}{new}"
                tips[COL_LANG] = f"Old: {old}\nNew: {new}"
                changed.add(COL_LANG)
            if FIELD_NAME in ch:
                old, new = ch[FIELD_NAME]
                cells[COL_NAME] = f"{old or '–'}{ARROW}{new}"
                tips[COL_NAME] = f"Old: {old or '(empty)'}\nNew: {new}"
                changed.add(COL_NAME)
            override = {FLAG_BY_LABEL[k]: v[1] == YES for k, v in ch.items() if k in FLAG_BY_LABEL}
            if override:
                old, new = flags_text(t), flags_text(t, override)
                cells[COL_FLAGS] = f"{old or '–'}{ARROW}{new or '–'}"
                tips[COL_FLAGS] = "\n".join(
                    f"{k}: {v[0]} → {v[1]}" for k, v in ch.items() if k in FLAG_BY_LABEL
                )
                changed.add(COL_FLAGS)
            if FIELD_EXTRA in ch:
                cells[COL_FLAGS] = (cells[COL_FLAGS] + "  + Extra").strip()
                tips[COL_FLAGS] = (tips[COL_FLAGS] + "\nExtra parameters: " + ch[FIELD_EXTRA][1]).strip()
                changed.add(COL_FLAGS)

            for c, v in enumerate(cells):
                item = QTableWidgetItem(v)
                item.setToolTip(tips[c])
                if t.id in hits:
                    item.setBackground(highlight)
                if c in changed:
                    item.setFont(self._bold_font)
                    item.setForeground(accent)
                self.ref_table.setItem(r, c, item)
        # ResizeToContents ignores the header text when the values are short ("und", "ger")
        header_width = self.ref_table.horizontalHeader().fontMetrics().horizontalAdvance(REF_COLUMNS[COL_LANG]) + 48
        self.ref_table.setColumnWidth(COL_LANG, max(self.ref_table.sizeHintForColumn(COL_LANG) + 16, header_width))
        self._update_match_info()

    def _update_match_info(self):
        rule = self._current_rule()
        if not rule:
            self.editor.set_match_info("")
            self.editor.set_result("")
            return
        files = [f for f in self.state.ready_files() if not f.error]
        n = sum(1 for f in files if matching_tracks(rule, f))
        text = f"Matches in {n} of {len(files)} file(s)."
        ref = self._ref_file()
        if ref:
            hits = matching_tracks(rule, ref)
            text += " Reference: " + ("; ".join(t.describe() for t in hits) if hits else "no track")
        self.editor.set_match_info(text)
        self.editor.set_result(self._rule_result(rule, ref))

    def _rule_result(self, rule: TrackRule, ref) -> str:
        """What the selected rule on its own changes in the reference file."""
        if not ref or rule.actions.is_empty():
            return ""
        head = "In the reference file: "
        if not rule.enabled:
            return head + "nothing, the rule is switched off."
        ready = self.state.ready_files()
        index = next((i for i, x in enumerate(ready) if x.path == ref.path), 0)
        general = self.state.preset.general
        alone = GlobalPreset(
            general=GeneralSettings(num_start=general.num_start, num_padding=general.num_padding), rules=[rule]
        )
        plan = plan_file(ref, alone, index, self.state.settings.only_changes)
        by_track: dict[str, list[str]] = {}
        for ch in plan.changes:
            if ch.field == FIELD_EXTRA:
                part = f"extra parameters {ch.new}"
            elif ch.field == FIELD_NAME:
                part = f'name "{ch.old}" → "{ch.new}"' if ch.old else f'name → "{ch.new}"'
            else:
                part = f"{ch.field.lower()} {ch.old} → {ch.new}"
            by_track.setdefault(ch.scope, []).append(part)
        warnings = [f"⚠ {w}" for w in plan.warnings if "matches no track" not in w]
        if by_track:
            lines = [f"{scope}:  {', '.join(parts)}" for scope, parts in by_track.items()]
            return "\n".join([head.rstrip(), *lines, *warnings])
        if not matching_tracks(rule, ref):
            return "\n".join([head + "no track matches.", *warnings])
        return "\n".join([head + "already as wanted, nothing to change.", *warnings])

    # ------------------------------------------------------------------ rule list
    def _hits(self) -> dict[str, tuple[int, int]]:
        """Rule id -> (files in which the rule finds a track, files)."""
        files = [f for f in self.state.ready_files() if not f.error]
        if not files:
            return {}
        return {r.id: (sum(1 for f in files if matching_tracks(r, f)), len(files)) for r in self.rules}

    def _show_rules(self):
        self.rule_list.set_rules(self.rules, self._hits())

    def _reload_rules(self, select: str | None = None):
        """Rebuilds the list and the editor; `select` is the id of the rule to select."""
        self._show_rules()
        wanted = select or self.rule_list.current_id() or self.rule_list.first_id()
        self.rule_list.set_current(wanted, notify=False)
        self._on_rule_selected()

    def _on_rule_selected(self, *_):
        self.editor.load(self._current_rule())
        self._update_track_preset_buttons()
        self._refresh_reference()

    def _on_rule_toggled(self, rule_id: str, enabled: bool):
        rule = self._rule(rule_id)
        if rule and rule.enabled != enabled:
            rule.enabled = enabled
            self._changed()

    def _on_editor_changed(self):
        self._changed()

    def _changed(self):
        self.state.mark_dirty()
        self._show_rules()
        self._refresh_reference()

    def _new_rule(self, matcher: TrackMatcher, actions=None, label: str = ""):
        rule = TrackRule(matcher=matcher, label=label)
        if actions is not None:
            rule.actions = actions.model_copy(deep=True)
        self.rules.append(rule)
        self._reload_rules(select=rule.id)
        self.state.mark_dirty()

    def _rule_from_selected_track(self):
        f = self._ref_file()
        rows = {i.row() for i in self.ref_table.selectedIndexes()}
        if not f or not rows:
            self._toast("No track selected", "Select a track in the reference file first.", error=True)
            return
        t = f.tracks[min(rows)]
        same_lang = [x for x in f.tracks_of(t.type) if x.language == t.language]
        matcher = TrackMatcher(track_type=t.type)
        if t.language and t.language != "und":
            matcher.languages = [t.language]
        if len(same_lang) > 1 or not matcher.languages:
            # language alone is ambiguous -> use the name or the position
            if t.name and sum(1 for x in same_lang if x.name == t.name) == 1:
                matcher.name_regex = "^" + re.escape(t.name) + "$"
            else:
                matcher.positions = [t.index_in_type]
        self._new_rule(matcher)

    def _reorder(self, rule: TrackRule, position: int) -> None:
        """Puts the rule at `position` among the rules of its track type; all other types stay where they are."""
        slots = [i for i, r in enumerate(self.rules) if r.matcher.track_type == rule.matcher.track_type]
        order = [self.rules[i] for i in slots if self.rules[i].id != rule.id]
        order.insert(min(max(position, 0), len(order)), rule)
        if [r.id for r in order] == [self.rules[i].id for i in slots]:
            return
        for i, r in zip(slots, order):
            self.rules[i] = r
        self._reload_rules(select=rule.id)
        self.state.mark_dirty()

    def _move(self, delta: int):
        """Moves the rule one step among the rules of its track type."""
        rule = self._current_rule()
        if rule:
            same = [r.id for r in self.rules if r.matcher.track_type == rule.matcher.track_type]
            self._reorder(rule, same.index(rule.id) + delta)

    def _on_rule_moved(self, rule_id: str, before_id: str):
        """A rule was dragged in front of `before_id` ("" = to the end of its track type)."""
        rule = self._rule(rule_id)
        if not rule:
            return
        others = [
            r.id for r in self.rules if r.matcher.track_type == rule.matcher.track_type and r.id != rule_id
        ]
        self._reorder(rule, others.index(before_id) if before_id in others else len(others))

    def _duplicate(self):
        rule = self._current_rule()
        if rule:
            copy = rule.model_copy(deep=True)
            copy.id = TrackRule(matcher=rule.matcher).id
            self.rules.insert(self._index(rule) + 1, copy)
            self._reload_rules(select=copy.id)
            self.state.mark_dirty()

    def _delete(self):
        rule = self._current_rule()
        if rule:
            neighbour = self.rule_list.neighbour_id(rule.id)
            del self.rules[self._index(rule)]
            self._reload_rules(select=neighbour)
            self.state.mark_dirty()

    # ------------------------------------------------------------------ track presets
    def _refresh_track_presets(self):
        presets = self.state.store.list_track()
        cur = self.track_preset_combo.currentText()
        self.track_preset_combo.clear()
        for p in presets:
            self.track_preset_combo.addItem(p.name, userData=p.name)
        idx = self.track_preset_combo.findText(cur)
        if idx >= 0:
            self.track_preset_combo.setCurrentIndex(idx)
        self._update_track_preset_buttons()
        self.new_from_preset_menu.clear()
        for p in presets:
            act = Action(p.name)
            act.triggered.connect(lambda _=False, name=p.name: self._new_rule_from_preset(name))
            self.new_from_preset_menu.addAction(act)
        self.new_from_preset_menu.setEnabled(bool(presets))

    def _update_track_preset_buttons(self):
        has_preset = self.track_preset_combo.count() > 0
        has_rule = self._current_rule() is not None
        self.btn_apply_tp.setEnabled(has_preset and has_rule)
        self.btn_overwrite_tp.setEnabled(has_preset and has_rule)
        self.btn_save_tp.setEnabled(has_rule)

    def _overwrite_track_preset(self):
        rule = self._current_rule()
        name = self.track_preset_combo.currentData()
        if not rule or not name:
            return
        old = self._load_track_preset(name)
        if not old:
            return
        # whether the match is stored stays the same as in the existing preset
        with_matcher = old.matcher is not None
        tp = TrackPreset(
            name=old.name,
            actions=rule.actions.model_copy(deep=True),
            matcher=rule.matcher.model_copy(deep=True) if with_matcher else None,
        )
        self.state.store.save_track(tp)
        self.state.presets_saved.emit()
        detail = "actions + match" if with_matcher else "actions only"
        self._toast("Track preset overwritten", f"\"{old.name}\" ({detail})")

    def _load_track_preset(self, name: str) -> TrackPreset | None:
        try:
            return self.state.store.load_track(name)
        except Exception as e:  # noqa: BLE001
            self._toast("Could not load track preset", str(e), error=True)
            return None

    def _apply_track_preset(self, with_matcher: bool):
        rule = self._current_rule()
        name = self.track_preset_combo.currentData()
        if not rule or not name:
            self._toast("No rule selected", "Select or create a rule on the left first.", error=True)
            return
        tp = self._load_track_preset(name)
        if not tp:
            return
        rule.actions = tp.actions.model_copy(deep=True)
        if with_matcher and tp.matcher:
            rule.matcher = tp.matcher.model_copy(deep=True)
        self._reload_rules()
        self.state.mark_dirty()
        self._toast("Track preset applied", tp.name)

    def _new_rule_from_preset(self, name: str):
        tp = self._load_track_preset(name)
        if not tp:
            return
        ref = self._current_rule()
        matcher = tp.matcher or TrackMatcher(track_type=ref.matcher.track_type if ref else TrackType.AUDIO)
        self._new_rule(matcher.model_copy(deep=True), tp.actions, label=tp.name)

    def _save_track_preset(self):
        rule = self._current_rule()
        if not rule:
            self._toast("No rule selected", error=True)
            return
        name = TextInputDialog.ask_with_check(
            self.window(),
            "Save as track preset",
            "Name of the track preset (an existing name is overwritten):",
            rule.label or self.track_preset_combo.currentText(),
            "Also store the match (which track)",
        )
        if not name:
            return
        text, with_matcher = name
        tp = TrackPreset(
            name=text,
            actions=rule.actions.model_copy(deep=True),
            matcher=rule.matcher.model_copy(deep=True) if with_matcher else None,
        )
        self.state.store.save_track(tp)
        self.state.presets_saved.emit()
        idx = self.track_preset_combo.findText(text)
        if idx >= 0:
            self.track_preset_combo.setCurrentIndex(idx)
        self._toast("Track preset saved", text)
