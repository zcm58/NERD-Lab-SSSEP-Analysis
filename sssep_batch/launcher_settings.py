"""Validated local launcher preferences, separate from analysis defaults."""

from dataclasses import dataclass, replace
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sssep_batch.experiment.models import TaskSettings
from sssep_batch.roi_settings import validate_roi


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / ".sssep_gui_settings.json"
_TASK_FIELDS = (
    "epoch_duration_sec", "epochs_per_condition", "break_duration_sec",
    "left_hand_prompt", "right_hand_prompt", "right_ankle_prompt", "break_prompt",
    "output_folder", "test_mode",
)
_LAUNCHER_FIELDS = (
    "plot_channel", "stimulation_hz", "remember_folders", "input_folder", "output_root",
    "plot_rois",
)


def validate_plot_rois(rois: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Copy named plot selections, preserving their order and separate identities."""
    if not isinstance(rois, dict):
        raise ValueError("Regions of Interest must contain names and electrode lists.")
    validated = {}
    names = set()
    for name, channels in rois.items():
        if not isinstance(channels, tuple):
            raise ValueError("Each ROI must contain an electrode tuple.")
        name, labels = validate_roi(name, channels)
        if name.casefold() in names:
            raise ValueError(f"Duplicate ROI name: {name}")
        if len(labels) != len({label.casefold() for label in labels}):
            raise ValueError(f"ROI {name!r} cannot contain duplicate electrode names.")
        names.add(name.casefold())
        validated[name] = labels
    return validated


@dataclass(frozen=True)
class LauncherSettings:
    """Editable session and analysis preferences saved by File > Settings."""

    task: TaskSettings
    plot_channel: str
    stimulation_hz: float | None
    remember_folders: bool = True
    input_folder: str = ""
    output_root: str = ""
    plot_rois: dict[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskSettings):
            raise TypeError("task must be a TaskSettings value.")
        if not isinstance(self.plot_channel, str) or not self.plot_channel.strip():
            raise ValueError("plot_channel must be a nonblank string.")
        rois = self.plot_rois if self.plot_rois is not None else {
            self.plot_channel: (self.plot_channel,)
        }
        object.__setattr__(self, "plot_rois", validate_plot_rois(rois))
        if not isinstance(self.remember_folders, bool):
            raise ValueError("remember_folders must be True or False.")
        for name in ("input_folder", "output_root"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string.")
        frequency = self.stimulation_hz
        if frequency is not None and (
            not isinstance(frequency, (int, float))
            or isinstance(frequency, bool)
            or not isfinite(frequency)
            or frequency <= 0
        ):
            raise ValueError("stimulation_hz must be a finite number above zero, or None.")


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict:
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"Duplicate saved GUI setting: {key}")
        values[key] = value
    return values


def _read_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Saved GUI settings are not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Saved GUI settings must contain a JSON object: {path}")
    unknown = payload.keys() - {"task", "roi_name", "roi_channels", *_LAUNCHER_FIELDS}
    if unknown:
        raise ValueError(f"Unknown saved GUI settings: {', '.join(sorted(unknown))}")
    if "task" in payload:
        task = payload["task"]
        if not isinstance(task, dict):
            raise ValueError("Saved GUI setting 'task' must contain a JSON object.")
        unknown = task.keys() - set(_TASK_FIELDS)
        if unknown:
            raise ValueError(f"Unknown saved task settings: {', '.join(sorted(unknown))}")
    return payload


def load_launcher_settings(
    defaults: LauncherSettings,
    *,
    channels: tuple[str, ...],
    settings_path: str | Path = SETTINGS_PATH,
) -> LauncherSettings:
    """Load editable preferences; omitted fields retain their supplied defaults."""
    payload = _read_payload(Path(settings_path))
    task_values = dict(payload.get("task", {}))
    if "task" not in payload and payload.get("output_root"):
        task_values["output_folder"] = payload["output_root"]
    if "output_folder" in task_values:
        folder = task_values["output_folder"]
        if folder is not None and not isinstance(folder, str):
            raise ValueError("Saved task setting 'output_folder' must be a string or None.")
        task_values["output_folder"] = Path(folder) if folder else None
    launcher_values = {name: payload[name] for name in _LAUNCHER_FIELDS if name in payload}
    if "plot_rois" in payload:
        if {"roi_name", "roi_channels"} & payload.keys():
            raise ValueError("Saved ROI settings cannot mix collection and legacy selections.")
        rois = payload["plot_rois"]
        if not isinstance(rois, dict) or any(
            not isinstance(labels, list) for labels in rois.values()
        ):
            raise ValueError("Saved Regions of Interest need names and electrode lists.")
        launcher_values["plot_rois"] = {name: tuple(labels) for name, labels in rois.items()}
    elif {"roi_name", "roi_channels"} & payload.keys():
        if not isinstance(payload.get("roi_name"), str) or not isinstance(
            payload.get("roi_channels"), list
        ):
            raise ValueError("Saved ROI settings need a name and an electrode list.")
        launcher_values["plot_rois"] = {payload["roi_name"]: tuple(payload["roi_channels"])}
    elif "plot_channel" in payload:
        # Older settings files stored only the electrode used for processing plots.
        channel = payload["plot_channel"]
        if not isinstance(channel, str):
            raise ValueError("plot_channel must be a nonblank string.")
        launcher_values["plot_rois"] = {channel: (channel,)}
    settings = replace(
        defaults,
        task=replace(defaults.task, **task_values),
        **launcher_values,
    )
    if settings.plot_channel not in channels:
        raise ValueError(f"Unknown plot electrode in saved GUI settings: {settings.plot_channel}")
    return settings


def _write_payload(path: Path, payload: dict) -> None:
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_launcher_settings(
    settings: LauncherSettings, settings_path: str | Path = SETTINGS_PATH,
) -> None:
    """Atomically save editable values; hardware codes and random seeds stay in code."""
    task = {name: getattr(settings.task, name) for name in _TASK_FIELDS}
    task["output_folder"] = (
        str(settings.task.output_folder) if settings.task.output_folder is not None else None
    )
    payload = {
        "task": task,
        **{name: getattr(settings, name) for name in _LAUNCHER_FIELDS},
    }
    _write_payload(Path(settings_path), payload)


def load_saved_folders(settings_path: str | Path = SETTINGS_PATH) -> dict[str, str]:
    """Read legacy recording-folder defaults from the shared settings file."""
    path = Path(settings_path)
    if not path.exists():
        return {}
    payload = _read_payload(path)
    saved = {}
    for name in ("input_folder", "output_root"):
        value = payload.get(name, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"Saved GUI setting {name!r} must be a string: {path}")
        saved[name] = value
    return saved


def save_folder_defaults(
    input_folder: str, output_root: str, settings_path: str | Path = SETTINGS_PATH,
) -> None:
    """Update recording folders without discarding saved session preferences."""
    if not isinstance(input_folder, str) or not isinstance(output_root, str):
        raise ValueError("Recording folder defaults must be strings.")
    path = Path(settings_path)
    payload = _read_payload(path)
    payload.update(input_folder=input_folder, output_root=output_root)
    _write_payload(path, payload)
