"""Saved session preferences and legacy folder defaults, without a GUI."""

from dataclasses import replace
import json

import pytest

from sssep_batch.config import STIMULATION_FREQUENCY_HZ
from sssep_batch.experiment.models import CueTriggerCodes, TaskSettings
from sssep_batch.gui import load_saved_folders, save_folder_defaults
import sssep_batch.launcher_settings as settings_module
from sssep_batch.launcher_settings import (
    LauncherSettings, load_launcher_settings, save_launcher_settings,
)


CHANNELS = ("Cz", "C3", "C4")


def defaults() -> LauncherSettings:
    return LauncherSettings(
        task=TaskSettings(
            epoch_duration_sec=15.0,
            epochs_per_condition=10,
            trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        ),
        plot_channel="Cz",
        stimulation_hz=STIMULATION_FREQUENCY_HZ,
    )


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


def test_missing_settings_preserve_launcher_defaults(tmp_path):
    original = defaults()
    loaded = load_launcher_settings(
        original, channels=CHANNELS, settings_path=tmp_path / "missing.json"
    )
    assert loaded == original
    assert loaded.stimulation_hz == 26.0
    assert loaded.roi_name == "Cz"
    assert loaded.roi_channels == ("Cz",)


@pytest.mark.parametrize("frequency", [None, 12.5])
def test_saved_frequency_takes_precedence_over_new_default(tmp_path, frequency):
    settings_path = tmp_path / "settings.json"
    save_launcher_settings(replace(defaults(), stimulation_hz=frequency), settings_path)

    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded.stimulation_hz == frequency


def test_launcher_preferences_round_trip_all_editable_fields(tmp_path):
    original = defaults()
    selected = replace(
        original,
        task=replace(
            original.task,
            epoch_duration_sec=1.5,
            epochs_per_condition=8,
            break_duration_sec=0.5,
            left_hand_prompt="Attend to your left hand.",
            right_hand_prompt="Attend to your right hand.",
            right_ankle_prompt="Attend to your right ankle.",
            break_prompt="Please rest.\nThe next cue will appear shortly.",
            output_folder=tmp_path / "Task logs",
            test_mode=True,
        ),
        plot_channel="C4",
        roi_name="Hand ROI",
        roi_channels=("C3", "c3", "C4", "External electrode"),
        stimulation_hz=80.0,  # Analysis range validation happens when processing.
        remember_folders=False,
        input_folder=str(tmp_path / "recordings"),
        output_root=str(tmp_path / "results"),
    )
    settings_path = tmp_path / "settings.json"

    save_launcher_settings(selected, settings_path)
    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded == selected
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert not {"serial_port", "trigger_codes", "random_seed", "condition"} & saved["task"].keys()
    assert loaded.task.serial_port == "COM3"
    assert loaded.task.trigger_codes == CueTriggerCodes(11, 12, 21, 22)
    assert loaded.task.random_seed is None
    assert saved["roi_channels"] == ["C3", "c3", "C4", "External electrode"]


def test_legacy_plot_electrode_becomes_active_single_electrode_roi(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"plot_channel": "C4", "stimulation_hz": 12.5}', encoding="utf-8")

    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded.roi_name == "C4"
    assert loaded.roi_channels == ("C4",)
    assert loaded.stimulation_hz == 12.5


def test_active_roi_trims_names_and_preserves_order_without_dataset_validation(tmp_path):
    selected = replace(
        defaults(), roi_name=" Custom ", roi_channels=(" X2 ", "x2", "Cz"),
    )
    assert selected.roi_name == "Custom"
    assert selected.roi_channels == ("X2", "x2", "Cz")
    settings_path = tmp_path / "settings.json"
    save_launcher_settings(selected, settings_path)
    assert load_launcher_settings(
        defaults(), channels=CHANNELS, settings_path=settings_path,
    ) == selected


def test_legacy_folder_file_seeds_task_log_folder(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_module.save_folder_defaults(
        str(tmp_path / "recordings"), str(tmp_path / "old results"), settings_path
    )

    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded.input_folder == str(tmp_path / "recordings")
    assert loaded.output_root == str(tmp_path / "old results")
    assert loaded.task.output_folder == tmp_path / "old results"
    assert loaded.task.epoch_duration_sec == 15.0
    assert loaded.task.epochs_per_condition == 10
    assert loaded.task.test_mode is False


def test_missing_session_fields_keep_defaults_and_explicit_empty_log_stays_empty(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "task": {"break_duration_sec": 4.5, "output_folder": None},
        "output_root": str(tmp_path / "results"),
    }), encoding="utf-8")

    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded.task.break_duration_sec == 4.5
    assert loaded.task.epoch_duration_sec == 15.0
    assert loaded.task.output_folder is None


def test_recording_folder_update_preserves_session_preferences(tmp_path):
    original = defaults()
    selected = replace(
        original,
        task=replace(original.task, epochs_per_condition=24, left_hand_prompt="Left!"),
        plot_channel="C3", stimulation_hz=10.0,
        roi_name="Central", roi_channels=("C3", "Cz", "C4"),
    )
    settings_path = tmp_path / "settings.json"
    save_launcher_settings(selected, settings_path)

    settings_module.save_folder_defaults("new input", "new output", settings_path)
    loaded = load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)

    assert loaded == replace(selected, input_folder="new input", output_root="new output")
    assert load_saved_folders(settings_path) == {
        "input_folder": "new input", "output_root": "new output"
    }


@pytest.mark.parametrize("payload", [
    [], {"task": []}, {"task": {"epochs_per_condition": True}},
    {"task": {"epochs_per_condition": 3}}, {"task": {"epoch_duration_sec": "15"}},
    {"task": {"break_duration_sec": 0}}, {"task": {"left_hand_prompt": "   "}},
    {"task": {"output_folder": 42}}, {"task": {"test_mode": 1}},
    {"plot_channel": None}, {"plot_channel": "missing"},
    {"stimulation_hz": True}, {"stimulation_hz": "10"}, {"stimulation_hz": 0},
    {"stimulation_hz": float("inf")}, {"remember_folders": 1},
    {"input_folder": []}, {"output_root": None}, {"unrecognized": "value"},
    {"roi_name": "Central"}, {"roi_channels": ["Cz"]},
    {"roi_name": None, "roi_channels": None},
    {"roi_name": " ", "roi_channels": ["Cz"]},
    {"roi_name": "Central", "roi_channels": []},
    {"roi_name": "Central", "roi_channels": "Cz"},
    {"roi_name": "Central", "roi_channels": ["Cz", None]},
    {"roi_name": "Central", "roi_channels": ["Cz", ""]},
    {"roi_name": "Central", "roi_channels": ["Cz", " Cz "]},
])
def test_invalid_saved_values_are_reported(tmp_path, payload):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises((ValueError, TypeError)):
        load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)


@pytest.mark.parametrize("field,value", [
    ("trigger_codes", {"both_hands_left_hand": 77}),
    ("serial_port", "COM7"), ("random_seed", 42), ("condition", "both_hands"),
])
@pytest.mark.parametrize("inside_task", [True, False])
def test_saved_file_cannot_override_fixed_hardware_or_condition_order(
    tmp_path, field, value, inside_task,
):
    settings_path = tmp_path / "settings.json"
    injected = {field: value}
    settings_path.write_text(
        json.dumps({"task": injected} if inside_task else injected), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unknown saved"):
        load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)


def test_invalid_json_is_reported_and_not_overwritten_by_folder_update(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        load_launcher_settings(defaults(), channels=CHANNELS, settings_path=settings_path)
    with pytest.raises(ValueError, match="not valid JSON"):
        settings_module.save_folder_defaults("input", "output", settings_path)
    assert settings_path.read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize("folders_only", [False, True])
def test_failed_atomic_replace_preserves_existing_preferences(tmp_path, monkeypatch, folders_only):
    settings_path = tmp_path / "settings.json"
    save_launcher_settings(defaults(), settings_path)
    before = settings_path.read_bytes()

    def fail_replace(source, target):
        raise PermissionError("settings file is locked")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="locked"):
        if folders_only:
            settings_module.save_folder_defaults("new input", "new output", settings_path)
        else:
            save_launcher_settings(replace(
                defaults(), plot_channel="C4", roi_name="Central", roi_channels=("C3", "C4"),
            ), settings_path)

    assert settings_path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [settings_path]
