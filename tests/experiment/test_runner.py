from __future__ import annotations

import csv
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from sssep_batch.experiment.models import (
    CUE_PROMPTS,
    CueTarget,
    CueTriggerCodes,
    TaskCondition,
    TaskSettings,
)
from sssep_batch.experiment.runner import (
    READY_PROMPT,
    TEST_MODE_READY_PROMPT,
    QtTaskRunner,
    _FrameCallbackGate,
)
from sssep_batch.experiment.triggers import SerialTriggerError


class _FakeMonotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _FakeSurface:
    def __init__(
        self,
        events: list[tuple[str, object]],
        on_space: Callable[[], None],
        on_escape: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.events = events
        self._on_space = on_space
        self._on_escape = on_escape
        self._on_error = on_error
        self._visible_callback: Callable[[], None] | None = None
        self._visible_text: str | None = None
        self._scheduled_callback: Callable[[], None] | None = None
        self.scheduled_delay: float | None = None
        self.finished = False

    def show_ready(self, text: str, on_visible: Callable[[], None]) -> None:
        self.events.append(("show_ready", text))
        self._queue_frame(text, on_visible)

    def present(self, text: str, on_visible: Callable[[], None]) -> None:
        self.events.append(("present", text))
        self._queue_frame(text, on_visible)

    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> None:
        assert self._scheduled_callback is None
        self.events.append(("schedule", delay_seconds))
        self.scheduled_delay = delay_seconds
        self._scheduled_callback = callback

    def cancel_scheduled(self) -> None:
        self.events.append(("cancel_scheduled", None))
        self.scheduled_delay = None
        self._scheduled_callback = None

    def finish(self) -> None:
        self.events.append(("surface_finished", None))
        self.finished = True
        self._visible_callback = None
        self._visible_text = None
        self.cancel_scheduled()

    def swap(self) -> None:
        callback = self._visible_callback
        assert callback is not None, "No requested frame is waiting to become visible."
        text = self._visible_text
        self._visible_callback = None
        self._visible_text = None
        self.events.append(("swap", text))
        callback()

    def fire_scheduled(self) -> None:
        callback = self._scheduled_callback
        assert callback is not None, "No cue timer is pending."
        self._scheduled_callback = None
        self.scheduled_delay = None
        self.events.append(("timer_fired", None))
        callback()

    def press_space(self) -> None:
        self.events.append(("space", None))
        self._on_space()

    def press_escape(self) -> None:
        self.events.append(("escape", None))
        self._on_escape()

    def fail(self, exc: Exception) -> None:
        self._on_error(exc)

    def _queue_frame(self, text: str, callback: Callable[[], None]) -> None:
        assert self._visible_callback is None
        self._visible_text = text
        self._visible_callback = callback


class _FakeSurfaceFactory:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.surface: _FakeSurface | None = None

    def __call__(
        self,
        on_space: Callable[[], None],
        on_escape: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> _FakeSurface:
        self.events.append(("surface_created", None))
        self.surface = _FakeSurface(
            self.events,
            on_space,
            on_escape,
            on_error,
        )
        return self.surface


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


def _settings(output_folder) -> TaskSettings:
    return TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=0.2,
        total_epochs=2,
        trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        output_folder=output_folder,
        random_seed=4,
    )


def _start_runner(
    settings: TaskSettings,
    *,
    backend: _FakeBackend | None = None,
    clock: _FakeMonotonic | None = None,
):
    events: list[tuple[str, object]] = []
    clock = clock or _FakeMonotonic()
    surface_factory = _FakeSurfaceFactory(events)
    if backend is None:
        backend = _FakeBackend(events)
    else:
        backend.events = events

    results = []
    failures: list[Exception] = []
    progress: list[tuple[int, int]] = []
    done: list[bool] = []
    runner = QtTaskRunner(
        trigger_backend=backend,
        surface_factory=surface_factory,
        monotonic=clock,
    )
    runner.progress_changed.connect(
        lambda completed, total: progress.append((completed, total))
    )
    runner.task_finished.connect(results.append)
    runner.task_failed.connect(failures.append)
    runner.task_done.connect(lambda: done.append(True))
    runner.start(settings)
    return (
        runner,
        surface_factory,
        clock,
        events,
        results,
        failures,
        progress,
        done,
    )


def test_frame_callback_gate_ignores_incidental_and_duplicate_swaps() -> None:
    gate = _FrameCallbackGate()
    callbacks: list[str] = []

    first_generation = gate.request(lambda: callbacks.append("first"))
    assert gate.take_swapped_callback() is None
    gate.mark_painted(first_generation - 1)
    assert gate.take_swapped_callback() is None

    gate.mark_painted(first_generation)
    first_callback = gate.take_swapped_callback()
    assert first_callback is not None
    first_callback()
    assert gate.take_swapped_callback() is None
    assert callbacks == ["first"]

    second_generation = gate.request(lambda: callbacks.append("second"))
    with pytest.raises(RuntimeError, match="already pending"):
        gate.request(lambda: None)
    gate.mark_painted(first_generation)
    assert gate.take_swapped_callback() is None
    gate.mark_painted(second_generation)
    second_callback = gate.take_swapped_callback()
    assert second_callback is not None
    second_callback()
    assert gate.take_swapped_callback() is None
    assert callbacks == ["first", "second"]

    cancelled_generation = gate.request(lambda: callbacks.append("cancelled"))
    gate.cancel()
    gate.mark_painted(cancelled_generation)
    assert gate.take_swapped_callback() is None
    assert callbacks == ["first", "second"]


def test_runner_preflights_then_sends_each_trigger_after_its_visible_swap(
    tmp_path,
) -> None:
    (
        runner,
        factory,
        clock,
        events,
        results,
        failures,
        progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    runner.progress_changed.connect(
        lambda completed, _total: events.append(("progress_signal", completed))
    )
    surface = factory.surface
    assert surface is not None

    assert [name for name, _ in events[:3]] == [
        "connect",
        "surface_created",
        "show_ready",
    ]
    assert events[2] == ("show_ready", READY_PROMPT)

    surface.press_space()
    assert progress == []
    assert not any(name.startswith("send") for name, _ in events)

    surface.swap()
    surface.press_space()
    assert progress == [(0, 2)]
    assert not any(name.startswith("send") for name, _ in events)

    clock.advance(0.1)
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(0.2)

    clock.advance(0.2)
    surface.fire_scheduled()
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(0.2)

    clock.advance(0.2)
    surface.fire_scheduled()
    assert events[-1] == ("present", "")
    assert results == []
    surface.swap()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
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

    cue_prompts = {CUE_PROMPTS[epoch.cue] for epoch in result.schedule}
    assert {
        value for name, value in events if name == "present" and value
    } == cue_prompts
    assert sum(name == "send_prevalidated" for name, _ in events) == 2
    assert sum(name == "swap" for name, _ in events) == 4
    for send_index, (name, code) in enumerate(events):
        if name != "send_prevalidated":
            continue
        prior_swaps = [
            index
            for index, (prior_name, _) in enumerate(events[:send_index])
            if prior_name == "swap"
        ]
        assert prior_swaps
        assert events[prior_swaps[-1] + 1] == ("send_prevalidated", code)

    assert result.log_path is not None and result.log_path.exists()
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["cue"] for row in rows} == {"left_hand", "right_hand"}
    assert all(row["trigger_succeeded"] == "True" for row in rows)
    assert {row["epoch_duration_sec"] for row in rows} == {"0.2"}
    assert {row["total_epochs"] for row in rows} == {"2"}
    assert {row["test_mode"] for row in rows} == {"False"}
    assert {row["serial_port"] for row in rows} == {"COM3"}


def test_runner_test_mode_skips_com3_and_marks_the_ready_screen(
    monkeypatch,
    tmp_path,
) -> None:
    events: list[tuple[str, object]] = []
    factory = _FakeSurfaceFactory(events)
    failures: list[Exception] = []
    results = []
    done: list[bool] = []
    settings = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=0.2,
        total_epochs=2,
        trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        output_folder=tmp_path,
        random_seed=4,
        test_mode=True,
    )

    def fail_serial_backend(*_args, **_kwargs):
        pytest.fail("Test mode attempted to create the COM3 backend.")

    monkeypatch.setattr(
        "sssep_batch.experiment.runner.SerialTriggerBackend",
        fail_serial_backend,
    )
    runner = QtTaskRunner(
        surface_factory=factory,
        monotonic=_FakeMonotonic(),
    )
    runner.task_failed.connect(failures.append)
    runner.task_finished.connect(results.append)
    runner.task_done.connect(lambda: done.append(True))

    runner.start(settings)

    surface = factory.surface
    assert surface is not None
    assert events[1] == ("show_ready", TEST_MODE_READY_PROMPT)
    surface.swap()
    surface.press_space()
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(0.2)
    runner.request_stop()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    assert results[0].settings.test_mode is True
    with results[0].log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["test_mode"] for row in rows} == {"True"}


def test_epoch_timer_compensates_for_trigger_callback_time(tmp_path) -> None:
    clock = _FakeMonotonic()

    class AdvancingBackend(_FakeBackend):
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
            clock.advance(0.03)

    backend = AdvancingBackend([])
    (
        _runner,
        factory,
        _clock,
        _events,
        _results,
        failures,
        _progress,
        _done,
    ) = _start_runner(_settings(tmp_path), backend=backend, clock=clock)
    surface = factory.surface
    assert surface is not None
    surface.swap()
    surface.press_space()
    clock.advance(0.1)
    surface.swap()

    assert failures == []
    assert surface.scheduled_delay == pytest.approx(0.17)


def test_escape_from_ready_screen_aborts_before_any_trigger(tmp_path) -> None:
    (
        _runner,
        factory,
        _clock,
        events,
        results,
        failures,
        progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    surface = factory.surface
    assert surface is not None
    surface.swap()
    surface.press_escape()

    assert failures == []
    assert done == [True]
    assert progress == []
    assert len(results) == 1
    result = results[0]
    assert result.aborted is True
    assert result.abort_reason == "Escape pressed before the task started."
    assert result.events == ()
    assert not any(name.startswith("send") for name, _ in events)
    assert result.log_path is not None and result.log_path.exists()


def test_application_shutdown_at_ready_screen_aborts_before_any_trigger(
    tmp_path,
) -> None:
    (
        runner,
        factory,
        _clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    assert factory.surface is not None

    runner.request_stop()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
    assert result.aborted is True
    assert result.abort_reason == "Application shutdown requested before the task started."
    assert result.events == ()
    assert not any(name.startswith("send") for name, _ in events)
    assert events[-3:] == [
        ("surface_finished", None),
        ("cancel_scheduled", None),
        ("backend_closed", None),
    ]


def test_application_shutdown_during_cue_closes_it_and_suppresses_later_triggers(
    tmp_path,
) -> None:
    (
        runner,
        factory,
        clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    surface = factory.surface
    assert surface is not None
    surface.swap()
    surface.press_space()
    clock.advance(0.1)
    surface.swap()

    clock.advance(0.05)
    runner.request_stop()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
    assert result.aborted is True
    assert result.abort_reason == "Application shutdown requested during a cue epoch."
    assert len(result.events) == 1
    assert result.events[0].completed is False
    assert result.events[0].cue_offset_time_sec == pytest.approx(0.15)
    assert result.events[0].observed_duration_sec == pytest.approx(0.05)
    assert sum(name == "send_prevalidated" for name, _ in events) == 1
    assert surface.scheduled_delay is None


def test_serial_preflight_failure_happens_before_surface_creation(tmp_path) -> None:
    events: list[tuple[str, object]] = []

    class FailingBackend(_FakeBackend):
        def connect(self) -> None:
            self.events.append(("connect", None))
            raise SerialTriggerError("COM3 is unavailable")

    backend = FailingBackend(events)
    (
        _runner,
        factory,
        _clock,
        observed_events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path), backend=backend)

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert isinstance(failures[0], SerialTriggerError)
    assert "COM3 is unavailable" in str(failures[0])
    assert factory.surface is None
    assert observed_events == [("connect", None), ("backend_closed", None)]


def test_presentation_surface_failure_stops_before_any_trigger(tmp_path) -> None:
    (
        _runner,
        factory,
        _clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    surface = factory.surface
    assert surface is not None

    surface.fail(RuntimeError("participant frame was not presented"))

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert "frame was not presented" in str(failures[0])
    assert not any(name.startswith("send") for name, _ in events)
    assert events[-3:] == [
        ("surface_finished", None),
        ("cancel_scheduled", None),
        ("backend_closed", None),
    ]


def test_active_presentation_failure_preserves_partial_task_log(tmp_path) -> None:
    (
        _runner,
        factory,
        clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    surface = factory.surface
    assert surface is not None
    surface.swap()
    surface.press_space()
    clock.advance(0.1)
    surface.swap()
    clock.advance(0.05)

    surface.fail(RuntimeError("participant frame failed"))

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert "participant frame failed" in str(failures[0])
    assert "Partial task log:" in str(failures[0])
    assert sum(name == "send_prevalidated" for name, _ in events) == 1

    logs = list(tmp_path.glob("sssep_task_events_*.csv"))
    assert len(logs) == 1
    with logs[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["completed"] == "False"
    assert rows[0]["trigger_succeeded"] == "True"
    assert float(rows[0]["observed_duration_sec"]) == pytest.approx(0.05)
    assert all(row["run_aborted"] == "True" for row in rows)
    assert all(row["abort_reason"] == "participant frame failed" for row in rows)


def test_cleanup_closes_backend_when_surface_finish_fails(tmp_path) -> None:
    (
        runner,
        factory,
        _clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path))
    surface = factory.surface
    assert surface is not None

    def fail_finish() -> None:
        events.append(("surface_finish_failed", None))
        raise RuntimeError("surface close failed")

    surface.finish = fail_finish  # type: ignore[method-assign]
    runner.request_stop()

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert str(failures[0]) == "surface close failed"
    assert events[-2:] == [
        ("surface_finish_failed", None),
        ("backend_closed", None),
    ]


def test_unwritable_log_path_fails_before_serial_or_surface(tmp_path) -> None:
    file_path = tmp_path / "not_a_folder"
    file_path.write_text("occupied", encoding="utf-8")
    (
        _runner,
        factory,
        _clock,
        events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(file_path))

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert "task log folder" in str(failures[0])
    assert factory.surface is None
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
        ) -> None:
            self.events.append(("send_prevalidated_failed", code))
            raise SerialTriggerError("one-byte write failed")

    backend = FailingBackend(events)
    (
        _runner,
        factory,
        clock,
        observed_events,
        results,
        failures,
        _progress,
        done,
    ) = _start_runner(_settings(tmp_path), backend=backend)
    surface = factory.surface
    assert surface is not None
    surface.swap()
    surface.press_space()
    clock.advance(0.1)
    surface.swap()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
    assert result.aborted is True
    assert "one-byte write failed" in (result.abort_reason or "")
    assert len(result.events) == 1
    assert result.events[0].trigger_succeeded is False
    assert result.events[0].completed is False
    assert result.events[0].observed_duration_sec == pytest.approx(0.0)
    assert sum(name == "send_prevalidated_failed" for name, _ in observed_events) == 1
    assert not any(name == "schedule" for name, _ in observed_events)
    assert result.log_path is not None and result.log_path.exists()
