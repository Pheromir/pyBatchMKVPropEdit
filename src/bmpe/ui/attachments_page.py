"""Attachments page: add, replace, delete (the same for all files)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, Qt
from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import Action, DropDownPushButton, PushButton, RoundMenu, TableWidget
from qfluentwidgets import FluentIcon as FIF

from ..core.models import AttachmentAdd, AttachmentDelete, AttachmentReplace, AttachmentSelector
from .state import AppState
from .widgets.common import Card, EnumCombo, ScrollPage

SELECTOR_ITEMS = [(s, s.label) for s in AttachmentSelector]
FONT_MIMES = [
    "font/ttf",
    "font/otf",
    "font/collection",
    "application/x-truetype-font",
    "application/vnd.ms-opentype",
    "application/x-font-ttf",
    "application/x-font-otf",
]


def guess_mime(path: str) -> str:
    return {
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".ttc": "font/collection",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".xml": "text/xml",
        ".txt": "text/plain",
    }.get(Path(path).suffix.lower(), "")


class EditTable(TableWidget):
    """Table with editable cells; column `selector_col` is a combo box."""

    def __init__(self, headers: list[str], selector_col: int | None, readonly_cols: set[int], on_change, parent):
        super().__init__(parent)
        self.selector_col = selector_col
        self.readonly_cols = readonly_cols
        self.on_change = on_change
        self._loading = False
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().hide()
        self.setBorderVisible(True)
        self.setBorderRadius(8)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setMinimumHeight(150)
        h = self.horizontalHeader()
        for c in range(len(headers)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.itemChanged.connect(lambda _: self._changed())

    def _changed(self):
        if not self._loading:
            self.on_change()

    def set_rows(self, rows: list[list]):
        self._loading = True
        self.setRowCount(0)
        for row in rows:
            self._append(row)
        self._loading = False

    def add_row(self, row: list):
        self._loading = True
        self._append(row)
        self._loading = False
        self.on_change()

    def _append(self, row: list):
        r = self.rowCount()
        self.insertRow(r)
        for c, v in enumerate(row):
            if c == self.selector_col:
                combo = EnumCombo(SELECTOR_ITEMS, self)
                combo.setValue(v)
                combo.currentIndexChanged.connect(lambda _: self._changed())
                self.setCellWidget(r, c, combo)
            else:
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                if c in self.readonly_cols:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(r, c, item)

    def rows(self) -> list[list]:
        out = []
        for r in range(self.rowCount()):
            row = []
            for c in range(self.columnCount()):
                if c == self.selector_col:
                    row.append(self.cellWidget(r, c).value())
                else:
                    it = self.item(r, c)
                    row.append(it.text().strip() if it else "")
            out.append(row)
        return out

    def remove_selected(self):
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)
        self.on_change()


class AttachmentsPage(ScrollPage):
    def __init__(self, state: AppState, parent=None):
        super().__init__("Attachments", "attachmentsPage", parent)
        self.state = state
        v = self.view
        mime_hint = "Leave the MIME type empty to let mkvpropedit detect it."

        # ---------------- delete
        card = Card(
            "Delete attachments",
            "Runs first. Select by name, ID, UID or MIME type (a MIME type deletes all matching ones).",
            v,
        )
        self.del_table = EditTable(["Select by", "Value"], 0, set(), self._sync, card)
        self.del_table.setColumnWidth(0, 160)
        card.addWidget(self.del_table)
        bar = QHBoxLayout()
        b_add = PushButton(FIF.ADD, "Add entry", card)
        b_add.clicked.connect(lambda: self.del_table.add_row([AttachmentSelector.NAME, ""]))
        b_fonts = DropDownPushButton(FIF.FONT, "Templates", card)
        menu = RoundMenu(parent=b_fonts)
        act = Action("Delete all fonts (all font MIME types)")
        act.triggered.connect(self._add_font_deletes)
        menu.addAction(act)
        b_fonts.setMenu(menu)
        b_rm = PushButton(FIF.REMOVE, "Remove", card)
        b_rm.clicked.connect(self.del_table.remove_selected)
        for b in (b_add, b_fonts, b_rm):
            bar.addWidget(b)
        bar.addStretch(1)
        card.vbox.addLayout(bar)
        self.body.addWidget(card)

        # ---------------- add
        card = Card("Add attachments", "Name/description/MIME type are optional (double-click to edit). " + mime_hint, v)
        self.add_table = EditTable(["File", "Name", "Description", "MIME type"], None, {0}, self._sync, card)
        self.add_table.setColumnWidth(0, 360)
        self.add_table.setColumnWidth(1, 160)
        self.add_table.setColumnWidth(2, 160)
        card.addWidget(self.add_table)
        bar = QHBoxLayout()
        b_add = PushButton(FIF.ADD, "Add files", card)
        b_add.clicked.connect(self._add_files)
        b_rm = PushButton(FIF.REMOVE, "Remove", card)
        b_rm.clicked.connect(self.add_table.remove_selected)
        bar.addWidget(b_add)
        bar.addWidget(b_rm)
        bar.addStretch(1)
        card.vbox.addLayout(bar)
        self.body.addWidget(card)

        # ---------------- replace
        card = Card("Replace attachments", "Replace an existing attachment (selection) with a new file. " + mime_hint, v)
        self.rep_table = EditTable(
            ["Select by", "Value", "New file", "Name", "Description", "MIME type"], 0, {2}, self._sync, card
        )
        self.rep_table.setColumnWidth(0, 140)
        self.rep_table.setColumnWidth(1, 160)
        self.rep_table.setColumnWidth(2, 300)
        card.addWidget(self.rep_table)
        bar = QHBoxLayout()
        b_add = PushButton(FIF.ADD, "Add replacement", card)
        b_add.clicked.connect(self._add_replace)
        b_rm = PushButton(FIF.REMOVE, "Remove", card)
        b_rm.clicked.connect(self.rep_table.remove_selected)
        bar.addWidget(b_add)
        bar.addWidget(b_rm)
        bar.addStretch(1)
        card.vbox.addLayout(bar)
        self.body.addWidget(card)
        self.body.addStretch(1)

        state.preset_replaced.connect(self.load)
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        a = self.state.preset.attachments
        self.del_table.set_rows([[d.selector, d.value] for d in a.delete])
        self.add_table.set_rows([[x.path, x.name, x.description, x.mime_type] for x in a.add])
        self.rep_table.set_rows(
            [[r.selector, r.value, r.path, r.name, r.description, r.mime_type] for r in a.replace]
        )

    def _sync(self):
        a = self.state.preset.attachments
        a.delete = [AttachmentDelete(selector=s, value=v) for s, v in self.del_table.rows()]
        a.add = [
            AttachmentAdd(path=p, name=n, description=d, mime_type=m) for p, n, d, m in self.add_table.rows() if p
        ]
        a.replace = [
            AttachmentReplace(selector=s, value=v, path=p, name=n, description=d, mime_type=m)
            for s, v, p, n, d, m in self.rep_table.rows()
            if p
        ]
        self.state.mark_dirty()

    def _pick_files(self, multi: bool) -> list[str]:
        filt = "Fonts (*.ttf *.otf *.ttc);;Images (*.jpg *.jpeg *.png);;All files (*)"
        start = self.state.settings.last_dir
        if multi:
            files, _ = QFileDialog.getOpenFileNames(self, "Choose attachments", start, filt)
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Choose new file", start, filt)
            files = [f] if f else []
        return [QDir.toNativeSeparators(f) for f in files]

    def _add_files(self):
        for f in self._pick_files(True):
            self.add_table.add_row([f, "", "", guess_mime(f)])

    def _add_replace(self):
        for f in self._pick_files(False):
            self.rep_table.add_row([AttachmentSelector.NAME, Path(f).name, f, "", "", ""])

    def _add_font_deletes(self):
        existing = {(s, v) for s, v in self.del_table.rows()}
        for mime in FONT_MIMES:
            if (AttachmentSelector.MIME, mime) not in existing:
                self.del_table.add_row([AttachmentSelector.MIME, mime])
