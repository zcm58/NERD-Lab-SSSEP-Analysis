"""PsychoPy participant prompts with flip-synchronized BioSemi triggers."""

from __future__ import annotations

import csv
import importlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from math import ceil, isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import ModuleType
from typing import Any, Protocol
from uuid import uuid4

from .models import (
    CONDITION_CUES,
    CUE_PROMPTS,
    CueEpoch,
    CuePresentationRecord,
    TaskRunResult,
    TaskSettings,
)
from .schedule import build_cue_schedule
from .triggers import SerialTriggerBackend, SerialTriggerError


class TriggerBackend(Protocol):
    """Runtime-facing subset of the serial trigger backend."""

    def connect(self) -> None: ...

    def send_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> Any: ...

    def send_prevalidated_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> None: ...

    def close(self) -> None: ...


ProgressCallback = Callable[[int, int], None]
TriggerBackendFactory = Callable[[TaskSettings], TriggerBackend]
AbortRequested = Callable[[], bool]


class PsychoPyUnavailableError(RuntimeError):
    """Raised when the optional presentation dependency cannot be imported."""


class PsychoPyTaskRunner:
    """Show one task schedule and send a trigger on every cue-onset flip."""

    def __init__(
        self,
        trigger_backend: TriggerBackend,
        *,
        psychopy_modules: tuple[ModuleType | Any, ModuleType | Any, ModuleType | Any]
        | None = None,
    ) -> None:
        self._trigger_backend = trigger_backend
        self._send_prevalidated_trigger = getattr(
            trigger_backend,
            "send_prevalidated_trigger",
            trigger_backend.send_trigger,
        )
        self._psychopy_modules = psychopy_modules

    def run(
        self,
        settings: TaskSettings,
        *,
        progress_callback: ProgressCallback | None = None,
        abort_requested: AbortRequested | None = None,
    ) -> TaskRunResult:
        schedule = build_cue_schedule(settings)
        run_id = uuid4().hex
        started_at_utc = datetime.now(timezone.utc).isoformat()
        records: list[CuePresentationRecord] = []
        aborted = False
        abort_reason: str | None = None
        window: Any | None = None

        visual, core, keyboard_module = self._psychopy_modules or _load_psychopy_modules()
        try:
            # Opening COM3 is the hardware preflight. It must succeed before a
            # participant-facing PsychoPy window or screen is created.
            self._trigger_backend.connect()
            window = visual.Window(
                fullscr=True,
                color="black",
                units="height",
                allowGUI=False,
                waitBlanking=True,
            )
            measured_refresh_hz = self._measure_refresh_rate(window)
            frames_per_epoch = max(
                1,
                ceil(settings.epoch_duration_sec * measured_refresh_hz),
            )
            keyboard = keyboard_module.Keyboard()
            instruction = visual.TextStim(
                window,
                text="Press Space when you are ready to begin.\n\nPress Escape to stop.",
                color="white",
                height=0.055,
                wrapWidth=1.5,
                autoLog=False,
            )
            cue_stimuli = {
                cue: visual.TextStim(
                    window,
                    text=CUE_PROMPTS[cue],
                    color="white",
                    height=0.085,
                    wrapWidth=1.5,
                    autoLog=False,
                )
                for cue in CONDITION_CUES[settings.condition]
            }

            start_abort_reason = _wait_for_space_or_escape(
                window,
                keyboard,
                instruction,
                abort_requested=abort_requested,
            )
            if start_abort_reason is not None:
                aborted = True
                abort_reason = start_abort_reason
            else:
                keyboard.clearEvents()
                task_clock = core.Clock()
                task_clock.reset()
                if progress_callback is not None:
                    progress_callback(0, settings.total_epochs)

                for epoch in schedule:
                    stimulus = cue_stimuli[epoch.cue]
                    callback_state: dict[str, float | Exception | None] = {
                        "cue_onset_time_sec": None,
                        "error": None,
                    }
                    for frame_index in range(frames_per_epoch):
                        shutdown_requested = (
                            abort_requested is not None and abort_requested()
                        )
                        if shutdown_requested or _escape_pressed(keyboard):
                            aborted = True
                            abort_reason = (
                                "Application shutdown requested during a cue epoch."
                                if shutdown_requested
                                else "Escape pressed during a cue epoch."
                            )
                            if records:
                                self._close_last_record(
                                    records,
                                    offset_time_sec=float(task_clock.getTime()),
                                    completed=False,
                                )
                            break

                        stimulus.draw()
                        if frame_index == 0:
                            window.callOnFlip(
                                self._emit_cue_trigger,
                                epoch,
                                task_clock,
                                callback_state,
                            )
                        window.flip()

                        if frame_index != 0:
                            continue
                        trigger_error = callback_state["error"]
                        cue_onset_time_sec = callback_state["cue_onset_time_sec"]
                        if not isinstance(cue_onset_time_sec, float):
                            raise RuntimeError(
                                "The cue-onset callback did not run on the display flip."
                            )
                        if records:
                            self._close_last_record(
                                records,
                                offset_time_sec=cue_onset_time_sec,
                                completed=True,
                            )
                            if progress_callback is not None:
                                progress_callback(epoch.epoch_index, settings.total_epochs)
                        records.append(
                            CuePresentationRecord(
                                epoch_index=epoch.epoch_index,
                                condition=epoch.condition,
                                cue=epoch.cue,
                                trigger_code=epoch.trigger_code,
                                scheduled_onset_sec=epoch.scheduled_onset_sec,
                                cue_onset_time_sec=cue_onset_time_sec,
                                trigger_time_sec=cue_onset_time_sec,
                                trigger_succeeded=trigger_error is None,
                                trigger_error=(
                                    None if trigger_error is None else str(trigger_error)
                                ),
                            )
                        )
                        if trigger_error is not None:
                            aborted = True
                            abort_reason = (
                                f"BioSemi trigger output failed: {trigger_error}"
                            )
                            break
                    if aborted:
                        break

                if not aborted and records:
                    terminal_flip_state: dict[str, float | Exception | None] = {
                        "cue_onset_time_sec": None,
                        "error": None,
                    }
                    window.callOnFlip(
                        self._capture_flip_time,
                        task_clock,
                        terminal_flip_state,
                    )
                    window.flip()
                    terminal_flip_time_sec = terminal_flip_state["cue_onset_time_sec"]
                    if not isinstance(terminal_flip_time_sec, float):
                        raise RuntimeError(
                            "The terminal display callback did not run on the display flip."
                        )
                    self._close_last_record(
                        records,
                        offset_time_sec=terminal_flip_time_sec,
                        completed=True,
                    )
                    if progress_callback is not None:
                        progress_callback(settings.total_epochs, settings.total_epochs)
        finally:
            if window is not None:
                window.close()
            self._trigger_backend.close()

        return TaskRunResult(
            run_id=run_id,
            started_at_utc=started_at_utc,
            settings=settings,
            schedule=schedule,
            events=tuple(records),
            aborted=aborted,
            abort_reason=abort_reason,
        )

    def _emit_cue_trigger(
        self,
        epoch: CueEpoch,
        task_clock: Any,
        callback_state: dict[str, float | Exception | None],
    ) -> None:
        cue_onset_time_sec = float(task_clock.getTime())
        callback_state["cue_onset_time_sec"] = cue_onset_time_sec
        try:
            self._send_prevalidated_trigger(
                epoch.trigger_code,
                label=epoch.label,
                time_s=cue_onset_time_sec,
                epoch_index=epoch.epoch_index,
            )
        except SerialTriggerError as exc:
            callback_state["error"] = exc

    @staticmethod
    def _capture_flip_time(
        task_clock: Any,
        callback_state: dict[str, float | Exception | None],
    ) -> None:
        callback_state["cue_onset_time_sec"] = float(task_clock.getTime())

    @staticmethod
    def _close_last_record(
        records: list[CuePresentationRecord],
        *,
        offset_time_sec: float,
        completed: bool,
    ) -> None:
        record = records[-1]
        records[-1] = replace(
            record,
            cue_offset_time_sec=offset_time_sec,
            observed_duration_sec=offset_time_sec - record.cue_onset_time_sec,
            completed=completed,
        )

    @staticmethod
    def _measure_refresh_rate(window: Any) -> float:
        measure_refresh = getattr(window, "getActualFrameRate", None)
        if not callable(measure_refresh):
            raise RuntimeError(
                "PsychoPy cannot measure the display refresh rate for frame-locked timing."
            )
        try:
            measured_refresh_hz = measure_refresh(
                nIdentical=20,
                nMaxFrames=240,
                nWarmUpFrames=60,
                threshold=0.5,
                infoMsg="SSSEP is measuring this display's refresh rate...",
            )
        except Exception as exc:
            raise RuntimeError(
                "PsychoPy could not measure the display refresh rate for frame-locked timing."
            ) from exc
        if (
            isinstance(measured_refresh_hz, bool)
            or not isinstance(measured_refresh_hz, (int, float))
            or not isfinite(float(measured_refresh_hz))
            or measured_refresh_hz <= 0
        ):
            raise RuntimeError(
                "PsychoPy could not measure a finite positive display refresh rate."
            )
        return float(measured_refresh_hz)


def run_participant_task(
    settings: TaskSettings,
    *,
    trigger_backend: TriggerBackend | None = None,
    trigger_backend_factory: TriggerBackendFactory | None = None,
    progress_callback: ProgressCallback | None = None,
    abort_requested: AbortRequested | None = None,
    psychopy_modules: tuple[ModuleType | Any, ModuleType | Any, ModuleType | Any]
    | None = None,
) -> TaskRunResult:
    """Run one participant task and write its event log when configured."""

    if settings.output_folder is not None:
        _prepare_task_log_folder(settings.output_folder)

    if trigger_backend is not None and trigger_backend_factory is not None:
        raise ValueError("Pass trigger_backend or trigger_backend_factory, not both.")
    if trigger_backend is None:
        trigger_backend = (
            trigger_backend_factory(settings)
            if trigger_backend_factory is not None
            else SerialTriggerBackend(port=settings.serial_port)
        )

    result = PsychoPyTaskRunner(
        trigger_backend,
        psychopy_modules=psychopy_modules,
    ).run(
        settings,
        progress_callback=progress_callback,
        abort_requested=abort_requested,
    )
    if settings.output_folder is None:
        return result

    log_path = write_task_event_log(result, settings.output_folder)
    return replace(result, log_path=log_path)


def write_task_event_log(result: TaskRunResult, output_folder: Path) -> Path:
    """Write the planned schedule and observed cue timing to one CSV file."""

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    output_path = output_folder / f"sssep_task_events_{result.run_id}.csv"
    events_by_index = {event.epoch_index: event for event in result.events}
    fieldnames = [
        "run_id",
        "started_at_utc",
        "condition",
        "epoch_duration_sec",
        "total_epochs",
        "serial_port",
        "epoch_number",
        "cue",
        "prompt",
        "trigger_code",
        "scheduled_onset_sec",
        "cue_onset_time_sec",
        "trigger_time_sec",
        "cue_offset_time_sec",
        "observed_duration_sec",
        "completed",
        "trigger_succeeded",
        "trigger_error",
        "run_aborted",
        "abort_reason",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for epoch in result.schedule:
            event = events_by_index.get(epoch.epoch_index)
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "started_at_utc": result.started_at_utc,
                    "condition": epoch.condition.value,
                    "epoch_duration_sec": result.settings.epoch_duration_sec,
                    "total_epochs": result.settings.total_epochs,
                    "serial_port": result.settings.serial_port,
                    "epoch_number": epoch.epoch_index + 1,
                    "cue": epoch.cue.value,
                    "prompt": epoch.prompt,
                    "trigger_code": epoch.trigger_code,
                    "scheduled_onset_sec": epoch.scheduled_onset_sec,
                    "cue_onset_time_sec": (
                        "" if event is None else event.cue_onset_time_sec
                    ),
                    "trigger_time_sec": "" if event is None else event.trigger_time_sec,
                    "cue_offset_time_sec": (
                        "" if event is None else event.cue_offset_time_sec
                    ),
                    "observed_duration_sec": (
                        "" if event is None else event.observed_duration_sec
                    ),
                    "completed": False if event is None else event.completed,
                    "trigger_succeeded": (
                        "" if event is None else event.trigger_succeeded
                    ),
                    "trigger_error": "" if event is None else event.trigger_error,
                    "run_aborted": result.aborted,
                    "abort_reason": result.abort_reason,
                }
            )
    return output_path


def _prepare_task_log_folder(output_folder: Path) -> None:
    """Create and probe the log folder before opening COM3 or fullscreen UI."""

    output_folder = Path(output_folder)
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix=".sssep_task_write_test_",
            dir=output_folder,
        ) as probe:
            probe.write(b"ok\n")
            probe.flush()
    except OSError as exc:
        raise RuntimeError(
            "The task log folder could not be created or written to. Choose a "
            f"different folder before starting the participant task: {output_folder}"
        ) from exc


def _wait_for_space_or_escape(
    window: Any,
    keyboard: Any,
    instruction: Any,
    *,
    abort_requested: AbortRequested | None = None,
) -> str | None:
    keyboard.clearEvents()
    while True:
        if abort_requested is not None and abort_requested():
            return "Application shutdown requested before the task started."
        instruction.draw()
        window.flip()
        for key in keyboard.getKeys(
            keyList=["space", "escape"],
            waitRelease=False,
            clear=True,
        ):
            key_name = getattr(key, "name", str(key))
            if key_name == "escape":
                return "Escape pressed before the task started."
            if key_name == "space":
                return None


def _escape_pressed(keyboard: Any) -> bool:
    keys = keyboard.getKeys(
        keyList=["escape"],
        waitRelease=False,
        clear=True,
    )
    return any(getattr(key, "name", str(key)) == "escape" for key in keys)


def _load_psychopy_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    try:
        visual = importlib.import_module("psychopy.visual")
        core = importlib.import_module("psychopy.core")
        keyboard_module = importlib.import_module("psychopy.hardware.keyboard")
    except (ImportError, ModuleNotFoundError) as exc:
        raise PsychoPyUnavailableError(
            "PsychoPy could not be loaded. Use the project's Python 3.11 "
            "environment and run: powershell -NoProfile -ExecutionPolicy "
            "Bypass -File .\\install.ps1. If .venv uses another Python "
            "version, add -Recreate. "
            f"Details: {exc}"
        ) from exc
    return visual, core, keyboard_module
