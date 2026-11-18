"""Settings page."""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBar,
    LineEdit,
    PushButton,
    SwitchButton,
    Theme,
    ToolTipFilter,
    setTheme,
)
from qfluentwidgets import FluentIcon as FIF

from .. import __version__
from ..core.languages import language_problem, pick_languages
from ..core.mkvtoolnix import dir_has_tools, standard_dirs, tool_version
from .about_dialog import COPYRIGHT, show_about
from .state import AppState
from .widgets.common import Card, EnumCombo, IntSpin, PathEdit, ScrollPage

THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}


def apply_theme(name: str) -> None:
    setTheme(THEMES.get(name, Theme.AUTO))


class SettingsPage(ScrollPage):
    _version_ready = Signal(int, object, str)

    def __init__(self, state: AppState, parent=None):
        super().__init__("Settings", "settingsPage", parent)
        self.state = state
        self._tools_shown = 0
        self._version_ready.connect(self._on_version)
        v = self.view

        # ---------------- MKVToolNix
        dirs = ", ".join(str(d) for d in standard_dirs()) or "–"
        card = Card(
            "MKVToolNix",
            "Search order: folder entered here → PATH → default folder "
            f"({dirs}). Leave empty to search automatically.",
            v,
        )
        row = QWidget(card)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.tool_dir = PathEdit("dir", parent=row)
        self.btn_apply = PushButton("Apply", row)
        rl.addWidget(self.tool_dir, 1)
        rl.addWidget(self.btn_apply)
        card.addRow("Folder", row)
        self.lbl_merge = BodyLabel("", card)
        self.lbl_merge.setWordWrap(True)
        card.addRow("mkvmerge", self.lbl_merge)
        self.lbl_prop = BodyLabel("", card)
        self.lbl_prop.setWordWrap(True)
        card.addRow("mkvpropedit", self.lbl_prop)
        self.body.addWidget(card)

        # ---------------- behavior
        card = Card("Behavior", "", v)
        self.only_changes = SwitchButton(card)
        self.only_changes.setOnText("on")
        self.only_changes.setOffText("off")
        card.addRow("Only write values that differ", self.only_changes, stretch=False, label_width=240)
        self.recursive = SwitchButton(card)
        self.recursive.setOnText("on")
        self.recursive.setOffText("off")
        card.addRow("Search folders recursively", self.recursive, stretch=False, label_width=240)
        self.workers = IntSpin(card)
        self.workers.setRange(1, 16)
        card.addRow("Parallel mkvpropedit processes", self.workers, stretch=False, label_width=240)
        self.slow_file = IntSpin(card)
        self.slow_file.setRange(0, 600)
        row = card.addRow("Ask when a file takes longer than", self.slow_file, stretch=False, label_width=240)
        row.setToolTip(
            "Minutes after which the program asks whether to keep waiting for mkvpropedit or to stop it. 0 = never ask."
        )
        row.installEventFilter(ToolTipFilter(row))
        row.layout().insertWidget(2, BodyLabel("minutes (0 = never)", row))
        self.body.addWidget(card)

        # ---------------- language picker
        card = Card(
            "Language picker",
            "These languages are offered in the dropdown of the rule editor. Every other language can still be "
            "typed there, by code or by name.",
            v,
        )
        self.dropdown_languages = LineEdit(card)
        self.dropdown_languages.setPlaceholderText("codes separated by commas, e.g. ger, eng, jpn, de-DE")
        card.addRow("Languages", self.dropdown_languages)
        self.dropdown_names = CaptionLabel("", card)
        self.dropdown_names.setWordWrap(True)
        self.dropdown_names.setTextColor("#606060", "#a0a0a0")
        card.addRow("", self.dropdown_names)
        self.body.addWidget(card)

        # ---------------- appearance
        card = Card("Appearance", "", v)
        self.theme = EnumCombo([("auto", "System"), ("light", "Light"), ("dark", "Dark")], card)
        card.addRow("Theme", self.theme, stretch=False)
        self.body.addWidget(card)

        loc = CardInfo(state)
        self.body.addWidget(loc.build(v))

        card = Card("About", "", v)
        card.addRow("Version", BodyLabel(f"pyBatchMKVPropEdit {__version__}", card))
        card.addRow("License", BodyLabel("MIT License", card))
        card.addRow("Copyright", BodyLabel(COPYRIGHT, card))
        info = PushButton(FIF.INFO, "Info", card)
        info.setToolTip("Version of pyBatchMKVPropEdit and the libraries it uses, with their licenses")
        info.installEventFilter(ToolTipFilter(info))
        info.clicked.connect(lambda: show_about(self.window()))
        card.addRow("Libraries", info, stretch=False)
        self.body.addWidget(card)
        self.body.addStretch(1)

        s = state.settings
        self.tool_dir.setText(s.mkvtoolnix_dir)
        self.only_changes.setChecked(s.only_changes)
        self.recursive.setChecked(s.recursive)
        self.workers.setValue(s.workers)
        self.slow_file.setValue(s.slow_file_minutes)
        self.dropdown_languages.setText(", ".join(s.dropdown_languages))
        self._show_dropdown_names()
        self.theme.setValue(s.theme)

        self.btn_apply.clicked.connect(self._apply_dir)
        self.only_changes.checkedChanged.connect(self._save)
        self.recursive.checkedChanged.connect(self._save)
        self.workers.valueChanged.connect(self._save)
        self.slow_file.valueChanged.connect(self._save)
        self.dropdown_languages.editingFinished.connect(self._save_dropdown_languages)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        state.tools_changed.connect(self._show_tools)
        state.settings_changed.connect(lambda: self.tool_dir.setText(state.settings.mkvtoolnix_dir))
        self._show_tools()

    def _show_tools(self):
        self._tools_shown += 1
        shown = self._tools_shown
        jobs = []
        for lbl, loc in ((self.lbl_merge, self.state.mkvmerge), (self.lbl_prop, self.state.mkvpropedit)):
            if loc:
                lbl.setText(f"{loc.path}  ({loc.source})")
                jobs.append((lbl, loc.path))
            else:
                lbl.setText("not found")

        def work():  # asking for the version starts the program, so keep it off the UI thread
            for lbl, path in jobs:
                version = tool_version(path)
                try:
                    self._version_ready.emit(shown, lbl, version)
                except RuntimeError:  # the window was closed in the meantime
                    return

        if jobs:
            threading.Thread(target=work, daemon=True).start()

    def _on_version(self, shown: int, lbl: BodyLabel, version: str):
        if shown == self._tools_shown and version:  # otherwise the tools have changed in the meantime
            lbl.setText(f"{lbl.text()}\n{version}")

    def _apply_dir(self):
        folder = self.tool_dir.text()
        if folder and not dir_has_tools(folder):
            InfoBar.error(
                "Invalid folder",
                "mkvmerge and mkvpropedit were not found in that folder.",
                duration=3000,
                parent=self.window(),
            )
            return
        self.state.set_mkvtoolnix_dir(folder)
        InfoBar.success("MKVToolNix", "Path applied.", duration=2000, parent=self.window())

    def _save(self, *_):
        s = self.state.settings
        s.only_changes = self.only_changes.isChecked()
        s.recursive = self.recursive.isChecked()
        s.workers = self.workers.value()
        s.slow_file_minutes = self.slow_file.value()
        self.state.save_settings()

    def _show_dropdown_names(self):
        entries = pick_languages(self.state.languages(), self.state.settings.dropdown_languages)
        self.dropdown_names.setText("Shown as: " + "  ·  ".join(display for display, _ in entries) if entries else "")

    def _save_dropdown_languages(self):
        codes = []
        for code in self.dropdown_languages.text().replace(";", ",").split(","):
            code = code.strip()
            if code and code.lower() not in [c.lower() for c in codes]:
                codes.append(code)
        invalid = [c for c in codes if (language_problem(c) or ("", False))[1]]
        if invalid:
            InfoBar.error(
                "Not a language code",
                ", ".join(invalid) + " — use codes such as ger, de or de-DE.",
                duration=4000,
                parent=self.window(),
            )
            return
        if codes != self.state.settings.dropdown_languages:
            self.state.settings.dropdown_languages = codes
            self.state.save_settings()
        self.dropdown_languages.setText(", ".join(codes))
        self._show_dropdown_names()

    def _theme_changed(self, *_):
        self.state.settings.theme = self.theme.value()
        self.state.save_settings()
        apply_theme(self.state.settings.theme)


class CardInfo:
    def __init__(self, state: AppState):
        self.state = state

    def build(self, parent) -> Card:
        card = Card("Storage location", "Presets and settings are stored here:", parent)
        card.addRow("Folder", BodyLabel(str(self.state.store.base), card))
        return card
