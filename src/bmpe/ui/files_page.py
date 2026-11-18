"""Files page: add MKVs (also via drag & drop), sort, probe."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QTableWidgetItem, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressBar,
    PrimaryPushButton,
    PushButton,
    TableWidget,
    ToolButton,
    ToolTipFilter,
)
from qfluentwidgets import FluentIcon as FIF

from .state import AppState
from .widgets.common import page_layout

COLUMNS = ["#", "File", "Folder", "Title", "Tracks", "Status"]


class FileTable(TableWidget):
    """File list whose rows can be dragged to another position; files dropped from outside are passed on."""

    rows_dropped = Signal(int)  # row in front of which the selected rows go; rowCount() = to the end
    paths_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)

    def drop_row(self, pos: QPoint) -> int:
        index = self.indexAt(pos)
        if not index.isValid():
            return self.rowCount()
        return index.row() + (1 if pos.y() > self.visualRect(index).center().y() else 0)

    def dragEnterEvent(self, e):
        if e.source() is self or e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self:
            super().dragMoveEvent(e)  # drop indicator and scrolling at the edges
            e.setDropAction(Qt.MoveAction)
            e.accept()
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is self:
            row = self.drop_row(e.position().toPoint())
            # the table is rebuilt from the file list; Qt must not move or remove cells on its own
            e.setDropAction(Qt.IgnoreAction)
            e.accept()
            self.rows_dropped.emit(row)
        elif e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            if paths:
                self.paths_dropped.emit(paths)
        else:
            e.ignore()


class FilesPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("filesPage")
        lay = page_layout(self, "Files")
        w = self
        self.setAcceptDrops(True)

        bar = QHBoxLayout()
        self.btn_files = PrimaryPushButton(FIF.ADD, "Add files", w)
        self.btn_folder = PushButton(FIF.FOLDER_ADD, "Add folder", w)
        self.btn_reload = PushButton(FIF.SYNC, "Reload", w)
        self.btn_up = ToolButton(FIF.UP, w)
        self.btn_down = ToolButton(FIF.DOWN, w)
        self.btn_sort = ToolButton(FIF.ALIGNMENT, w)
        self.btn_remove = ToolButton(FIF.REMOVE, w)
        self.btn_clear = ToolButton(FIF.DELETE, w)
        for b, tip in (
            (self.btn_up, "Move up"),
            (self.btn_down, "Move down"),
            (self.btn_sort, "Sort by path"),
            (self.btn_remove, "Remove selected"),
            (self.btn_clear, "Remove all"),
        ):
            b.setToolTip(tip)
            b.installEventFilter(ToolTipFilter(b))
        for b in (self.btn_files, self.btn_folder, self.btn_reload):
            bar.addWidget(b)
        bar.addStretch(1)
        for b in (self.btn_up, self.btn_down, self.btn_sort, self.btn_remove, self.btn_clear):
            bar.addWidget(b)
        lay.addLayout(bar)

        self.progress = IndeterminateProgressBar(w)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.table = FileTable(w)
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(5, 160)
        lay.addWidget(self.table, 1)

        self.hint = CaptionLabel(
            "Drop files or folders here. Drag rows to reorder them; the order determines the numbering for {num}.", w
        )
        self.count_label = BodyLabel("", w)
        foot = QHBoxLayout()
        foot.addWidget(self.hint)
        foot.addStretch(1)
        foot.addWidget(self.count_label)
        lay.addLayout(foot)

        self.btn_files.clicked.connect(self._add_files)
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_reload.clicked.connect(lambda: self.state.reprobe(self._selected() or None))
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_sort.clicked.connect(self.state.sort_files)
        self.btn_remove.clicked.connect(lambda: self.state.remove_files(self._selected()))
        self.btn_clear.clicked.connect(self.state.clear_files)
        self.table.rows_dropped.connect(self._move_to)
        self.table.paths_dropped.connect(self.state.add_paths)
        state.files_changed.connect(self.refresh)
        state.file_updated.connect(self._update_row)
        state.probing_changed.connect(self.progress.setVisible)
        self.refresh()

    # ------------------------------------------------------------------ Drag & Drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.state.add_paths(paths)

    # ------------------------------------------------------------------ actions
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose MKV files",
            self.state.settings.last_dir,
            "Matroska (*.mkv *.mka *.mk3d *.webm *.mks);;All files (*)",
        )
        if files:
            self.state.settings.last_dir = str(Path(files[0]).parent)
            self.state.save_settings()
            self.state.add_paths(files)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", self.state.settings.last_dir)
        if folder:
            self.state.settings.last_dir = folder
            self.state.save_settings()
            self.state.add_paths([folder])

    def _selected(self) -> set[str]:
        rows = {i.row() for i in self.table.selectedIndexes()}
        return {self.state.files[r].path for r in rows if r < len(self.state.files)}

    def _move(self, delta: int):
        sel = self._selected()
        self.state.move_files(sel, delta)
        self._select(sel)

    def _move_to(self, row: int):
        """The selected rows were dragged in front of `row`."""
        sel = self._selected()
        self.state.move_files_to(sel, row)
        self._select(sel)

    def _select(self, sel: set[str]):
        self.table.clearSelection()
        mode = self.table.selectionMode()
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        for r, f in enumerate(self.state.files):
            if f.path in sel:
                self.table.selectRow(r)
        self.table.setSelectionMode(mode)

    # ------------------------------------------------------------------ display
    def refresh(self):
        files = self.state.files
        self.table.setRowCount(len(files))
        for r in range(len(files)):
            self._fill_row(r)
        n_err = sum(1 for f in files if f.error)
        text = f"{len(files)} file(s)"
        if n_err:
            text += f", {n_err} with errors"
        self.count_label.setText(text)

    def _update_row(self, path: str):
        for r, f in enumerate(self.state.files):
            if f.path == path:
                self._fill_row(r)
                break

    def _fill_row(self, r: int):
        f = self.state.files[r]
        p = Path(f.path)
        pending = f.path in self.state.pending
        if pending:
            status = "Reading..."
        elif f.error:
            status = f.error
        else:
            status = "Ready"
        values = [str(r + 1), p.name, str(p.parent), f.title, "" if pending else f.summary, status]
        for c, v in enumerate(values):
            item = QTableWidgetItem(v)
            item.setToolTip(f.path if c in (1, 2) else v)
            if c == 0:
                item.setTextAlignment(Qt.AlignCenter)
            if c == 5 and f.error and not pending:
                item.setForeground(QColor("#d13438"))
            self.table.setItem(r, c, item)
