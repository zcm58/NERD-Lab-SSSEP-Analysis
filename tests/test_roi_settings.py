"""Custom ROI preferences must survive reloads and failed writes intact."""

import json
from pathlib import Path

import pytest

from sssep_batch import roi_settings


def test_path_is_local_to_repo_and_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert roi_settings.ROI_SETTINGS_PATH == (
        Path(roi_settings.__file__).resolve().parents[1] / ".sssep_rois.json"
    )
    path = tmp_path / "rois.json"
    assert roi_settings.load_custom_rois(path) == {}
    assert not path.exists()


def test_single_electrode_and_group_round_trip_with_order(tmp_path):
    path = tmp_path / "rois.json"
    assert roi_settings.save_custom_roi(" Left hand ", [" C3 "], path) == {
        "Left hand": ("C3",),
    }
    assert roi_settings.save_custom_roi(
        "Central", (label for label in ("C4", "Cz", "C3")), path,
    ) == {"Left hand": ("C3",), "Central": ("C4", "Cz", "C3")}
    reopened = roi_settings.load_custom_rois(str(path))
    assert list(reopened) == ["Left hand", "Central"]
    assert reopened["Central"] == ("C4", "Cz", "C3")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "Left hand": ["C3"], "Central": ["C4", "Cz", "C3"],
    }


def test_save_rereads_latest_file_and_updates_name_case_in_place(tmp_path):
    path = tmp_path / "rois.json"
    roi_settings.save_custom_roi("Central", ["Cz"], path)
    stale = roi_settings.load_custom_rois(path)
    roi_settings.save_custom_roi("Right", ["C4"], path)
    updated = roi_settings.save_custom_roi(" CENTRAL ", ["C1", "C2"], path)
    assert stale == {"Central": ("Cz",)}
    assert list(updated) == ["CENTRAL", "Right"]
    assert updated == {"CENTRAL": ("C1", "C2"), "Right": ("C4",)}
    assert roi_settings.load_custom_rois(path) == updated


def test_saved_labels_preserve_case_collisions_and_non_ascii_names(tmp_path):
    path = tmp_path / "rois.json"
    roi_settings.save_custom_roi("Sélection", ["c3", "C3", "Other label"], path)
    assert roi_settings.load_custom_rois(path) == {
        "Sélection": ("c3", "C3", "Other label"),
    }


@pytest.mark.parametrize(("name", "channels"), [
    ("", ["C3"]), ("  ", ["C3"]), (None, ["C3"]),
    ("New", []), ("New", "C3"), ("New", None), ("New", 12),
    ("New", [""]), ("New", ["C3", " "]), ("New", ["C3", None]),
    ("New", ["C3", 3]), ("New", ["C3", " C3 "]),
])
def test_invalid_definition_preserves_existing_file(tmp_path, name, channels):
    path = tmp_path / "rois.json"
    original = b'{"Existing": ["Cz"]}\n'
    path.write_bytes(original)
    with pytest.raises(ValueError):
        roi_settings.save_custom_roi(name, channels, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("contents", [
    "{broken", "[]", "null", '{"Empty": []}', '{" ": ["C3"]}',
    '{"One": "C3"}', '{"One": null}', '{"One": {"C3": true}}',
    '{"One": ["C3", "C3"]}', '{"One": ["C3", " C3 "]}',
    '{"One": ["C3", ""]}', '{"One": ["C3", 4]}',
    '{"One": ["C3"], "One": ["C4"]}',
    '{"One": ["C3"], " one ": ["C4"]}',
])
def test_invalid_saved_data_is_reported_and_never_replaced(tmp_path, contents):
    path = tmp_path / "rois.json"
    original = contents.encode("utf-8")
    path.write_bytes(original)
    with pytest.raises(ValueError):
        roi_settings.load_custom_rois(path)
    with pytest.raises(ValueError):
        roi_settings.save_custom_roi("New", ["Cz"], path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_existing_file_read_failure_is_not_treated_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "rois.json"
    original = b'{"Existing": ["Cz"]}\n'
    path.write_bytes(original)

    def denied(*args, **kwargs):
        raise PermissionError("Cannot read saved ROIs")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError, match="Cannot read"):
        roi_settings.load_custom_rois(path)
    with pytest.raises(PermissionError, match="Cannot read"):
        roi_settings.save_custom_roi("New", ["C3"], path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_atomic_write_failure_preserves_file_and_cleans_temp(tmp_path, monkeypatch, operation):
    path = tmp_path / "rois.json"
    original = b'{"Existing": ["Cz"]}\n'
    path.write_bytes(original)

    def fail(*args):
        raise PermissionError("Cannot finish saving ROIs")

    monkeypatch.setattr(roi_settings.os, operation, fail)
    with pytest.raises(PermissionError, match="Cannot finish"):
        roi_settings.save_custom_roi("New", ["C3"], path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_first_save_failure_leaves_no_file_or_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "rois.json"

    def denied(*args):
        raise PermissionError("Cannot replace saved ROIs")

    monkeypatch.setattr(roi_settings.os, "replace", denied)
    with pytest.raises(PermissionError):
        roi_settings.save_custom_roi("New", ["C3"], path)
    assert list(tmp_path.iterdir()) == []
