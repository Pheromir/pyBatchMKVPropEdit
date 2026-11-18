from bmpe import __version__
from bmpe.core.licenses import license_dir, load_licenses


def test_every_license_file_exists():
    entries = load_licenses()
    assert entries, "run tools/collect_licenses.py"
    for e in entries:
        assert e.files, e.name
        for name in e.files:
            assert (license_dir() / name).is_file(), f"{e.name}: {name}"
        assert "is missing)" not in e.text()


def test_app_entry_is_current():
    app = load_licenses()[0]
    assert app.name == "pyBatchMKVPropEdit"
    assert app.version == __version__, "run tools/collect_licenses.py after changing the version"
    assert app.license == "MIT"
    assert "Pheromir" in app.text()


def test_missing_folder_gives_empty_list(tmp_path):
    assert load_licenses(tmp_path) == []
