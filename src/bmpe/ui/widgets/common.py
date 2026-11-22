"""Reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QDir, QPoint, QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    InfoBar,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    SegmentedWidget,
    SimpleCardWidget,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    getFont,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from ...core.languages import Language, pick_languages, search_languages
from ...core.models import TriState


class TriStateWidget(SegmentedWidget):
    """Unchanged / Yes / No."""

    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._silent = False
        for state, text in ((TriState.UNCHANGED, "–"), (TriState.YES, "Yes"), (TriState.NO, "No")):
            self.addItem(state.value, text)
        self.setCurrentItem(TriState.UNCHANGED.value)
        self.currentItemChanged.connect(self._emit)
        self.setFixedWidth(200)

    def _emit(self, key: str) -> None:
        if not self._silent:
            self.changed.emit(TriState(key))

    def value(self) -> TriState:
        return TriState(self.currentRouteKey())

    def setValue(self, state: TriState) -> None:
        self._silent = True
        self.setCurrentItem(TriState(state).value)
        self._silent = False


class FlowLayout(QLayout):
    """Lays its widgets out in rows and wraps to the next row when the width is used up."""

    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h, self._v = h_spacing, v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():  # hidden widget
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, row_height = area.x(), y + row_height + self._v, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + m.bottom()


class Chip(QLabel):
    """Small rounded label. kind: "match" (neutral), "action" (accent), "warn" or "off" (muted)."""

    # kind -> (light background RGBA, light text, dark background RGBA, dark text)
    COLORS = {
        "match": ((0, 0, 0, 15), "#5c5c5c", (255, 255, 255, 20), "#c8c8c8"),
        "action": ((0, 95, 184, 31), "#005a9e", (96, 205, 255, 46), "#8fd8ff"),
        "warn": ((194, 124, 14, 46), "#8a5700", (252, 225, 0, 51), "#ffd866"),
        "off": ((0, 0, 0, 10), "#9a9a9a", (255, 255, 255, 13), "#7d7d7d"),
    }

    def __init__(self, text: str, kind: str = "match", parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self.setFont(getFont(11))
        self.setContentsMargins(6, 1, 6, 1)
        self.setTextFormat(Qt.PlainText)

    def setKind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, e):
        light_bg, light_fg, dark_bg, dark_fg = self.COLORS.get(self.kind, self.COLORS["match"])
        bg, fg = (dark_bg, dark_fg) if isDarkTheme() else (light_bg, light_fg)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*bg))
        p.drawRoundedRect(self.rect(), 5, 5)
        p.setPen(QColor(fg))
        p.setFont(self.font())
        p.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class Splitter(QSplitter):
    """QSplitter with an invisible handle (the native Windows style paints it light grey/white)."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(10)
        self.setStyleSheet(
            "QSplitter { background: transparent; }"
            "QSplitter::handle { background: transparent; }"
            "QSplitter::handle:hover { background: rgba(128, 128, 128, 45); border-radius: 3px; }"
        )


class IntSpin(SpinBox):
    """SpinBox with a workaround: on Qt 6.12 the inner text field otherwise ends up 1 px wide."""

    def __init__(self, parent=None, width: int = 150):
        super().__init__(parent)
        self.setFixedWidth(width)
        self._fix()

    def _fix(self):
        self.lineEdit().setMinimumWidth(max(30, self.width() - 80))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fix()


class OptionalBoolCombo(ComboBox):
    """any / yes / no -> None / True / False."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItem("any", userData=None)
        self.addItem("yes", userData=True)
        self.addItem("no", userData=False)

    def value(self) -> bool | None:
        return [None, True, False][max(self.currentIndex(), 0)]

    def setValue(self, v: bool | None) -> None:
        self.setCurrentIndex({None: 0, True: 1, False: 2}[v])


class EnumCombo(ComboBox):
    """ComboBox with (value, text) pairs."""

    def __init__(self, items: list[tuple[object, str]], parent=None):
        super().__init__(parent)
        self._values = [v for v, _ in items]
        for _, text in items:
            self.addItem(text)

    def value(self):
        i = self.currentIndex()
        return self._values[i] if 0 <= i < len(self._values) else self._values[0]

    def setValue(self, v) -> None:
        if v in self._values:
            self.setCurrentIndex(self._values.index(v))

    def fit_to_items(self) -> EnumCombo:
        """Fixed width that fits the longest entry, for choices whose texts never change."""
        self.ensurePolished()
        fm = self.fontMetrics()
        padding = self.sizeHint().width() - fm.horizontalAdvance(self.text())  # margins and arrow
        widest = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.setFixedWidth(widest + padding)
        return self


class LanguageCombo(EditableComboBox):
    """Language picker.

    The dropdown only offers a short list (building a menu with every language takes seconds). Typing finds
    all languages by code or name, and free IETF tags such as de-DE or pt-BR are accepted as they are.
    """

    MAX_SUGGESTIONS = 15

    def __init__(self, languages: list[Language], parent=None, shortlist: list[str] | None = None):
        super().__init__(parent)
        self._langs: list[Language] = []
        self._shortlist: list[str] | None = None
        self._by_display: dict[str, str] = {}
        self._suggestions = QStringListModel(self)
        completer = QCompleter(self._suggestions, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setMaxVisibleItems(12)
        self.setCompleter(completer)
        self.textEdited.connect(self._suggest)
        self.setPlaceholderText("code or name, e.g. ger, de-DE")
        self.setLanguages(languages, shortlist)

    def setLanguages(self, languages: list[Language], shortlist: list[str] | None = None) -> None:
        """`shortlist`: codes for the dropdown; None offers every language (slow with the full list)."""
        if languages is self._langs and shortlist == self._shortlist and self._by_display:
            return
        cur = self.code()
        self._langs = languages
        self._shortlist = list(shortlist) if shortlist is not None else None
        if shortlist is None:
            entries = [(l.display, l.code) for l in languages]
        else:
            entries = pick_languages(languages, shortlist)
        self._by_display = {l.display: l.code for l in languages}
        self._by_display.update(dict(entries))
        self.blockSignals(True)
        self.clear()
        self.addItems([display for display, _ in entries])
        self.blockSignals(False)
        self.setCode(cur)

    def _suggest(self, text: str) -> None:
        """Typed text: offer the best matches out of all languages, not hundreds of them."""
        matches = search_languages(self._langs, text, self.MAX_SUGGESTIONS)
        self._suggestions.setStringList([l.display for l in matches])
        self.completer().setCompletionPrefix(text)

    def code(self) -> str:
        text = self.text().strip()
        if text in self._by_display:
            return self._by_display[text]
        if "(" in text and text.endswith(")"):
            return text[text.rfind("(") + 1 : -1].split(",")[0].strip()
        return text

    def setCode(self, code: str | None) -> None:
        self.blockSignals(True)
        code = (code or "").strip()
        match = next((l for l in getattr(self, "_langs", []) if l.code == code or (l.iso1 and l.iso1 == code)), None)
        if match and match.code == code:
            self.setText(match.display)
        else:
            self.setText(code)
        self.blockSignals(False)


class PathEdit(QWidget):
    """Row with a LineEdit and a browse button."""

    changed = Signal(str)

    def __init__(self, mode: str = "file", file_filter: str = "All files (*)", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.file_filter = file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = LineEdit(self)
        self.edit.setClearButtonEnabled(True)
        self.btn = ToolButton(FIF.FOLDER, self)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(self._browse)
        self.edit.textChanged.connect(self.changed)

    def _browse(self) -> None:
        if self.mode == "dir":
            path = QFileDialog.getExistingDirectory(self, "Choose folder", self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(), self.file_filter)
        if path:
            self.edit.setText(QDir.toNativeSeparators(path))

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, text: str) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(text)
        self.edit.blockSignals(False)


class Card(SimpleCardWidget):
    """Card with a heading and form rows."""

    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(20, 16, 20, 16)
        self.vbox.setSpacing(10)
        self.vbox.addWidget(StrongBodyLabel(title, self))
        if description:
            d = CaptionLabel(description, self)
            d.setWordWrap(True)
            d.setTextColor("#606060", "#a0a0a0")
            self.vbox.addWidget(d)

    def addRow(self, label: str, widget: QWidget, stretch: bool = True, label_width: int = 150) -> QWidget:
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lbl = BodyLabel(label, row)
        lbl.setFixedWidth(label_width)
        lay.addWidget(lbl)
        lay.addWidget(widget, 1 if stretch else 0)
        if not stretch:
            lay.addStretch(1)
        self.vbox.addWidget(row)
        return row

    def addWidget(self, widget: QWidget) -> None:
        self.vbox.addWidget(widget)


class ScrollPage(SmoothScrollArea):
    """Scrollable page with a title; content goes into self.body (QVBoxLayout)."""

    def __init__(self, title: str, object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.body = QVBoxLayout(self.view)
        self.body.setContentsMargins(28, 20, 28, 28)
        self.body.setSpacing(14)
        self.body.addWidget(SubtitleLabel(title, self.view))
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("SmoothScrollArea, #view { background: transparent; border: none; }")


def page_layout(w: QWidget, title: str | None = None) -> QVBoxLayout:
    lay = QVBoxLayout(w)
    lay.setContentsMargins(28, 20, 28, 20)
    lay.setSpacing(12)
    if title:
        lay.addWidget(SubtitleLabel(title, w))
    return lay


def plain_text(*labels: QLabel) -> None:
    """Shows the text as it is. Qt would otherwise render text that looks like HTML, and names of files and
    tracks come from outside the program."""
    for label in labels:
        label.setTextFormat(Qt.PlainText)


def toast(kind: str, title: str, content: str = "", **kw) -> InfoBar:
    """InfoBar.success / .error / .warning / .info with title and text shown as plain text."""
    bar = getattr(InfoBar, kind)(title, content, **kw)
    plain_text(bar.titleLabel, bar.contentLabel)
    return bar


def message_box(title: str, content: str, parent) -> MessageBox:
    """MessageBox with title and text shown as plain text."""
    box = MessageBox(title, content, parent)
    plain_text(box.titleLabel, box.contentLabel)
    return box


class TextInputDialog(MessageBoxBase):
    def __init__(self, title: str, label: str, text: str = "", parent=None, checkbox: str = "", checked=False):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        if label:
            lbl = BodyLabel(label, self)
            lbl.setWordWrap(True)
            self.viewLayout.addWidget(lbl)
        self.edit = LineEdit(self)
        self.edit.setText(text)
        self.edit.selectAll()
        self.viewLayout.addWidget(self.edit)
        self.check = None
        if checkbox:
            self.check = CheckBox(checkbox, self)
            self.check.setChecked(checked)
            self.viewLayout.addWidget(self.check)
        self.yesButton.setText("OK")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(380)
        self.edit.textChanged.connect(lambda t: self.yesButton.setEnabled(bool(t.strip())))
        self.yesButton.setEnabled(bool(text.strip()))

    @staticmethod
    def ask(parent, title: str, label: str = "", text: str = "") -> str | None:
        dlg = TextInputDialog(title, label, text, parent)
        if dlg.exec():
            return dlg.edit.text().strip()
        return None

    @staticmethod
    def ask_with_check(parent, title: str, label: str, text: str, checkbox: str, checked=False):
        dlg = TextInputDialog(title, label, text, parent, checkbox=checkbox, checked=checked)
        if dlg.exec():
            return dlg.edit.text().strip(), dlg.check.isChecked()
        return None
