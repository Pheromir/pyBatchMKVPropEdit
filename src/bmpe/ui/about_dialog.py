"""Info dialog: version of pyBatchMKVPropEdit and the bundled libraries with their license texts."""

from __future__ import annotations

import platform

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QListWidgetItem, QSplitter, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    HyperlinkLabel,
    ListWidget,
    MessageBoxBase,
    PlainTextEdit,
    StrongBodyLabel,
    SubtitleLabel,
)

from .. import __version__
from ..core.licenses import LicenseEntry, load_licenses

COPYRIGHT = "© 2026 Pheromir"


class AboutDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(900, 600)

        # header: icon, name, version, runtime
        head = QHBoxLayout()
        head.setSpacing(14)
        icon = QLabel(self)
        icon.setPixmap(QApplication.windowIcon().pixmap(48, 48))
        head.addWidget(icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(SubtitleLabel("pyBatchMKVPropEdit", self))
        col.addWidget(BodyLabel(f"Version {__version__} · {COPYRIGHT} · MIT License", self))
        col.addWidget(CaptionLabel("Batch editing of MKV properties with mkvpropedit", self))
        runtime = CaptionLabel(
            f"Python {platform.python_version()} · Qt {qVersion()} · PySide6 {pyside_version}", self
        )
        runtime.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(runtime)
        head.addLayout(col, 1)
        self.viewLayout.addLayout(head)
        self.viewLayout.addSpacing(6)
        self.viewLayout.addWidget(StrongBodyLabel("Licenses of pyBatchMKVPropEdit and the libraries it uses", self))

        self.list = ListWidget(self)
        self.list.setMinimumWidth(250)
        self.text = PlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(PlainTextEdit.WidgetWidth)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setFamilies(["Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Liberation Mono", mono.family()])
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)
        self.text.setFont(mono)
        split = QSplitter(Qt.Horizontal, self)
        split.addWidget(self.list)
        split.addWidget(self.text)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 640])
        self.viewLayout.addWidget(split, 1)

        self.link = HyperlinkLabel(self)  # stays visible (empty if there is no URL) so the layout doesn't jump
        self.viewLayout.addWidget(self.link, 0, Qt.AlignLeft)

        self.entries = load_licenses()
        for e in self.entries:
            item = QListWidgetItem(f"{e.name} {e.version}\n{e.license}")
            item.setData(Qt.UserRole, e)
            item.setToolTip(e.url)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._show)
        if self.entries:
            self.list.setCurrentRow(0)
        else:
            self.text.setPlainText("The license texts are missing. They are created by tools/collect_licenses.py.")

        self.yesButton.setText("Close")
        self.yesButton.setFixedWidth(140)
        self.cancelButton.hide()
        self.buttonLayout.insertStretch(0, 1)

    def _show(self, item: QListWidgetItem | None, *_):
        if item is None:
            return
        e: LicenseEntry = item.data(Qt.UserRole)
        self.text.setPlainText(e.text())
        self.link.setUrl(QUrl(e.url))
        self.link.setText(e.url)


def show_about(parent=None) -> None:
    AboutDialog(parent).exec()
