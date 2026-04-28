"""Tests for saved launcher folder defaults.

The GUI stores remembered input/output folders in a small JSON file next to the
repo. These tests check that loading and saving that JSON works without opening
the real PySide6 window.
"""

import json

import pytest

from sssep_batch.gui import load_saved_folders, save_folder_defaults


def test_load_saved_folders_returns_empty_dict_when_file_is_missing(tmp_path):
    """Missing settings should behave like no saved defaults exist."""
    assert load_saved_folders(tmp_path / "missing.json") == {}


def test_save_and_load_folder_defaults(tmp_path):
    """Saved input/output folders should round-trip through JSON."""
    settings_path = tmp_path / "settings.json"

    save_folder_defaults(
        r"C:\Data\Input",
        r"C:\Data\Output",
        settings_path=settings_path,
    )

    assert load_saved_folders(settings_path) == {
        "input_folder": r"C:\Data\Input",
        "output_root": r"C:\Data\Output",
    }


def test_load_saved_folders_rejects_invalid_shape(tmp_path):
    """A settings file with the wrong JSON shape should be rejected clearly."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_saved_folders(settings_path)
