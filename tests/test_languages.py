from bmpe.core.languages import FALLBACK, Language, pick_languages, search_languages
from bmpe.core.models import AppSettings

LANGS = [*FALLBACK, Language("Klingon", "tlh"), Language("Germanic languages", "gem")]


def test_pick_languages_for_the_dropdown():
    picked = pick_languages(LANGS, ["jpn", "deu", "EN", " de-DE ", "", "ger", "xx"])
    assert picked == [
        ("Japanese (jpn, ja)", "jpn"),
        ("German (ger, de)", "ger"),  # deu and the later ger are the same language
        ("English (eng, en)", "eng"),
        ("de-DE", "de-DE"),  # a tag with a region is offered as it is
        ("xx", "xx"),  # unknown codes too
    ]
    assert pick_languages(LANGS, []) == []


def test_search_languages_ranks_and_limits():
    names = lambda text, limit=15: [l.name for l in search_languages(LANGS, text, limit)]  # noqa: E731

    assert names("") == [] and names("   ") == []
    assert names("de") == ["German", "Undetermined"]  # the exact code first, then texts that contain it
    assert names("ger") == ["German", "Germanic languages"]  # exact code first, then names starting with it
    assert names("GERM") == ["German", "Germanic languages"]
    assert "Japanese" in names("an") and "Germanic languages" in names("an")  # found inside the text
    assert names("klingon") == ["Klingon"]
    assert len(names("a", limit=3)) == 3
    assert names("zzz") == []


def test_default_dropdown_languages_are_per_instance():
    a, b = AppSettings(), AppSettings()
    assert a.dropdown_languages[:4] == ["und", "ger", "eng", "jpn"]
    a.dropdown_languages.append("kor")
    assert "kor" not in b.dropdown_languages
    assert AppSettings.model_validate({"dropdown_languages": ["jpn"]}).dropdown_languages == ["jpn"]
