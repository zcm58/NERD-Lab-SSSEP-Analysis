"""Export one participant-demographics row per saved SSSEP task run."""

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from sssep_batch.experiment.models import ParticipantInformation


_TASK_LOG_PREFIX = "sssep_task_events_"
_DEMOGRAPHICS_FIELDS = (
    "participant_number",
    "participant_age",
    "participant_sex",
    "participant_handedness",
    "participant_colorblind",
)
_RUN_FIELDS = (*_DEMOGRAPHICS_FIELDS, "run_id", "started_at_utc", "run_aborted")
_LOG_FIELDS = (*_RUN_FIELDS, "test_mode")
_EXPORT_FIELDS = (*_RUN_FIELDS, "source_file")
_SAFE_RUN_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*")


@dataclass(frozen=True, slots=True)
class DemographicsExportResult:
    """Export counts, with invalid logs included in the skipped count."""

    output_path: Path
    exported_count: int
    skipped_count: int
    invalid_count: int


def _is_task_log(path: Path) -> bool:
    return (
        path.name.casefold().startswith(_TASK_LOG_PREFIX)
        and path.suffix.casefold() == ".csv"
    )


def _read_task_log(path: Path) -> dict[str, str] | None:
    """Read the metadata repeated across a run's rows and verify agreement."""

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        header = reader.fieldnames or []
        if not set(_DEMOGRAPHICS_FIELDS).intersection(header):
            return None
        if len(header) != len(set(header)) or not set(_LOG_FIELDS).issubset(header):
            raise ValueError("The task log has an incomplete or ambiguous header.")
        first_row = next(reader, None)
        if first_row is None or any(first_row[key] is None for key in _LOG_FIELDS):
            raise ValueError("The task log has missing run metadata.")
        metadata = tuple(first_row[key] for key in _LOG_FIELDS)
        if any(tuple(row[key] for key in _LOG_FIELDS) != metadata for row in reader):
            raise ValueError("Run metadata differs between task log rows.")

    run = dict(zip(_LOG_FIELDS, metadata, strict=True))
    if run["test_mode"] == "True" or not any(run[key].strip() for key in _DEMOGRAPHICS_FIELDS):
        return None
    if run["test_mode"] != "False" or run["run_aborted"] not in {"False", "True"}:
        raise ValueError("The task log has invalid run status.")
    if not _SAFE_RUN_ID.fullmatch(run["run_id"]):
        raise ValueError("The task log has an invalid run ID.")
    if datetime.fromisoformat(run["started_at_utc"]).utcoffset() != timedelta(0):
        raise ValueError("The task log has an invalid UTC start time.")
    if run["participant_colorblind"] not in {"False", "True"}:
        raise ValueError("The task log has an invalid colorblind status.")
    participant = ParticipantInformation(
        participant_number=run["participant_number"],
        age=int(run["participant_age"]),
        sex=run["participant_sex"],
        handedness=run["participant_handedness"],
        colorblind=run["participant_colorblind"] == "True",
    )
    return {
        "participant_number": participant.participant_number,
        "participant_age": str(participant.age),
        "participant_sex": participant.sex,
        "participant_handedness": participant.handedness,
        "participant_colorblind": str(participant.colorblind),
        "run_id": run["run_id"],
        "started_at_utc": run["started_at_utc"],
        "run_aborted": run["run_aborted"],
        "source_file": path.name,
    }


def export_demographics(
    task_log_folder: str | Path, output_path: str | Path,
) -> DemographicsExportResult:
    """Save a CSV from the task logs, preserving separate runs by one person."""

    folder = Path(task_log_folder)
    destination = Path(output_path).resolve()
    if destination.suffix.casefold() != ".csv":
        raise ValueError("Choose a CSV filename for the demographics export.")
    if _is_task_log(Path(output_path)) or _is_task_log(destination):
        raise ValueError("Choose a demographics filename that does not replace a task log.")

    source_paths = sorted(
        path for path in folder.iterdir() if _is_task_log(path) and path.is_file()
    )
    if any(source.resolve() == destination for source in source_paths):
        raise ValueError("Choose a demographics filename that does not replace a task log.")
    runs = defaultdict(list)
    invalid_count = 0
    for source in source_paths:
        try:
            record = _read_task_log(source)
        except (csv.Error, UnicodeError, ValueError):
            invalid_count += 1
            continue
        if record is not None:
            runs[record["run_id"]].append(record)

    records = []
    for copies in runs.values():
        if len({tuple(copy[key] for key in _RUN_FIELDS) for copy in copies}) == 1:
            records.append(copies[0])
        else:
            invalid_count += len(copies)
    if not records:
        invalid_note = f" Invalid task logs skipped: {invalid_count}." if invalid_count else ""
        raise ValueError(
            "No participant demographics were found. Choose the folder containing "
            "SSSEP task logs from participant runs." + invalid_note
        )
    records.sort(key=lambda record: (record["started_at_utc"], record["run_id"]))

    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8-sig", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=_EXPORT_FIELDS)
            writer.writeheader()
            writer.writerows(records)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return DemographicsExportResult(
        output_path=destination,
        exported_count=len(records),
        skipped_count=len(source_paths) - len(records),
        invalid_count=invalid_count,
    )
