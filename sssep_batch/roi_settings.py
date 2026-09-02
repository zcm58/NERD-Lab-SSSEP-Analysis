"""Validated, atomic storage for named custom electrode selections."""

from collections.abc import Iterable
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


REPO_ROOT = Path(__file__).resolve().parents[1]
ROI_SETTINGS_PATH = REPO_ROOT / ".sssep_rois.json"


def validate_roi(name: str, channels: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Each ROI needs a nonblank name.")
    if isinstance(channels, (str, bytes)):
        raise ValueError("ROI electrodes must be a list of electrode names.")
    try:
        labels = tuple(channels)
    except TypeError as exc:
        raise ValueError("ROI electrodes must be a list of electrode names.") from exc
    if not labels or any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Each ROI needs at least one nonblank electrode name.")
    labels = tuple(label.strip() for label in labels)
    if len(labels) != len(set(labels)):
        raise ValueError("An ROI cannot contain duplicate electrode names.")
    return name.strip(), labels


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict:
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"Duplicate saved ROI name: {key}")
        values[key] = value
    return values


def load_custom_rois(path: str | Path = ROI_SETTINGS_PATH) -> dict[str, tuple[str, ...]]:
    """Read saved definitions; only an absent file means no custom ROIs."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        payload = json.loads(text, object_pairs_hook=_unique_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Saved ROIs are not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Saved ROIs must contain a JSON object of names and electrode lists.")
    rois = {}
    names = set()
    for name, channels in payload.items():
        if not isinstance(channels, list):
            raise ValueError(f"Saved ROI {name!r} must contain an electrode list.")
        name, labels = validate_roi(name, channels)
        if name.casefold() in names:
            raise ValueError(f"Duplicate saved ROI name: {name}")
        names.add(name.casefold())
        rois[name] = labels
    return rois


def save_custom_roi(
    name: str, channels: Iterable[str], path: str | Path = ROI_SETTINGS_PATH,
) -> dict[str, tuple[str, ...]]:
    """Merge one definition with the latest file; callers confirm overwrites."""
    name, labels = validate_roi(name, channels)
    path = Path(path)
    current = load_custom_rois(path)
    rois = {
        name if key.casefold() == name.casefold() else key:
        labels if key.casefold() == name.casefold() else value
        for key, value in current.items()
    }
    rois[name] = labels
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(rois, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return rois
