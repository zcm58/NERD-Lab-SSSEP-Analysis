"""Validated local launcher preferences, separate from analysis defaults."""

from dataclasses import dataclass, replace
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sssep_batch.experiment.models import TaskSettings


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / ".sssep_gui_settings.json"
_TASK_FIELDS = (
    "epoch_duration_sec", "epochs_per_condition", "break_duration_sec",
    "left_hand_prompt", "right_hand_prompt", "right_ankle_prompt", "break_prompt",
    "output_folder", "test_mode",
)
_LAUNCHER_FIELDS = (
    "plot_channel", "stimulation_hz", "remember_folders", "input_folder", "output_root",
    "roi_name", "roi_channels",
)


@dataclass(frozen=True)
class LauncherSettings:
    """Editable session and analysis preferences saved by File > Settings."""

    task: TaskSettings
    plot_channel: str
    stimulation_hz: float | None
    remember_folders: bool = True
    input_folder: str = ""
    output_root: str = ""
    roi_name: str | None = None
    roi_channels: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskSettings):
            raise TypeError("task must be a TaskSettings value.")
        if not isinstance(self.plot_channel, str) or not self.plot_channel.strip():
            raise ValueError("plot_channel must be a nonblank string.")
        if self.roi_name is None and self.roi_channels is None:
            object.__setattr__(self, "roi_name", self.plot_channel)
            object.__setattr__(self, "roi_channels", (self.plot_channel,))
        if not isinstance(self.roi_name, str) or not self.roi_name.strip():
            raise ValueError("roi_name must be a nonblank string.")
        if not isinstance(self.roi_channels, tuple) or not self.roi_channels or any(
            not isinstance(label, str) or not label.strip() for label in self.roi_channels
        ):
            raise ValueError("roi_channels must contain at least one electrode name.")
        labels = tuple(label.strip() for label in self.roi_channels)
        if len(labels) != len(set(labels)):
            raise ValueError("roi_channels cannot contain duplicate electrode names.")
        object.__setattr__(self, "roi_name", self.roi_name.strip())
        object.__setattr__(self, "roi_channels", labels)
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


def _read_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Saved GUI settings are not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Saved GUI settings must contain a JSON object: {path}")
    unknown = payload.keys() - {"task", *_LAUNCHER_FIELDS}
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
    if {"roi_name", "roi_channels"} & payload.keys():
        if not isinstance(payload.get("roi_name"), str) or not isinstance(
            payload.get("roi_channels"), list
        ):
            raise ValueError("Saved ROI settings need a name and an electrode list.")
        launcher_values["roi_channels"] = tuple(payload["roi_channels"])
    elif "plot_channel" in payload:
        # Older settings files stored only the electrode used for processing plots.
        launcher_values.update(roi_name=payload["plot_channel"], roi_channels=(payload["plot_channel"],))
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
