"""Rule list of the Tracks page: grouped by track type, every rule as a row with chips and a hit counter."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CheckBox, SmoothScrollArea, getFont, isDarkTheme, qconfig

from ..core.models import TrackRule, TrackType
from ..core.summary import action_chips, match_chips
from .widgets.common import Chip, FlowLayout

RULE_MIME = "application/x-pybatchmkvpropedit-rule"  # carries the id of the rule that is being dragged


class RuleRow(QWidget):
    """One rule: checkbox, title, chips (what it matches / what it changes) and "matched in n of m files"."""

    clicked = Signal(str)
    toggled = Signal(str, bool)

    def __init__(self, rule: TrackRule, parent=None):
        super().__init__(parent)
        self.rule_id = rule.id
        self._selected = False
        self._hover = False
        self._press_pos: QPoint | None = None
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 5)
        lay.setSpacing(4)
        self.check = CheckBox(self)
        self.check.setToolTip("Rule is active")
        lay.addWidget(self.check, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setContentsMargins(0, 1, 0, 0)
        mid.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = BodyLabel("", self)
        self.title.setTextFormat(Qt.PlainText)
        self.title.setFont(getFont(13))
        self.title.setMinimumWidth(40)
        self.hits = Chip("", "off", self)
        head.addWidget(self.title, 1)
        head.addWidget(self.hits, 0, Qt.AlignTop)
        mid.addLayout(head)
        self.chips = FlowLayout(h_spacing=3, v_spacing=3)
        mid.addLayout(self.chips)
        lay.addLayout(mid, 1)

        self.check.stateChanged.connect(self._on_check)

    def _on_check(self, *_):
        self.toggled.emit(self.rule_id, self.check.isChecked())

    def update_rule(self, rule: TrackRule, number: int, hits: tuple[int, int] | None) -> None:
        """`number` counts within the track type; `hits` is (files with a match, files) or None without files."""
        self.check.blockSignals(True)
        self.check.setChecked(rule.enabled)
        self.check.blockSignals(False)

        title = rule.label or f"{rule.matcher.track_type.label} rule {number}"
        self.title.setText(title)
        self.title.setToolTip(title)
        self.title.setTextColor(*(("#1b1b1b", "#ffffff") if rule.enabled else ("#9a9a9a", "#7d7d7d")))

        while self.chips.count():
            old = self.chips.takeAt(0).widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
        actions = action_chips(rule.actions)
        for text in match_chips(rule.matcher):
            self.chips.addWidget(Chip(text, "match" if rule.enabled else "off", self))
        for text in actions or ["no changes"]:
            self.chips.addWidget(Chip(text, "action" if rule.enabled and actions else "off", self))
        self.chips.invalidate()

        if not rule.enabled:
            self.hits.setText("off")
            self.hits.setKind("off")
            self.hits.setToolTip("This rule is switched off.")
        elif hits is None:
            self.hits.setText("")
        else:
            n, total = hits
            self.hits.setText(f"{n}/{total}")
            self.hits.setKind("off" if n == total else "warn")
            self.hits.setToolTip(
                f"Matches a track in {n} of {total} file(s)."
                + ("" if n == total else " The other files are built differently.")
            )
        self.hits.setVisible(bool(self.hits.text()))
        for chip in self.findChildren(Chip):
            if chip is not self.hits:
                chip.show()
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()

    def setSelected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    # ------------------------------------------------------------------ events
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position().toPoint()
            self.clicked.emit(self.rule_id)
            e.accept()  # the row handles it; the following moves decide whether this becomes a drag
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """Dragging a row starts moving the rule; the list shows where it would land."""
        pressed = self._press_pos
        if (
            pressed is not None
            and e.buttons() & Qt.LeftButton
            and (e.position().toPoint() - pressed).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._press_pos = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(RULE_MIME, self.rule_id.encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(pressed)
            drag.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_pos = None
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        if not (self._selected or self._hover):
            return
        dark = isDarkTheme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self._selected:
            p.setBrush(QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 16))
        else:
            p.setBrush(QColor(255, 255, 255, 12) if dark else QColor(0, 0, 0, 8))
        p.drawRoundedRect(self.rect().adjusted(0, 1, 0, -1), 6, 6)
        if self._selected:  # accent bar like in the navigation
            p.setBrush(QColor("#60cdff") if dark else QColor("#005fb8"))
            p.drawRoundedRect(0, 8, 3, self.height() - 16, 1.5, 1.5)
        p.end()


class RuleList(SmoothScrollArea):
    """All rules, grouped by track type. Rules keep their order within a type (later rules win)."""

    current_changed = Signal(str)  # rule id, "" if nothing is selected
    rule_toggled = Signal(str, bool)
    rule_moved = Signal(str, str)  # dragged rule id, id of the rule it goes in front of ("" = end of its type)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFocusPolicy(Qt.StrongFocus)
        self.view = QWidget(self)
        self.view.setStyleSheet("")
        self.body = QVBoxLayout(self.view)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(0)
        self.setWidget(self.view)

        self.rows: dict[str, RuleRow] = {}
        self._order: list[str] = []  # rule ids in display order
        self._layout_key: list[tuple[str, TrackType]] = []
        self._current = ""
        self.empty_hint = CaptionLabel(
            "No rules yet. Select a track in the table above and click \"Rule from selected track\", "
            "or use \"New\".",
            self.view,
        )
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setTextColor("#606060", "#a0a0a0")
        qconfig.themeChanged.connect(lambda *_: self.view.update())

        # dragging a row: the line shows where the rule would be inserted
        self.drop_line = QFrame(self.view)
        self.drop_line.setFixedHeight(2)
        self.drop_line.hide()
        self.view.setAcceptDrops(True)
        self.view.installEventFilter(self)

    # ------------------------------------------------------------------ content
    def current_id(self) -> str:
        return self._current

    def set_rules(self, rules: list[TrackRule], hits: dict[str, tuple[int, int]] | None = None) -> None:
        """Shows `rules`; rows are reused as long as the grouping has not changed."""
        hits = hits or {}
        groups = {tt: [r for r in rules if r.matcher.track_type == tt] for tt in TrackType}
        key = [(r.id, tt) for tt, rs in groups.items() for r in rs]
        if key != self._layout_key:
            self._rebuild(groups)
            self._layout_key = key
        for rs in groups.values():
            for number, rule in enumerate(rs, start=1):
                self.rows[rule.id].update_rule(rule, number, hits.get(rule.id))
        if self._current not in self.rows:
            self._current = ""
        for rule_id, row in self.rows.items():
            row.setSelected(rule_id == self._current)

    def _rebuild(self, groups: dict[TrackType, list[TrackRule]]) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            w = item.widget()
            if w is not None and w is not self.empty_hint:
                w.deleteLater()
        self.rows = {}
        self._order = []
        for tt, rules in groups.items():
            if not rules:
                continue
            header = CaptionLabel(tt.label, self.view)
            header.setTextColor("#606060", "#a0a0a0")
            header.setContentsMargins(8, 6 if self._order else 0, 0, 1)
            self.body.addWidget(header)
            for rule in rules:
                row = RuleRow(rule, self.view)
                row.clicked.connect(self.set_current)
                row.toggled.connect(self.rule_toggled)
                self.body.addWidget(row)
                self.rows[rule.id] = row
                self._order.append(rule.id)
        self.empty_hint.setVisible(not self._order)
        if not self._order:
            self.body.addWidget(self.empty_hint)
        self.body.addStretch(1)

    def first_id(self) -> str:
        return self._order[0] if self._order else ""

    def neighbour_id(self, rule_id: str) -> str:
        """The rule to select once `rule_id` is gone: the next one, otherwise the previous one."""
        if rule_id not in self._order:
            return ""
        i = self._order.index(rule_id)
        rest = self._order[i + 1 : i + 2] or self._order[max(i - 1, 0) : i]
        return rest[0] if rest else ""

    def set_current(self, rule_id: str, notify: bool = True) -> None:
        if rule_id not in self.rows:
            rule_id = ""
        changed = rule_id != self._current
        self._current = rule_id
        for rid, row in self.rows.items():
            row.setSelected(rid == rule_id)
        if rule_id:
            self.ensureWidgetVisible(self.rows[rule_id], 0, 12)
        if changed and notify:
            self.current_changed.emit(rule_id)

    # ------------------------------------------------------------------ drag & drop
    def drop_target(self, rule_id: str, y: int) -> tuple[str, int] | None:
        """Where a rule dropped at height `y` goes: (id of the rule after it or "", height of the line).

        A rule stays within its track type, so only the rows of that type count.
        """
        rule_type = dict(self._layout_key).get(rule_id)
        same = [rid for rid, tt in self._layout_key if tt == rule_type]
        if not same:
            return None
        for rid in same:
            geometry = self.rows[rid].geometry()
            if y < geometry.center().y():
                if rid == rule_id:  # dropped on itself: stays in front of the rule that follows it
                    following = same[same.index(rid) + 1 :]
                    return (following[0] if following else ""), geometry.top()
                return rid, geometry.top()
        return "", self.rows[same[-1]].geometry().bottom() + 1

    def eventFilter(self, obj, e):
        # the scroll area installs filters of its own while it is being set up, before self.view exists
        drag_events = (QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop)
        if e.type() in drag_events and obj is getattr(self, "view", None):
            if e.type() == QEvent.DragLeave:
                self.drop_line.hide()
                return True
            mime = e.mimeData()
            rule_id = bytes(mime.data(RULE_MIME)).decode() if mime.hasFormat(RULE_MIME) else ""
            target = self.drop_target(rule_id, e.position().toPoint().y())
            if target is None:
                self.drop_line.hide()
                e.ignore()
                return True
            before_id, y = target
            e.setDropAction(Qt.MoveAction)
            e.accept()
            if e.type() == QEvent.Drop:
                self.drop_line.hide()
                self.rule_moved.emit(rule_id, before_id)
            else:
                color = "#60cdff" if isDarkTheme() else "#005fb8"
                self.drop_line.setStyleSheet(f"background: {color}; border: none;")
                self.drop_line.setGeometry(8, y - 1, max(self.view.width() - 24, 20), 2)
                self.drop_line.show()
                self.drop_line.raise_()
            return True
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------------ keyboard
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down) and self._order:
            step = -1 if e.key() == Qt.Key_Up else 1
            i = self._order.index(self._current) + step if self._current in self._order else 0
            self.set_current(self._order[min(max(i, 0), len(self._order) - 1)])
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        self.setFocus()
        super().mousePressEvent(e)
