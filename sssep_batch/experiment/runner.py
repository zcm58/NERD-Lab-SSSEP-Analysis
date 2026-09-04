"""PySide6 participant prompts with swap-synchronized BioSemi triggers."""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from PySide6.QtCore import QObject, QRect, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLWindow
from PySide6.QtWidgets import QWidget

from .models import (
    CueEpoch,
    CuePresentationRecord,
    ParticipantInformation,
    TaskRunResult,
    TaskSettings,
)
from .schedule import build_cue_schedule
from .triggers import SerialTriggerBackend, SerialTriggerError, SimulatedTriggerBackend


READY_PROMPT = "Press Space when you are ready to begin.\n\nPress Escape to stop."
TEST_MODE_READY_PROMPT = (
    "TEST MODE: BioSemi triggers are disabled.\n\n" + READY_PROMPT
)
BEGIN_PROMPT = "The experiment is about to begin.."
END_PROMPT = "Thank you for your time! The experiment is now over."
BEGIN_DURATION_SEC = 5.0
END_DURATION_SEC = 5.0
EPOCH_END_TRIGGER_CODE = 100
CONDITION_HANDOVER_PROMPT = (
    "Condition 1 complete.\n\n"
    "Before starting Condition 2, please remove the TENS unit electrodes from "
    "the left hand and place them on the right ankle.\n\n"
    "When finished, press space to continue the experiment."
)
CONDITION_CONFIRM_PROMPT = (
    "By continuing, you are confirming that the TENS unit electrodes are "
    "properly secured on the right hand and right ankle.\n\n"
    "Press 'Y' to continue."
)
FRAME_TIMEOUT_MS = 5_000


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


FrameCallback = Callable[[], None]
ErrorCallback = Callable[[Exception], None]
TriggerBackendFactory = Callable[[TaskSettings], TriggerBackend]
ParticipantInformationCollector = Callable[[], ParticipantInformation | None]


class PresentationSurface(Protocol):
    """Display operations used by the task state machine."""

    def show_ready(self, text: str, on_visible: FrameCallback) -> None: ...

    def present(
        self, text: str, on_visible: FrameCallback, *, duration_sec: float | None = None
    ) -> None: ...

    def schedule(self, delay_seconds: float, callback: FrameCallback) -> None: ...

    def cancel_scheduled(self) -> None: ...

    def finish(self) -> None: ...


PresentationSurfaceFactory = Callable[
    [FrameCallback, FrameCallback, FrameCallback, ErrorCallback], PresentationSurface
]


class _FrameCallbackGate:
    """Run one callback only after its exact requested frame was swapped."""

    def __init__(self) -> None:
        self.current_generation = 0
        self._painted_generation = 0
        self._pending: tuple[int, FrameCallback] | None = None

    def request(self, callback: FrameCallback) -> int:
        if self._pending is not None:
            raise RuntimeError("A participant display frame is already pending.")
        self.current_generation += 1
        self._pending = (self.current_generation, callback)
        return self.current_generation

    def mark_painted(self, generation: int) -> None:
        self._painted_generation = generation

    def take_swapped_callback(self) -> FrameCallback | None:
        pending = self._pending
        if pending is None or pending[0] != self._painted_generation:
            return None
        self._pending = None
        return pending[1]

    def cancel(self) -> None:
        self._pending = None


class _QtCueWindow(QOpenGLWindow):
    """Fullscreen black OpenGL surface with centered white task text."""

    def __init__(
        self,
        on_space: FrameCallback,
        on_confirm: FrameCallback,
        on_escape: FrameCallback,
        on_error: ErrorCallback,
    ) -> None:
        super().__init__()
        self._on_space = on_space
        self._on_confirm = on_confirm
        self._on_escape = on_escape
        self._on_error = on_error
        self._text = ""
        self._frame_gate = _FrameCallbackGate()
        self._allow_close = False
        self._error_reported = False
        self._scheduled_callback: FrameCallback | None = None
        self._phase_duration_sec: float | None = None
        self._countdown_deadline: float | None = None
        self._countdown_seconds: int | None = None

        surface_format = self.format()
        surface_format.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        surface_format.setSwapInterval(1)
        self.setFormat(surface_format)
        self.setTitle("SSSEP Participant Task")
        self.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        self.frameSwapped.connect(self._frame_swapped)

        self._frame_watchdog = QTimer(self)
        self._frame_watchdog.setSingleShot(True)
        self._frame_watchdog.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_watchdog.timeout.connect(self._frame_timed_out)

        self._epoch_timer = QTimer(self)
        self._epoch_timer.setSingleShot(True)
        self._epoch_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._epoch_timer.timeout.connect(self._scheduled_time_reached)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(100)
        self._countdown_timer.timeout.connect(self._refresh_countdown)

    def show_ready(self, text: str, on_visible: FrameCallback) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("No participant display is available.")
        self.setScreen(screen)
        self._request_frame(text, on_visible)
        self.showFullScreen()
        self.requestActivate()

    def present(
        self, text: str, on_visible: FrameCallback, *, duration_sec: float | None = None
    ) -> None:
        self._countdown_timer.stop()
        self._phase_duration_sec = duration_sec
        self._countdown_deadline = None
        self._countdown_seconds = None if duration_sec is None else ceil(duration_sec)
        self._request_frame(text, on_visible)

    def schedule(self, delay_seconds: float, callback: FrameCallback) -> None:
        if self._scheduled_callback is not None:
            raise RuntimeError("A participant screen timer is already pending.")
        self._scheduled_callback = callback
        self._epoch_timer.start(max(1, ceil(delay_seconds * 1_000)))

    def cancel_scheduled(self) -> None:
        self._epoch_timer.stop()
        self._scheduled_callback = None
        self._countdown_timer.stop()

    def finish(self) -> None:
        self.cancel_scheduled()
        self._frame_watchdog.stop()
        self._frame_gate.cancel()
        self._allow_close = True
        self.close()

    def paintGL(self) -> None:  # noqa: N802 - Qt override
        generation = self._frame_gate.current_generation
        painter = QPainter(self)
        try:
            painter.fillRect(
                QRect(0, 0, self.width(), self.height()),
                QColor("black"),
            )
            if self._text:
                font = QFont("Arial")
                font.setPixelSize(max(28, int(self.height() * 0.065)))
                painter.setFont(font)
                painter.setPen(QColor("white"))
                margin = max(40, int(self.width() * 0.08))
                text_rect = QRect(
                    margin,
                    int(self.height() * 0.15),
                    max(1, self.width() - (2 * margin)),
                    int(self.height() * 0.7),
                )
                painter.drawText(
                    text_rect,
                    int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                    self._text,
                )
            if self._countdown_seconds is not None:
                font = QFont("Arial")
                font.setPixelSize(max(24, int(self.height() * 0.045)))
                painter.setFont(font)
                painter.setPen(QColor("white"))
                painter.drawText(
                    QRect(
                        0,
                        int(self.height() * 0.03),
                        self.width(),
                        int(self.height() * 0.09),
                    ),
                    int(Qt.AlignmentFlag.AlignCenter),
                    f"{self._countdown_seconds} s",
                )
        finally:
            painter.end()
        self._frame_gate.mark_painted(generation)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self._run_callback(self._on_escape)
            return
        if event.isAutoRepeat():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            event.accept()
            self._run_callback(self._on_space)
            return
        if event.key() == Qt.Key.Key_Y:
            event.accept()
            self._run_callback(self._on_confirm)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        QTimer.singleShot(0, self._on_escape)

    def _request_frame(self, text: str, on_visible: FrameCallback) -> None:
        self._text = text
        self._frame_gate.request(on_visible)
        self._frame_watchdog.start(FRAME_TIMEOUT_MS)
        self.update()

    def _frame_swapped(self) -> None:
        callback = self._frame_gate.take_swapped_callback()
        if callback is None:
            return
        onset = perf_counter()
        self._frame_watchdog.stop()
        self._run_callback(callback)
        # Start after the callback so the cue marker remains its first action.
        # Incidental countdown swaps have no callback and never send markers.
        if (
            self._phase_duration_sec is not None
            and not self._allow_close
            and not self._error_reported
        ):
            self._countdown_deadline = onset + self._phase_duration_sec
            self._countdown_timer.start()
            self._refresh_countdown()

    def _refresh_countdown(self) -> None:
        if self._countdown_deadline is None:
            return
        remaining = max(0, ceil(self._countdown_deadline - perf_counter()))
        if remaining != self._countdown_seconds:
            self._countdown_seconds = remaining
            self.update()
        if remaining == 0:
            self._countdown_timer.stop()

    def _frame_timed_out(self) -> None:
        self._frame_gate.cancel()
        self._report_error(
            RuntimeError(
                "The participant display did not present the requested frame. "
                "Check the display and graphics driver before running the task."
            )
        )

    def _scheduled_time_reached(self) -> None:
        callback = self._scheduled_callback
        self._scheduled_callback = None
        if callback is not None:
            self._run_callback(callback)

    def _run_callback(self, callback: FrameCallback) -> None:
        try:
            callback()
        except Exception as exc:
            self._report_error(exc)

    def _report_error(self, exc: Exception) -> None:
        if self._error_reported:
            return
        self._error_reported = True
        self.cancel_scheduled()
        self._frame_watchdog.stop()
        self._frame_gate.cancel()
        self._on_error(exc)


class QtTaskRunner(QObject):
    """Run one event-driven participant task on Qt's main GUI thread."""

    progress_changed = Signal(int, int)
    task_finished = Signal(object)
    task_failed = Signal(object)
    task_done = Signal()

    def __init__(
        self,
        *,
        trigger_backend: TriggerBackend | None = None,
        trigger_backend_factory: TriggerBackendFactory | None = None,
        participant_information_collector: (
            ParticipantInformationCollector | None
        ) = None,
        surface_factory: PresentationSurfaceFactory | None = None,
        monotonic: Callable[[], float] = perf_counter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if trigger_backend is not None and trigger_backend_factory is not None:
            raise ValueError("Pass trigger_backend or trigger_backend_factory, not both.")
        self._provided_backend = trigger_backend
        self._trigger_backend_factory = trigger_backend_factory
        self._participant_information_collector = participant_information_collector
        self._surface_factory = surface_factory or _QtCueWindow
        self._monotonic = monotonic

        self._settings: TaskSettings | None = None
        self._schedule: tuple[CueEpoch, ...] = ()
        self._records: list[CuePresentationRecord] = []
        self._trigger_backend: TriggerBackend | None = None
        self._participant_information: ParticipantInformation | None = None
        self._send_prevalidated_trigger: Callable[..., Any] | None = None
        self._surface: PresentationSurface | None = None
        self._run_id = ""
        self._started_at_utc = ""
        self._task_zero: float | None = None
        self._next_epoch_index = 0
        self._ready_visible = False
        self._handover_visible = False
        self._confirmation_visible = False
        self._started = False
        self._finished = False

    @Slot(object)
    def start(self, settings: TaskSettings) -> None:
        """Preflight the log and trigger backend, then show the ready frame."""
        if self._started:
            self._fail(RuntimeError("This participant task runner was already used."))
            return
        self._started = True
        try:
            if not isinstance(settings, TaskSettings):
                raise TypeError("settings must be a TaskSettings value.")
            if settings.output_folder is not None:
                _prepare_task_log_folder(settings.output_folder)

            self._settings = settings
            self._schedule = build_cue_schedule(settings)
            self._run_id = uuid4().hex
            self._started_at_utc = datetime.now(timezone.utc).isoformat()
            self._trigger_backend = self._make_trigger_backend(settings)
            self._trigger_backend.connect()
            self._send_prevalidated_trigger = getattr(
                self._trigger_backend,
                "send_prevalidated_trigger",
                self._trigger_backend.send_trigger,
            )
            if not settings.test_mode:
                collector = (
                    self._participant_information_collector
                    or self._collect_participant_information
                )
                participant_information = collector()
                if participant_information is None:
                    self._finish_result(
                        aborted=True,
                        abort_reason="Participant information entry was cancelled.",
                    )
                    return
                if not isinstance(participant_information, ParticipantInformation):
                    raise TypeError(
                        "The participant information collector must return a "
                        "ParticipantInformation value or None."
                    )
                self._participant_information = participant_information
            self._surface = self._surface_factory(
                self._space_pressed,
                self._confirm_pressed,
                self._escape_pressed,
                self._fail,
            )
            ready_prompt = TEST_MODE_READY_PROMPT if settings.test_mode else READY_PROMPT
            self._surface.show_ready(ready_prompt, self._ready_frame_visible)
        except Exception as exc:
            self._fail(exc)

    @Slot()
    def request_stop(self) -> None:
        """Abort an active task during application shutdown."""
        if not self._started or self._finished:
            return
        if self._task_zero is None:
            reason = "Application shutdown requested before the task started."
        else:
            reason = "Application shutdown requested during the task."
        self._abort(reason)

    def _make_trigger_backend(self, settings: TaskSettings) -> TriggerBackend:
        if self._provided_backend is not None:
            return self._provided_backend
        if self._trigger_backend_factory is not None:
            return self._trigger_backend_factory(settings)
        if settings.test_mode:
            return SimulatedTriggerBackend()
        return SerialTriggerBackend(port=settings.serial_port)

    def _collect_participant_information(self) -> ParticipantInformation | None:
        from .participant_information import collect_participant_information

        parent = self.parent()
        return collect_participant_information(
            parent if isinstance(parent, QWidget) else None
        )

    def _ready_frame_visible(self) -> None:
        self._ready_visible = True

    def _space_pressed(self) -> None:
        if self._finished:
            return
        if self._handover_visible:
            self._handover_visible = False
            self._require_surface().present(
                CONDITION_CONFIRM_PROMPT, self._confirmation_frame_swapped
            )
            return
        if not self._ready_visible or self._task_zero is not None:
            return
        settings = self._require_settings()
        self._task_zero = self._monotonic()
        self.progress_changed.emit(0, settings.total_epochs)
        self._require_surface().present(
            BEGIN_PROMPT,
            self._begin_frame_swapped,
            duration_sec=self._countdown_duration(BEGIN_DURATION_SEC),
        )

    def _begin_frame_swapped(self) -> None:
        self._require_surface().schedule(BEGIN_DURATION_SEC, self._request_next_cue)

    def _confirm_pressed(self) -> None:
        if not self._confirmation_visible or self._finished:
            return
        self._confirmation_visible = False
        self._request_next_cue()

    def _escape_pressed(self) -> None:
        if self._finished:
            return
        if self._task_zero is None:
            reason = "Escape pressed before the task started."
        else:
            reason = "Escape pressed during the task."
        self._abort(reason)

    def _request_next_cue(self) -> None:
        surface = self._require_surface()
        epoch = self._schedule[self._next_epoch_index]
        surface.present(
            epoch.prompt,
            lambda: self._cue_frame_swapped(epoch),
            duration_sec=self._countdown_duration(
                self._require_settings().epoch_duration_sec
            ),
        )

    def _cue_frame_swapped(self, epoch: CueEpoch) -> None:
        settings = self._require_settings()
        if self._send_prevalidated_trigger is None:
            raise RuntimeError("The BioSemi trigger backend was not prepared.")

        onset_time_sec = self._elapsed_seconds()
        trigger_time_sec = self._elapsed_seconds()
        trigger_error: SerialTriggerError | None = None
        try:
            self._send_prevalidated_trigger(
                epoch.trigger_code,
                label=epoch.label,
                time_s=trigger_time_sec,
                epoch_index=epoch.epoch_index,
            )
        except SerialTriggerError as exc:
            trigger_error = exc

        self._records.append(
            CuePresentationRecord(
                epoch_index=epoch.epoch_index,
                condition=epoch.condition,
                cue=epoch.cue,
                trigger_code=epoch.trigger_code,
                scheduled_onset_sec=epoch.scheduled_onset_sec,
                cue_onset_time_sec=onset_time_sec,
                trigger_time_sec=trigger_time_sec,
                trigger_succeeded=trigger_error is None,
                trigger_error=(None if trigger_error is None else str(trigger_error)),
            )
        )
        self._next_epoch_index += 1

        if trigger_error is not None:
            self._abort(
                f"BioSemi trigger output failed: {trigger_error}",
                offset_time_sec=onset_time_sec,
            )
            return
        elapsed_since_onset = self._elapsed_seconds() - onset_time_sec
        self._require_surface().schedule(
            max(0.0, settings.epoch_duration_sec - elapsed_since_onset),
            self._cue_duration_reached,
        )

    def _cue_duration_reached(self) -> None:
        if self._next_epoch_index < len(self._schedule):
            if (
                self._schedule[self._next_epoch_index].condition
                != self._schedule[self._next_epoch_index - 1].condition
            ):
                self._require_surface().present(
                    CONDITION_HANDOVER_PROMPT, self._handover_frame_swapped
                )
                return
            settings = self._require_settings()
            self._require_surface().present(
                settings.break_prompt,
                self._break_frame_swapped,
                duration_sec=self._countdown_duration(settings.break_duration_sec),
            )
            return
        self._require_surface().present(
            END_PROMPT,
            self._end_frame_swapped,
            duration_sec=self._countdown_duration(END_DURATION_SEC),
        )

    def _handover_frame_swapped(self) -> None:
        if self._epoch_end_frame_swapped() is None:
            return
        self._handover_visible = True
        self.progress_changed.emit(
            self._next_epoch_index, self._require_settings().total_epochs
        )

    def _confirmation_frame_swapped(self) -> None:
        self._confirmation_visible = True

    def _break_frame_swapped(self) -> None:
        onset_time_sec = self._epoch_end_frame_swapped()
        if onset_time_sec is None:
            return
        settings = self._require_settings()
        self.progress_changed.emit(self._next_epoch_index, settings.total_epochs)
        elapsed_since_onset = self._elapsed_seconds() - onset_time_sec
        self._require_surface().schedule(
            max(0.0, settings.break_duration_sec - elapsed_since_onset),
            self._request_next_cue,
        )

    def _end_frame_swapped(self) -> None:
        onset_time_sec = self._epoch_end_frame_swapped()
        if onset_time_sec is None:
            return
        settings = self._require_settings()
        self.progress_changed.emit(settings.total_epochs, settings.total_epochs)
        elapsed_since_onset = self._elapsed_seconds() - onset_time_sec
        self._require_surface().schedule(
            max(0.0, END_DURATION_SEC - elapsed_since_onset),
            lambda: self._finish_result(aborted=False, abort_reason=None),
        )

    def _epoch_end_frame_swapped(self) -> float | None:
        """Mark the completed epoch before logging, progress, or timers."""
        if self._send_prevalidated_trigger is None:
            raise RuntimeError("The BioSemi trigger backend was not prepared.")
        record = self._records[-1]
        onset_time_sec = self._elapsed_seconds()
        trigger_error: SerialTriggerError | None = None
        try:
            self._send_prevalidated_trigger(
                EPOCH_END_TRIGGER_CODE,
                label=f"{record.condition.value}:{record.cue.value}:epoch_end",
                time_s=onset_time_sec,
                epoch_index=record.epoch_index,
            )
        except SerialTriggerError as exc:
            trigger_error = exc

        self._close_last_record(
            self._records,
            offset_time_sec=onset_time_sec,
            completed=True,
        )
        self._records[-1] = replace(
            self._records[-1],
            epoch_end_trigger_code=EPOCH_END_TRIGGER_CODE,
            epoch_end_trigger_time_sec=onset_time_sec,
            epoch_end_trigger_succeeded=trigger_error is None,
            epoch_end_trigger_error=(
                None if trigger_error is None else str(trigger_error)
            ),
        )
        if trigger_error is not None:
            self._abort(f"BioSemi epoch-end trigger output failed: {trigger_error}")
            return None
        return onset_time_sec

    def _countdown_duration(self, duration_sec: float) -> float | None:
        return duration_sec if self._require_settings().show_timer else None

    def _abort(
        self,
        reason: str,
        *,
        offset_time_sec: float | None = None,
    ) -> None:
        if self._finished:
            return
        if self._records and self._records[-1].cue_offset_time_sec is None:
            self._close_last_record(
                self._records,
                offset_time_sec=(
                    self._elapsed_seconds()
                    if offset_time_sec is None
                    else offset_time_sec
                ),
                completed=False,
            )
        self._finish_result(aborted=True, abort_reason=reason)

    def _finish_result(self, *, aborted: bool, abort_reason: str | None) -> None:
        if self._finished:
            return
        self._finished = True
        result = self._build_result(aborted=aborted, abort_reason=abort_reason)
        cleanup_error: Exception | None = None
        try:
            self._cleanup()
        except Exception as exc:
            cleanup_error = exc

        log_error: Exception | None = None
        try:
            if result.settings.output_folder is not None:
                log_path = write_task_event_log(result, result.settings.output_folder)
                result = replace(result, log_path=log_path)
        except Exception as exc:
            log_error = exc

        failure = cleanup_error or log_error
        if failure is None:
            self.task_finished.emit(result)
        else:
            self.task_failed.emit(failure)
        self.task_done.emit()

    def _fail(self, exc: Exception) -> None:
        if self._finished:
            return
        self._finished = True
        partial_result: TaskRunResult | None = None
        if self._task_zero is not None:
            if self._records and self._records[-1].cue_offset_time_sec is None:
                self._close_last_record(
                    self._records,
                    offset_time_sec=self._elapsed_seconds(),
                    completed=False,
                )
            partial_result = self._build_result(
                aborted=True,
                abort_reason=str(exc) or type(exc).__name__,
            )

        cleanup_error: Exception | None = None
        try:
            self._cleanup()
        except Exception as cleanup_exc:
            cleanup_error = cleanup_exc

        log_error: Exception | None = None
        if partial_result is not None and partial_result.settings.output_folder is not None:
            try:
                log_path = write_task_event_log(
                    partial_result,
                    partial_result.settings.output_folder,
                )
                partial_result = replace(partial_result, log_path=log_path)
            except Exception as write_exc:
                log_error = write_exc

        details = [str(exc) or type(exc).__name__]
        if cleanup_error is not None:
            details.append(f"Cleanup also failed: {cleanup_error}")
        if log_error is not None:
            details.append(f"Writing the partial task log also failed: {log_error}")
        elif partial_result is not None and partial_result.log_path is not None:
            details.append(f"Partial task log: {partial_result.log_path}")
        reported_error = exc if len(details) == 1 else RuntimeError("\n".join(details))
        self.task_failed.emit(reported_error)
        self.task_done.emit()

    def _build_result(
        self,
        *,
        aborted: bool,
        abort_reason: str | None,
    ) -> TaskRunResult:
        return TaskRunResult(
            run_id=self._run_id,
            started_at_utc=self._started_at_utc,
            settings=self._require_settings(),
            schedule=self._schedule,
            events=tuple(self._records),
            aborted=aborted,
            participant_information=self._participant_information,
            abort_reason=abort_reason,
        )

    def _cleanup(self) -> None:
        first_error: Exception | None = None
        surface = self._surface
        self._surface = None
        if surface is not None:
            try:
                surface.finish()
            except Exception as exc:
                first_error = exc
        backend = self._trigger_backend
        self._trigger_backend = None
        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _elapsed_seconds(self) -> float:
        if self._task_zero is None:
            return 0.0
        return float(self._monotonic() - self._task_zero)

    def _require_settings(self) -> TaskSettings:
        if self._settings is None:
            raise RuntimeError("Participant task settings are unavailable.")
        return self._settings

    def _require_surface(self) -> PresentationSurface:
        if self._surface is None:
            raise RuntimeError("The participant display is unavailable.")
        return self._surface

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


def write_task_event_log(result: TaskRunResult, output_folder: Path) -> Path:
    """Write the planned schedule and observed cue timing to one CSV file."""

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    output_path = output_folder / f"sssep_task_events_{result.run_id}.csv"
    events_by_index = {event.epoch_index: event for event in result.events}
    fieldnames = [
        "run_id",
        "started_at_utc",
        "participant_number",
        "participant_age",
        "participant_sex",
        "participant_handedness",
        "participant_colorblind",
        "condition",
        "epoch_duration_sec",
        "total_epochs",
        "test_mode",
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
        "break_duration_sec",
        "break_prompt",
        "epochs_per_condition",
        "condition_epoch_number",
        "scheduled_onset_reference",
        "show_timer",
        "epoch_end_trigger_code",
        "epoch_end_trigger_time_sec",
        "epoch_end_trigger_succeeded",
        "epoch_end_trigger_error",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for epoch in result.schedule:
            event = events_by_index.get(epoch.epoch_index)
            participant = result.participant_information
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "started_at_utc": result.started_at_utc,
                    "participant_number": (
                        "" if participant is None else participant.participant_number
                    ),
                    "participant_age": "" if participant is None else participant.age,
                    "participant_sex": "" if participant is None else participant.sex,
                    "participant_handedness": (
                        "" if participant is None else participant.handedness
                    ),
                    "participant_colorblind": (
                        "" if participant is None else participant.colorblind
                    ),
                    "condition": epoch.condition.value,
                    "epoch_duration_sec": result.settings.epoch_duration_sec,
                    "total_epochs": result.settings.total_epochs,
                    "test_mode": result.settings.test_mode,
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
                    "break_duration_sec": result.settings.break_duration_sec,
                    "break_prompt": result.settings.break_prompt,
                    "epochs_per_condition": result.settings.epochs_per_condition,
                    "condition_epoch_number": (
                        epoch.epoch_index % result.settings.epochs_per_condition + 1
                    ),
                    "scheduled_onset_reference": "condition_start",
                    "show_timer": result.settings.show_timer,
                    "epoch_end_trigger_code": (
                        "" if event is None else event.epoch_end_trigger_code
                    ),
                    "epoch_end_trigger_time_sec": (
                        "" if event is None else event.epoch_end_trigger_time_sec
                    ),
                    "epoch_end_trigger_succeeded": (
                        "" if event is None else event.epoch_end_trigger_succeeded
                    ),
                    "epoch_end_trigger_error": (
                        "" if event is None else event.epoch_end_trigger_error
                    ),
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
