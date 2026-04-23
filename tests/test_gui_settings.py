import json

import pytest

from sssep_batch.gui import load_saved_folders, save_folder_defaults


def test_load_saved_folders_returns_empty_dict_when_file_is_missing(tmp_path):
    assert load_saved_folders(tmp_path / "missing.json") == {}


def test_save_and_load_folder_defaults(tmp_path):
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
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_saved_folders(settings_path)
