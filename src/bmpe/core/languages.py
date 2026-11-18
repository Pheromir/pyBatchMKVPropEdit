"""Language list for the picker (from `mkvmerge --list-languages`, otherwise a built-in short list)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .mkvtoolnix import run_hidden


@dataclass(frozen=True)
class Language:
    name: str
    code: str  # preferred code for mkvpropedit (ISO 639-2, otherwise 639-3)
    iso1: str = ""

    @property
    def display(self) -> str:
        extra = f", {self.iso1}" if self.iso1 else ""
        return f"{self.name} ({self.code}{extra})"


FALLBACK = [
    Language("Undetermined", "und"),
    Language("German", "ger", "de"),
    Language("English", "eng", "en"),
    Language("Japanese", "jpn", "ja"),
    Language("French", "fre", "fr"),
    Language("Spanish", "spa", "es"),
    Language("Italian", "ita", "it"),
    Language("Portuguese", "por", "pt"),
    Language("Russian", "rus", "ru"),
    Language("Chinese", "chi", "zh"),
    Language("Korean", "kor", "ko"),
    Language("Dutch", "dut", "nl"),
    Language("Polish", "pol", "pl"),
    Language("Swedish", "swe", "sv"),
    Language("Danish", "dan", "da"),
    Language("Norwegian", "nor", "no"),
    Language("Finnish", "fin", "fi"),
    Language("Turkish", "tur", "tr"),
    Language("Arabic", "ara", "ar"),
    Language("Hindi", "hin", "hi"),
]

# ISO 639-2/T codes. mkvmerge only lists the /B variants, but mkvpropedit accepts both.
_T_TO_B = {
    "bod": "tib", "ces": "cze", "cym": "wel", "deu": "ger", "ell": "gre", "eus": "baq", "fas": "per",
    "fra": "fre", "hye": "arm", "isl": "ice", "kat": "geo", "mkd": "mac", "mri": "mao", "msa": "may",
    "mya": "bur", "nld": "dut", "ron": "rum", "slk": "slo", "sqi": "alb", "zho": "chi",
}
# language subtag, then any number of further subtags; or a private-use tag (x-...)
_TAG_RE = re.compile(r"(?:[a-z]{2,3}(?:-[a-z0-9]{1,8})*|x(?:-[a-z0-9]{1,8})+)", re.IGNORECASE)

_cache: list[Language] | None = None
_cache_key: str | None = None
# code (ISO 639-1/-2/-3, lower case) -> English name; pre-filled from the short list
_names: dict[str, str] = {}
# code (ISO 639-1/-2/-3, lower case) -> one key per language, so that ger / de compare equal
_keys: dict[str, str] = {}
_full_list = False  # True once the complete list from mkvmerge has been registered


def _short_name(name: str) -> str:
    """'Greek (modern, 1453-)' -> 'Greek', 'Spanish; Castilian' -> 'Spanish'."""
    name = re.sub(r"\s*\(.*?\)", "", name)
    return name.split(";")[0].strip()


def _register(name: str, *codes: str, key: str = "") -> None:
    short = _short_name(name)
    key = (key or next((c for c in codes if c), "")).lower()
    for code in codes:
        if code:
            _names.setdefault(code.lower(), short)
            _keys.setdefault(code.lower(), key)


for _l in FALLBACK:
    _register(_l.name, _l.code, _l.iso1)


def _primary(code: str) -> str:
    """Language subtag of a code/tag in its listed form: 'de-DE' -> 'de', 'DEU' -> 'ger'."""
    primary = (code or "").strip().lower().split("-")[0]
    return _T_TO_B.get(primary, primary)


def language_key(code: str) -> str:
    """The same key for every spelling of a language: ger / deu / de / de-DE."""
    primary = _primary(code)
    return _keys.get(primary, primary)


def language_problem(code: str) -> tuple[str, bool] | None:
    """(message, certain) if mkvpropedit will not accept the code, otherwise None.

    `certain` is False for well-formed codes that are merely missing from the language list.
    """
    code = (code or "").strip()
    if not _TAG_RE.fullmatch(code):
        return f"'{code}' is not a valid language code (expected e.g. ger, de or de-DE)", True
    primary = _primary(code)
    if primary == "x" or "qaa" <= primary <= "qtz":  # private use
        return None
    if _full_list and primary not in _keys:
        return f"Language code '{code}' is unknown; mkvpropedit will probably reject it", False
    return None


def _rows(text: str):
    for line in text.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 4 or set(cols[1]) <= {"-", "+", ""} or "ISO" in cols[1]:
            continue
        yield cols[:4]


def parse_list(text: str) -> list[Language]:
    langs: list[Language] = []
    for name, iso3, iso2, iso1 in _rows(text):
        if not iso2:  # only classic ISO 639-2 languages in the list; anything else can be typed
            continue
        langs.append(Language(name, iso2, iso1))
    return langs


def register_names(text: str) -> None:
    """Remembers the names of all languages (including ISO 639-3 only) for {lang_name}."""
    global _full_list
    rows = list(_rows(text))
    for name, iso3, iso2, iso1 in rows:  # 639-2/-1 take precedence ...
        _register(name, iso2, iso1, key=iso3 or iso2 or iso1)
    for name, iso3, iso2, iso1 in rows:  # ... over plain 639-3 codes
        _register(name, iso3, key=iso3)
    if len(rows) > len(FALLBACK):
        _full_list = True


def language_name(code: str) -> str:
    """English language name for ger / deu / de / de-DE; unknown -> the code itself."""
    code = (code or "").strip()
    if not code:
        return ""
    key = code.lower()
    if key in _names:
        return _names[key]
    return _names.get(_primary(code), code)


def pick_languages(languages: list[Language], codes: list[str]) -> list[tuple[str, str]]:
    """(text to show, code) for a hand-picked list of codes, in the given order.

    A code can be spelled in any way (ger, deu, de). Tags that are not in the list, such as de-DE, are kept
    as they are, so they can be offered as well.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for code in codes:
        code = code.strip()
        if not code:
            continue
        match = None
        if "-" not in code:
            wanted = code.lower()
            match = next((l for l in languages if wanted in (l.code.lower(), l.iso1.lower())), None)
            if match is None:
                key = language_key(code)
                match = next((l for l in languages if language_key(l.code) == key), None)
        entry = (match.display, match.code) if match else (code, code)
        if entry[0].lower() not in seen:
            seen.add(entry[0].lower())
            out.append(entry)
    return out


def search_languages(languages: list[Language], text: str, limit: int = 15) -> list[Language]:
    """The best matches for what was typed: the exact code first, then names starting with it, then the rest."""
    needle = text.strip().lower()
    if not needle:
        return []
    exact, starts, contains = [], [], []
    for l in languages:
        if needle in (l.code.lower(), l.iso1.lower()):
            exact.append(l)
        elif l.name.lower().startswith(needle):
            starts.append(l)
        elif needle in l.display.lower():
            contains.append(l)
    return (exact + starts + contains)[:limit]


def load_languages(mkvmerge: Path | str | None) -> list[Language]:
    global _cache, _cache_key
    key = str(mkvmerge or "")
    if _cache is not None and _cache_key == key:
        return _cache
    langs: list[Language] = []
    if mkvmerge:
        try:
            out = run_hidden([str(mkvmerge), "--ui-language", "en", "--list-languages"], timeout=30)
            text = out.stdout.decode("utf-8", "replace")
            langs = parse_list(text)
            register_names(text)
        except (OSError, subprocess.SubprocessError):
            langs = []
    if not langs:
        langs = list(FALLBACK)
    # frequently used ones first
    top = ["und", "ger", "eng", "jpn"]
    langs.sort(key=lambda l: (top.index(l.code) if l.code in top else len(top), l.name.lower()))
    _cache, _cache_key = langs, key
    return langs
