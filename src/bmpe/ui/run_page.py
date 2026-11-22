"""Preview & run page."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QTreeWidgetItem, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    ToolTipFilter,
    TreeWidget,
)
from qfluentwidgets import FluentIcon as FIF

from ..core.command import FilePlan, plan_batch
from ..core.runner import BatchRunner, RunResult, RunStatus
from .state import AppState
from .widgets.common import message_box, page_layout, Splitter, toast

WARN = QColor("#c27c0e")
ERR = QColor("#d13438")
OK = QColor("#107c10")
STATUS_COLOR = {
    RunStatus.OK: OK,
    RunStatus.WARNING: WARN,
    RunStatus.ERROR: ERR,
    RunStatus.CANCELLED: ERR,
    RunStatus.STOPPED: ERR,
}


class _Bridge(QObject):
    started = Signal(object)
    output = Signal(str, str)
    result = Signal(object)
    finished = Signal(object)


class RunPage(QWidget):
    run_finished = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("runPage")
        self.plans: list[FilePlan] = []
        self.items: dict[str, QTreeWidgetItem] = {}
        self.runner: BatchRunner | None = None
        lay = page_layout(self, "Preview & run")

        bar = QHBoxLayout()
        self.btn_run = PrimaryPushButton(FIF.PLAY, "Run", self)
        self.btn_cancel = PushButton(FIF.CANCEL, "Cancel", self)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Skips the files that are still waiting. A file being written is finished first.")
        self.btn_cancel.installEventFilter(ToolTipFilter(self.btn_cancel))
        self.btn_refresh = PushButton(FIF.SYNC, "Refresh preview", self)
        self.btn_expand = PushButton(FIF.VIEW, "Expand all", self)
        self.summary = BodyLabel("", self)
        for w in (self.btn_run, self.btn_cancel, self.btn_refresh, self.btn_expand):
            bar.addWidget(w)
        bar.addSpacing(12)
        bar.addWidget(self.summary, 1)
        lay.addLayout(bar)

        self.progress = ProgressBar(self)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        splitter = Splitter(Qt.Vertical, self)
        self.tree = TreeWidget(splitter)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["File / scope", "Field", "Old", "New"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setUniformRowHeights(True)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 200)
        self.log = PlainTextEdit(splitter)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("mkvpropedit output...")
        self.log.setMaximumBlockCount(20000)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.log)
        splitter.setSizes([520, 200])
        lay.addWidget(splitter, 1)

        self.bridge = _Bridge()
        self.bridge.started.connect(self._on_started)
        self.bridge.output.connect(self._on_output)
        self.bridge.result.connect(self._on_result)
        self.bridge.finished.connect(self._on_finished)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.refresh)

        # while a run is active: look out for a file that takes unusually long
        self._watch = QTimer(self)
        self._watch.setInterval(5000)
        self._watch.timeout.connect(self._check_slow_files)
        self._ask_after: dict[str, float] = {}  # path -> seconds of runtime after which to ask (again)
        self._asking = False

        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_run.clicked.connect(self._run)
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.btn_expand.clicked.connect(self._toggle_expand)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        for sig in (state.preset_edited, state.files_changed, state.settings_changed, state.tools_changed):
            sig.connect(self.schedule_refresh)
        state.file_updated.connect(lambda _: self.schedule_refresh())
        self.refresh()

    # ------------------------------------------------------------------ preview
    @property
    def running(self) -> bool:
        return self.runner is not None

    def schedule_refresh(self, *_):
        if not self.running:
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.schedule_refresh()

    def _exe_name(self) -> str:
        return str(self.state.mkvpropedit.path) if self.state.mkvpropedit else "mkvpropedit"

    def refresh(self):
        if self.running:
            return
        files = self.state.ready_files()
        self.plans = plan_batch(files, self.state.preset, self.state.settings.only_changes)
        expanded = {k for k, it in self.items.items() if it.isExpanded()}
        first_build = not self.items
        self.tree.clear()
        self.items = {}
        n_work = n_warn = n_err = 0
        for plan in self.plans:
            f = plan.file
            item = QTreeWidgetItem([Path(f.path).name, "", "", ""])
            item.setToolTip(0, f.path)
            if f.error:
                n_err += 1
                item.setText(1, "Error")
                item.setForeground(1, ERR)
            elif plan.has_work:
                n_work += 1
                item.setText(1, f"{len(plan.changes)} change(s)")
            else:
                item.setText(1, "no changes")
            if plan.warnings:
                n_warn += 1
                item.setText(2, f"{len(plan.warnings)} warning(s)")
                item.setForeground(2, WARN)
            for ch in plan.changes:
                c = QTreeWidgetItem([ch.scope, ch.field, ch.old, ch.new])
                for col in range(4):
                    c.setToolTip(col, c.text(col))
                item.addChild(c)
            for w in plan.warnings:
                c = QTreeWidgetItem(["⚠ Warning", "", "", w])
                c.setToolTip(3, w)
                for col in (0, 3):
                    c.setForeground(col, WARN)
                item.addChild(c)
            if plan.has_work:
                cmd = plan.command_line(self._exe_name())
                c = QTreeWidgetItem(["Command line", "", "", cmd])
                c.setToolTip(3, cmd)
                c.setData(0, Qt.UserRole, cmd)
                item.addChild(c)
            self.tree.addTopLevelItem(item)
            self.items[f.path] = item
            if f.path in expanded or (first_build and len(self.plans) <= 30 and (plan.has_work or plan.warnings)):
                item.setExpanded(True)
        pending = len(self.state.files) - len(files)
        parts = [f"{len(self.plans)} file(s)", f"{n_work} with changes"]
        if n_warn:
            parts.append(f"{n_warn} with warnings")
        if n_err:
            parts.append(f"{n_err} with errors")
        if pending:
            parts.append(f"{pending} still being read")
        if not self.state.mkvpropedit:
            parts.append("mkvpropedit not found!")
        self.summary.setText(" · ".join(parts))
        self.btn_run.setEnabled(n_work > 0 and self.state.mkvpropedit is not None and not pending)

    def _toggle_expand(self):
        expand = not any(it.isExpanded() for it in self.items.values())
        for it in self.items.values():
            it.setExpanded(expand)
        self.btn_expand.setText("Collapse all" if expand else "Expand all")

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        top = item if item.parent() is None else item.parent()
        plan = next((p for p in self.plans if self.items.get(p.file.path) is top), None)
        menu = RoundMenu(parent=self.tree)
        if plan and plan.has_work:
            a = Action(FIF.COPY, "Copy command line")
            a.triggered.connect(lambda: QGuiApplication.clipboard().setText(plan.command_line(self._exe_name())))
            menu.addAction(a)
        a = Action(FIF.COPY, "Copy row")
        a.triggered.connect(lambda: QGuiApplication.clipboard().setText("\t".join(item.text(c) for c in range(4))))
        menu.addAction(a)
        if plan:
            a = Action(FIF.FOLDER, "Open folder")
            a.triggered.connect(lambda: _open_folder(plan.file.path))
            menu.addAction(a)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ run
    def _run(self):
        self.refresh()
        todo = [p for p in self.plans if p.has_work]
        if not todo or not self.state.mkvpropedit:
            return
        n_warn = sum(1 for p in todo if p.warnings)
        text = f"{len(todo)} file(s) will be modified in place (no remux, but no undo either)."
        if n_warn:
            text += f"\n\n{n_warn} file(s) have warnings, please check the preview."
        box = message_box("Write changes?", text, self.window())
        box.yesButton.setText("Run")
        box.cancelButton.setText("Cancel")
        if not box.exec():
            return

        self.log.clear()
        self.progress.setRange(0, len(todo))
        self.progress.setValue(0)
        self._done = 0
        self._results: list[RunResult] = []
        self.btn_run.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        for p in self.plans:
            item = self.items.get(p.file.path)
            if item and p.has_work:
                item.setText(1, "waiting...")
        b = self.bridge
        self.runner = BatchRunner(
            self.state.mkvpropedit.path,
            todo,
            workers=self.state.settings.workers,
            on_start=b.started.emit,
            on_output=b.output.emit,
            on_result=b.result.emit,
        )
        runner = self.runner
        self._ask_after = {}
        self._watch.start()
        threading.Thread(target=lambda: b.finished.emit(runner.run()), daemon=True).start()

    def _check_slow_files(self):
        """Asks what to do when mkvpropedit has been busy with one file for longer than the limit."""
        limit = self.state.settings.slow_file_minutes * 60
        if not self.runner or limit <= 0 or self._asking:
            return
        for path, seconds in self.runner.running().items():
            if seconds < self._ask_after.get(path, limit):
                continue
            self._asking = True
            try:
                box = message_box(
                    "mkvpropedit is taking long",
                    f"\"{Path(path).name}\" has been in progress for {int(seconds // 60)} minute(s).\n\n"
                    "Large files can take a while, for example when statistics tags are calculated. "
                    "Stopping ends mkvpropedit in the middle of writing and can leave this file damaged.",
                    self.window(),
                )
                box.yesButton.setText("Keep waiting")
                box.cancelButton.setText("Stop this file")
                keep_waiting = bool(box.exec())
            finally:
                self._asking = False
            runner = self.runner
            if runner is None:  # the run ended while the question was open
                return
            if keep_waiting:
                self._ask_after[path] = runner.running().get(path, seconds) + limit
            elif runner.stop_file(path):
                self.log.appendPlainText(f"Stopping mkvpropedit for {path} on request.")
            return  # one question at a time

    def cancel_run(self, *_):
        """Skips the files that are still waiting; a file that is being written is finished first."""
        if self.runner and not self.runner.cancelled:
            self.runner.cancel()
            self.btn_cancel.setEnabled(False)
            self.log.appendPlainText("Cancel requested: files in progress are finished, the rest is skipped.")

    def _on_started(self, plan: FilePlan):
        item = self.items.get(plan.file.path)
        if item:
            item.setText(1, "running...")
        self.log.appendPlainText(f"▶ {plan.file.path}\n  {plan.command_line(self._exe_name())}")

    def _on_output(self, path: str, line: str):
        if line.strip():
            self.log.appendPlainText("  " + line)

    def _on_result(self, res: RunResult):
        self._done += 1
        self._results.append(res)
        self.progress.setValue(self._done)
        item = self.items.get(res.path)
        if item:
            item.setText(1, res.status.label)
            if res.status in STATUS_COLOR:
                item.setForeground(1, STATUS_COLOR[res.status])
        if res.status in (RunStatus.ERROR, RunStatus.CANCELLED) and res.output and res.exit_code is None:
            self.log.appendPlainText("  " + res.output)
        if res.status not in (RunStatus.SKIPPED,):
            self.log.appendPlainText(f"  → {res.status.label} (exit code {res.exit_code})\n")

    def _on_finished(self, results: list[RunResult]):
        self.runner = None
        self._watch.stop()
        self.btn_cancel.setEnabled(False)
        self.btn_refresh.setEnabled(True)
        counts: dict[RunStatus, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        msg = ", ".join(f"{n}× {s.label}" for s, n in counts.items())
        failed = sum(counts.get(s, 0) for s in (RunStatus.ERROR, RunStatus.CANCELLED, RunStatus.STOPPED))
        toast(
            "warning" if failed else "success",
            "Finished", msg, duration=5000 if failed else 3000, parent=self.window()
        )
        self.log.appendPlainText(f"Finished: {msg}")
        changed = [r.path for r in results if r.status in (RunStatus.OK, RunStatus.WARNING)]
        if changed:
            self.state.reprobe(changed)  # triggers a new preview afterwards
        else:
            self.refresh()
        self.run_finished.emit()


def _open_folder(path: str):
    """Shows the file in Explorer (Windows) or opens its folder in the file manager (other systems)."""
    if sys.platform == "win32":
        import subprocess

        subprocess.Popen(["explorer", "/select,", path])  # noqa: S603, S607
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
