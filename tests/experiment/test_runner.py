from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

from sssep_batch.experiment.models import (
    CueTarget,
    CueTriggerCodes,
    TaskCondition,
    TaskSettings,
)
from sssep_batch.experiment.runner import run_participant_task
from sssep_batch.experiment.triggers import SerialTriggerError


class _FakeWindow:
    def __init__(
        self,
        events: list[tuple[str, object]],
        *,
        actual_frame_rate: float | None,
        **kwargs: object,
    ) -> None:
        self.events = events
        self.time_s = 0.0
        self.actual_frame_rate = actual_frame_rate
        self.pending_callbacks: list[tuple[object, tuple[object, ...]]] = []
        self.events.append(("window_created", kwargs))

    def getActualFrameRate(self, **kwargs: object) -> float | None:  # noqa: N802
        self.events.append(("measure_refresh", kwargs))
        return self.actual_frame_rate

    def callOnFlip(self, callback: object, *args: object) -> None:  # noqa: N802
        trigger_code = getattr(args[0], "trigger_code", None)
        event_name = "call_on_flip" if trigger_code is not None else "terminal_call_on_flip"
        self.events.append((event_name, trigger_code))
        self.pending_callbacks.append((callback, args))

    def flip(self) -> float:
        self.events.append(("flip", self.time_s))
        self.time_s += 0.1
        callbacks = list(self.pending_callbacks)
        self.pending_callbacks.clear()
        for callback, args in callbacks:
            callback(*args)  # type: ignore[operator]
        return self.time_s

    def close(self) -> None:
        self.events.append(("window_closed", None))


class _FakeClock:
    def __init__(self, window: _FakeWindow) -> None:
        self.window = window
        self.offset = window.time_s

    def reset(self) -> None:
        self.offset = self.window.time_s

    def getTime(self) -> float:  # noqa: N802
        return self.window.time_s - self.offset


class _FakeKeyboard:
    def __init__(self) -> None:
        self.gate_opened = False

    def clearEvents(self) -> None:  # noqa: N802
        return None

    def getKeys(self, *, keyList: list[str], **kwargs: object) -> list[object]:  # noqa: N802
        if "space" in keyList and not self.gate_opened:
            self.gate_opened = True
            return [SimpleNamespace(name="space")]
        return []


class _FakeStim:
    def __init__(self, events: list[tuple[str, object]], *, text: str, **kwargs: object) -> None:
        self.events = events
        self.text = text

    def draw(self) -> None:
        self.events.append(("draw", self.text))


class _FakeBackend:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def connect(self) -> None:
        self.events.append(("connect", None))

    def send_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> object:
        self.events.append(("send", code))
        return SimpleNamespace(time_s=time_s)

    def send_prevalidated_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> None:
        self.events.append(("send_prevalidated", code))

    def close(self) -> None:
        self.events.append(("backend_closed", None))


def _fake_psychopy(
    events: list[tuple[str, object]],
    *,
    actual_frame_rate: float | None = 10.0,
) -> tuple[object, object, object]:
    state: dict[str, _FakeWindow] = {}

    def window_factory(**kwargs: object) -> _FakeWindow:
        window = _FakeWindow(
            events,
            actual_frame_rate=actual_frame_rate,
            **kwargs,
        )
        state["window"] = window
        return window

    def stim_factory(window: _FakeWindow, **kwargs: object) -> _FakeStim:
        return _FakeStim(events, **kwargs)

    visual = SimpleNamespace(Window=window_factory, TextStim=stim_factory)
    core = SimpleNamespace(Clock=lambda: _FakeClock(state["window"]))
    keyboard = SimpleNamespace(Keyboard=_FakeKeyboard)
    return visual, core, keyboard


def _settings(output_folder) -> TaskSettings:
    return TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=0.2,
        total_epochs=2,
        trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        output_folder=output_folder,
        random_seed=4,
    )


def test_runner_preflights_then_sends_every_cue_on_its_visible_flip(tmp_path) -> None:
    events: list[tuple[str, object]] = []
    progress: list[tuple[int, int]] = []

    result = run_participant_task(
        _settings(tmp_path),
        trigger_backend=_FakeBackend(events),
        progress_callback=lambda completed, total: progress.append((completed, total)),
        psychopy_modules=_fake_psychopy(events),
    )

    assert result.aborted is False
    assert result.completed_epochs == 2
    assert {event.cue for event in result.events} == {
        CueTarget.LEFT_HAND,
        CueTarget.RIGHT_HAND,
    }
    assert [event.trigger_code for event in result.events] == [
        epoch.trigger_code for epoch in result.schedule
    ]
    assert all(event.trigger_succeeded for event in result.events)
    assert [event.observed_duration_sec for event in result.events] == pytest.approx(
        [0.2, 0.2]
    )
    assert all(event.completed for event in result.events)
    assert progress == [(0, 2), (1, 2), (2, 2)]

    event_names = [name for name, _ in events]
    assert event_names.index("connect") < event_names.index("window_created")
    for call_index, (name, code) in enumerate(events):
        if name != "call_on_flip":
            continue
        flip_index = next(
            index for index in range(call_index + 1, len(events)) if events[index][0] == "flip"
        )
        send_index = next(
            index
            for index in range(flip_index + 1, len(events))
            if events[index] == ("send_prevalidated", code)
        )
        assert call_index < flip_index < send_index

    flip_indexes = [
        index for index, (name, _) in enumerate(events) if name == "flip"
    ]
    assert len(flip_indexes) == 6  # ready screen + 2 frames/cue + terminal blank
    assert not any(
        name == "draw"
        for name, _ in events[flip_indexes[-2] + 1 : flip_indexes[-1]]
    )

    assert result.log_path is not None and result.log_path.exists()
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["cue"] for row in rows} == {"left_hand", "right_hand"}
    assert all(row["trigger_succeeded"] == "True" for row in rows)
    assert {row["epoch_duration_sec"] for row in rows} == {"0.2"}
    assert {row["total_epochs"] for row in rows} == {"2"}
    assert {row["serial_port"] for row in rows} == {"COM3"}


def test_escape_at_start_aborts_before_any_trigger(tmp_path) -> None:
    events: list[tuple[str, object]] = []
    visual, core, _ = _fake_psychopy(events)

    class EscapeKeyboard(_FakeKeyboard):
        def getKeys(self, *, keyList: list[str], **kwargs: object) -> list[object]:  # noqa: N802
            return [SimpleNamespace(name="escape")]

    result = run_participant_task(
        _settings(tmp_path),
        trigger_backend=_FakeBackend(events),
        psychopy_modules=(visual, core, SimpleNamespace(Keyboard=EscapeKeyboard)),
    )

    assert result.aborted is True
    assert result.events == ()
    assert not any(name.startswith("send") for name, _ in events)
    assert result.log_path is not None and result.log_path.exists()


def test_application_shutdown_at_ready_screen_aborts_before_any_trigger(tmp_path) -> None:
    events: list[tuple[str, object]] = []

    result = run_participant_task(
        _settings(tmp_path),
        trigger_backend=_FakeBackend(events),
        abort_requested=lambda: True,
        psychopy_modules=_fake_psychopy(events),
    )

    assert result.aborted is True
    assert result.abort_reason == "Application shutdown requested before the task started."
    assert result.events == ()
    assert not any(name.startswith("send") for name, _ in events)
    assert events[-2:] == [("window_closed", None), ("backend_closed", None)]


def test_application_shutdown_during_cue_closes_it_and_suppresses_later_triggers(
    tmp_path,
) -> None:
    events: list[tuple[str, object]] = []
    shutdown = {"requested": False}

    class ShutdownAfterFirstTriggerBackend(_FakeBackend):
        def send_prevalidated_trigger(
            self,
            code: int,
            *,
            label: str | None = None,
            time_s: float | None = None,
            epoch_index: int | None = None,
        ) -> None:
            super().send_prevalidated_trigger(
                code,
                label=label,
                time_s=time_s,
                epoch_index=epoch_index,
            )
            shutdown["requested"] = True

    result = run_participant_task(
        _settings(tmp_path),
        trigger_backend=ShutdownAfterFirstTriggerBackend(events),
        abort_requested=lambda: shutdown["requested"],
        psychopy_modules=_fake_psychopy(events),
    )

    assert result.aborted is True
    assert result.abort_reason == "Application shutdown requested during a cue epoch."
    assert len(result.events) == 1
    assert result.events[0].completed is False
    assert result.events[0].cue_offset_time_sec is not None
    assert result.events[0].observed_duration_sec == pytest.approx(0.0)
    assert sum(name == "send_prevalidated" for name, _ in events) == 1


def test_serial_preflight_failure_happens_before_window_creation(tmp_path) -> None:
    events: list[tuple[str, object]] = []

    class FailingBackend(_FakeBackend):
        def connect(self) -> None:
            self.events.append(("connect", None))
            raise SerialTriggerError("COM3 is unavailable")

    with pytest.raises(SerialTriggerError, match="COM3 is unavailable"):
        run_participant_task(
            _settings(tmp_path),
            trigger_backend=FailingBackend(events),
            psychopy_modules=_fake_psychopy(events),
        )

    assert not any(name == "window_created" for name, _ in events)
    assert events == [("connect", None), ("backend_closed", None)]


def test_runner_stops_when_refresh_rate_cannot_be_measured(tmp_path) -> None:
    events: list[tuple[str, object]] = []

    with pytest.raises(RuntimeError, match="refresh rate"):
        run_participant_task(
            _settings(tmp_path),
            trigger_backend=_FakeBackend(events),
            psychopy_modules=_fake_psychopy(events, actual_frame_rate=None),
        )

    assert not any(name.startswith("send") for name, _ in events)
    assert events[-2:] == [("window_closed", None), ("backend_closed", None)]


def test_epoch_duration_rounds_up_to_a_whole_display_frame(tmp_path) -> None:
    events: list[tuple[str, object]] = []
    settings = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=0.21,
        total_epochs=2,
        trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        output_folder=tmp_path,
        random_seed=4,
    )

    result = run_participant_task(
        settings,
        trigger_backend=_FakeBackend(events),
        psychopy_modules=_fake_psychopy(events, actual_frame_rate=10.0),
    )

    assert [event.observed_duration_sec for event in result.events] == pytest.approx(
        [0.3, 0.3]
    )


def test_unwritable_log_path_fails_before_serial_or_window(tmp_path) -> None:
    events: list[tuple[str, object]] = []
    file_path = tmp_path / "not_a_folder"
    file_path.write_text("occupied", encoding="utf-8")

    with pytest.raises(RuntimeError, match="task log folder"):
        run_participant_task(
            _settings(file_path),
            trigger_backend=_FakeBackend(events),
            psychopy_modules=_fake_psychopy(events),
        )

    assert events == []


def test_trigger_write_failure_aborts_without_presenting_later_cues(tmp_path) -> None:
    events: list[tuple[str, object]] = []

    class FailingBackend(_FakeBackend):
        def send_prevalidated_trigger(
            self,
            code: int,
            *,
            label: str | None = None,
            time_s: float | None = None,
            epoch_index: int | None = None,
        ) -> object:
            self.events.append(("send_prevalidated_failed", code))
            raise SerialTriggerError("one-byte write failed")

    result = run_participant_task(
        _settings(tmp_path),
        trigger_backend=FailingBackend(events),
        psychopy_modules=_fake_psychopy(events),
    )

    assert result.aborted is True
    assert "one-byte write failed" in (result.abort_reason or "")
    assert len(result.events) == 1
    assert result.events[0].trigger_succeeded is False
    assert sum(name == "call_on_flip" for name, _ in events) == 1
    assert result.log_path is not None and result.log_path.exists()
