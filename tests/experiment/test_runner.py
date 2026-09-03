from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import replace
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
    BEGIN_DURATION_SEC,
    BEGIN_PROMPT,
    CONDITION_CONFIRM_PROMPT,
    CONDITION_HANDOVER_PROMPT,
    END_DURATION_SEC,
    END_PROMPT,
    READY_PROMPT,
    TEST_MODE_READY_PROMPT,
    QtTaskRunner,
    _FrameCallbackGate,
    _QtCueWindow,
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
        on_confirm: Callable[[], None],
        on_escape: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.events = events
        self._on_space = on_space
        self._on_confirm = on_confirm
        self._on_escape = on_escape
        self._on_error = on_error
        self._visible_callback: Callable[[], None] | None = None
        self._visible_text: str | None = None
        self._scheduled_callback: Callable[[], None] | None = None
        self.scheduled_delay: float | None = None
        self.presented_durations: list[float | None] = []
        self.finished = False

    def show_ready(self, text: str, on_visible: Callable[[], None]) -> None:
        self.events.append(("show_ready", text))
        self._queue_frame(text, on_visible)

    def present(
        self, text: str, on_visible: Callable[[], None], *,
        duration_sec: float | None = None,
    ) -> None:
        self.events.append(("present", text))
        self.presented_durations.append(duration_sec)
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

    def press_confirm(self) -> None:
        self.events.append(("confirm", None))
        self._on_confirm()

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
        on_confirm: Callable[[], None],
        on_escape: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> _FakeSurface:
        self.events.append(("surface_created", None))
        self.surface = _FakeSurface(
            self.events,
            on_space,
            on_confirm,
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
        epoch_duration_sec=0.2,
        epochs_per_condition=2,
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


def _start_first_cue(
    surface: _FakeSurface, clock: _FakeMonotonic, *, cue_swap_delay: float = 0.0,
) -> None:
    """Advance the ready screen and full five-second preparation period."""
    surface.swap()
    surface.press_space()
    assert surface._visible_text == BEGIN_PROMPT
    assert surface.scheduled_delay is None
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(5.0)
    clock.advance(5.0)
    surface.fire_scheduled()
    clock.advance(cue_swap_delay)
    surface.swap()


def _show_handover(surface: _FakeSurface, clock: _FakeMonotonic) -> None:
    """Complete the two short both-hands epochs used by the safety checks."""
    _start_first_cue(surface, clock)
    clock.advance(0.2)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(10.0)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(0.2)
    surface.fire_scheduled()
    assert surface._visible_text == CONDITION_HANDOVER_PROMPT
    surface.swap()
    assert surface.scheduled_delay is None


def _request_end_screen(surface: _FakeSurface, clock: _FakeMonotonic) -> None:
    """Complete both conditions, stopping before the end frame becomes visible."""
    _show_handover(surface, clock)
    surface.press_space()
    surface.swap()
    surface.press_confirm()
    surface.swap()
    clock.advance(0.2)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(10.0)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(0.2)
    surface.fire_scheduled()
    assert surface._visible_text == END_PROMPT


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
    assert BEGIN_DURATION_SEC == END_DURATION_SEC == 5.0
    (
        runner,
        factory,
        clock,
        events,
        results,
        failures,
        progress,
        done,
    ) = _start_runner(replace(_settings(tmp_path), epoch_duration_sec=15.0))
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
    surface.press_confirm()
    assert progress == []
    assert not any(name.startswith("send") for name, _ in events)

    surface.swap()
    surface.press_space()
    assert progress == [(0, 4)]
    assert not any(name.startswith("send") for name, _ in events)
    assert surface._visible_text == BEGIN_PROMPT
    assert surface.scheduled_delay is None

    surface.press_space()
    surface.press_confirm()
    assert surface._visible_text == BEGIN_PROMPT
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(5.0)
    clock.advance(4.9)
    surface.press_space()
    surface.press_confirm()
    assert surface._visible_callback is None
    assert not any(name.startswith("send") for name, _ in events)
    clock.advance(0.1)
    surface.fire_scheduled()
    assert not any(name.startswith("send") for name, _ in events)

    clock.advance(0.1)
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(15.0)

    clock.advance(15.0)
    surface.fire_scheduled()
    assert events[-1] == ("present", "Now let's take a short break.")
    assert progress == [(0, 4)]
    clock.advance(0.01)  # Cue remains visible until the break frame swaps.
    surface.swap()
    assert progress == [(0, 4), (1, 4)]
    assert surface.scheduled_delay == pytest.approx(10.0)
    assert sum(name == "send_prevalidated" for name, _ in events) == 1

    clock.advance(10.0)
    surface.fire_scheduled()
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(15.0)

    clock.advance(15.0)
    surface.fire_scheduled()
    assert events[-1] == ("present", CONDITION_HANDOVER_PROMPT)
    assert surface.scheduled_delay is None
    surface.press_space()
    surface.press_confirm()
    assert surface._visible_text == CONDITION_HANDOVER_PROMPT
    clock.advance(0.02)
    surface.swap()
    assert progress == [(0, 4), (1, 4), (2, 4)]
    assert surface.scheduled_delay is None

    # An administrator can take arbitrarily long; no cue timer or marker runs.
    clock.advance(60.0)
    surface.press_confirm()
    assert surface._visible_callback is None
    assert sum(name == "send_prevalidated" for name, _ in events) == 3
    surface.press_space()
    assert surface._visible_text == CONDITION_CONFIRM_PROMPT
    surface.press_space()
    surface.press_confirm()
    assert surface._visible_text == CONDITION_CONFIRM_PROMPT
    clock.advance(2.0)
    surface.swap()
    assert surface.scheduled_delay is None
    surface.press_space()
    assert surface._visible_callback is None
    surface.press_confirm()
    next_prompt = surface._visible_text
    surface.press_confirm()
    surface.press_space()
    assert surface._visible_text == next_prompt
    assert sum(name == "send_prevalidated" for name, _ in events) == 3
    clock.advance(0.03)
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(15.0)

    clock.advance(15.0)
    surface.fire_scheduled()
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(10.0)
    clock.advance(10.0)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(15.0)
    surface.fire_scheduled()
    assert events[-1] == ("present", END_PROMPT)
    assert results == []
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(5.0)
    assert not surface.finished
    clock.advance(4.9)
    surface.press_space()
    surface.press_confirm()
    assert results == []
    assert not surface.finished
    clock.advance(0.1)
    surface.fire_scheduled()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
    assert result.aborted is False
    assert result.completed_epochs == 4
    assert {event.cue for event in result.events} == {
        CueTarget.LEFT_HAND,
        CueTarget.RIGHT_HAND,
        CueTarget.RIGHT_ANKLE,
    }
    assert [event.trigger_code for event in result.events] == [
        epoch.trigger_code for epoch in result.schedule
    ]
    assert all(event.trigger_succeeded for event in result.events)
    assert [event.observed_duration_sec for event in result.events] == pytest.approx(
        [15.01, 15.02, 15.0, 15.0]
    )
    assert [event.cue_onset_time_sec for event in result.events] == pytest.approx(
        [5.1, 30.11, 107.16, 132.16]
    )
    assert [epoch.scheduled_onset_sec for epoch in result.schedule] == [0.0, 25.0, 0.0, 25.0]
    assert [event.condition for event in result.events] == [
        TaskCondition.BOTH_HANDS, TaskCondition.BOTH_HANDS,
        TaskCondition.RIGHT_HAND_AND_ANKLE, TaskCondition.RIGHT_HAND_AND_ANKLE,
    ]
    assert all(event.completed for event in result.events)
    assert progress == [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4)]

    cue_prompts = {CUE_PROMPTS[epoch.cue] for epoch in result.schedule}
    assert {
        value for name, value in events if name == "present" and value
    } == cue_prompts | {
        "Now let's take a short break.", CONDITION_HANDOVER_PROMPT, CONDITION_CONFIRM_PROMPT,
        BEGIN_PROMPT, END_PROMPT,
    }
    assert sorted(code for name, code in events if name == "send_prevalidated") == [
        11, 12, 21, 22, 100, 100,
    ]
    assert sum(name == "connect" for name, _ in events) == 1
    assert sum(name == "backend_closed" for name, _ in events) == 1
    assert sum(name == "swap" for name, _ in events) == 11
    assert surface.presented_durations == [
        5.0, 15.0, 10.0, 15.0, None, None, 15.0, 10.0, 15.0, 5.0,
    ]
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
    assert len(rows) == 4
    assert {row["cue"] for row in rows} == {"left_hand", "right_hand", "right_ankle"}
    assert all(row["trigger_succeeded"] == "True" for row in rows)
    assert {row["epoch_duration_sec"] for row in rows} == {"15.0"}
    assert {row["total_epochs"] for row in rows} == {"4"}
    assert {row["epochs_per_condition"] for row in rows} == {"2"}
    assert [row["condition_epoch_number"] for row in rows] == ["1", "2", "1", "2"]
    assert {row["scheduled_onset_reference"] for row in rows} == {"condition_start"}
    assert [float(row["cue_onset_time_sec"]) for row in rows] == pytest.approx(
        [5.1, 30.11, 107.16, 132.16]
    )
    assert {row["test_mode"] for row in rows} == {"False"}
    assert {row["show_timer"] for row in rows} == {"True"}
    assert {row["serial_port"] for row in rows} == {"COM3"}
    assert {row["break_duration_sec"] for row in rows} == {"10.0"}
    assert {row["break_prompt"] for row in rows} == {"Now let's take a short break."}
    assert [row["condition_end_trigger_code"] for row in rows] == ["", "100", "", "100"]
    assert [row["condition_end_trigger_succeeded"] for row in rows] == [
        "", "True", "", "True",
    ]
    assert all(row["condition_end_trigger_error"] == "" for row in rows)
    for index, event in enumerate(result.events):
        if index in (1, 3):
            assert event.condition_end_trigger_code == 100
            assert event.condition_end_trigger_succeeded is True
            assert event.condition_end_trigger_time_sec == pytest.approx(event.cue_offset_time_sec)
            assert float(rows[index]["condition_end_trigger_time_sec"]) == pytest.approx(
                event.cue_offset_time_sec
            )
        else:
            assert event.condition_end_trigger_code is None
            assert event.condition_end_trigger_time_sec is None
            assert event.condition_end_trigger_succeeded is None


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
        epoch_duration_sec=0.2,
        epochs_per_condition=2,
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
    clock = _FakeMonotonic()
    runner = QtTaskRunner(
        surface_factory=factory,
        monotonic=clock,
    )
    runner.task_failed.connect(failures.append)
    runner.task_finished.connect(results.append)
    runner.task_done.connect(lambda: done.append(True))

    runner.start(settings)

    surface = factory.surface
    assert surface is not None
    assert events[1] == ("show_ready", TEST_MODE_READY_PROMPT)
    _start_first_cue(surface, clock)
    assert surface.scheduled_delay == pytest.approx(0.2)
    runner.request_stop()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    assert results[0].settings.test_mode is True
    with results[0].log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["test_mode"] for row in rows} == {"True"}


@pytest.mark.parametrize("show_timer", [True, False])
def test_custom_prompts_and_breaks_preserve_every_cue_marker(tmp_path, show_timer):
    settings = replace(
        _settings(tmp_path),
        epochs_per_condition=6,
        break_duration_sec=0.7,
        left_hand_prompt="Attend to your left hand",
        right_hand_prompt="Attend to your right hand",
        right_ankle_prompt="Attend to your right ankle",
        break_prompt="Rest now, please.",
        show_timer=show_timer,
    )
    _, factory, clock, events, results, failures, progress, _ = _start_runner(settings)
    surface = factory.surface
    _start_first_cue(surface, clock)
    for index in range(settings.total_epochs):
        clock.advance(settings.epoch_duration_sec)
        surface.fire_scheduled()
        surface.swap()
        if index == settings.epochs_per_condition - 1:
            assert surface.scheduled_delay is None
            assert progress[-1] == (index + 1, settings.total_epochs)
            clock.advance(12.0)
            surface.press_space()
            surface.swap()
            surface.press_confirm()
            surface.swap()
        elif index < settings.total_epochs - 1:
            assert surface.scheduled_delay == pytest.approx(0.7)
            assert progress[-1] == (index + 1, settings.total_epochs)
            clock.advance(settings.break_duration_sec)
            surface.fire_scheduled()
            surface.swap()

    assert results == []
    assert surface.scheduled_delay == pytest.approx(5.0)
    clock.advance(5.0)
    surface.fire_scheduled()
    assert failures == []
    result = results[0]
    assert result.completed_epochs == 12
    expected_prompts = [BEGIN_PROMPT]
    for index, epoch in enumerate(result.schedule):
        if index == settings.epochs_per_condition:
            expected_prompts.extend([CONDITION_HANDOVER_PROMPT, CONDITION_CONFIRM_PROMPT])
        elif index:
            expected_prompts.append(settings.break_prompt)
        expected_prompts.append(settings.prompt_for(epoch.cue))
    expected_prompts.append(END_PROMPT)
    assert [text for name, text in events if name == "present"] == expected_prompts
    assert any(a.cue == b.cue for a, b in zip(result.schedule, result.schedule[1:]))
    assert [code for name, code in events if name == "send_prevalidated" and code != 100] == [
        settings.trigger_codes.code_for(epoch.condition, epoch.cue) for epoch in result.schedule
    ]
    assert sum(name == "send_prevalidated" and code == 100 for name, code in events) == 2
    if show_timer:
        assert surface.presented_durations.count(0.2) == 12
        assert surface.presented_durations.count(0.7) == 10
        assert surface.presented_durations.count(5.0) == 2
    else:
        assert all(duration is None for duration in surface.presented_durations)
    assert [duration for name, duration in events if name == "schedule"] == pytest.approx(
        [5.0] + ([0.2, 0.7] * 5 + [0.2]) * 2 + [5.0]
    )
    assert all(event.completed for event in result.events)
    assert [event.observed_duration_sec for event in result.events] == pytest.approx([0.2] * 12)
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["prompt"] for row in rows] == [epoch.prompt for epoch in result.schedule]
    assert {row["break_prompt"] for row in rows} == {"Rest now, please."}
    assert {row["break_duration_sec"] for row in rows} == {"0.7"}
    assert {row["show_timer"] for row in rows} == {str(show_timer)}


@pytest.mark.parametrize("stop_method", ["press_escape", "request_stop"])
def test_aborting_break_preserves_completed_cue_and_sends_no_later_marker(
    tmp_path, stop_method,
):
    runner, factory, clock, events, results, failures, progress, _ = _start_runner(
        _settings(tmp_path)
    )
    surface = factory.surface
    _start_first_cue(surface, clock)
    clock.advance(0.2)
    surface.fire_scheduled()
    surface.swap()
    clock.advance(3.0)
    getattr(surface if stop_method == "press_escape" else runner, stop_method)()

    assert failures == []
    assert surface.finished
    assert surface.scheduled_delay is None
    assert progress == [(0, 4), (1, 4)]
    result = results[0]
    assert result.aborted
    assert result.completed_epochs == 1
    assert len(result.events) == 1
    assert result.events[0].observed_duration_sec == pytest.approx(0.2)
    assert sum(name == "send_prevalidated" for name, _ in events) == 1
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["completed"] for row in rows] == ["True", "False", "False", "False"]
    assert rows[1]["cue_onset_time_sec"] == ""


@pytest.mark.parametrize("stage", ["handover", "confirmation"])
@pytest.mark.parametrize("stop_method", ["press_escape", "request_stop"])
def test_aborting_handover_preserves_condition_one_and_suppresses_condition_two(
    tmp_path, stage, stop_method,
):
    runner, factory, clock, events, results, failures, progress, done = _start_runner(
        _settings(tmp_path)
    )
    surface = factory.surface
    _show_handover(surface, clock)
    if stage == "confirmation":
        surface.press_space()
        surface.swap()
    clock.advance(90.0)
    getattr(surface if stop_method == "press_escape" else runner, stop_method)()
    surface.press_space()
    surface.press_confirm()

    assert failures == []
    assert done == [True]
    assert surface.finished
    assert surface.scheduled_delay is None
    assert progress == [(0, 4), (1, 4), (2, 4)]
    result = results[0]
    assert result.aborted
    assert result.completed_epochs == 2
    assert len(result.events) == 2
    assert [event.observed_duration_sec for event in result.events] == pytest.approx([0.2, 0.2])
    assert sorted(code for name, code in events if name == "send_prevalidated") == [11, 12, 100]
    assert sum(name == "backend_closed" for name, _ in events) == 1
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["completed"] for row in rows] == ["True", "True", "False", "False"]
    assert all(row["cue_onset_time_sec"] == "" for row in rows[2:])
    assert all(row["run_aborted"] == "True" for row in rows)


@pytest.mark.parametrize("stage", ["handover", "confirmation_pending", "confirmation"])
def test_handover_presentation_failure_keeps_completed_condition_in_partial_log(
    tmp_path, stage,
):
    _, factory, clock, events, results, failures, _, done = _start_runner(
        _settings(tmp_path)
    )
    surface = factory.surface
    _show_handover(surface, clock)
    if stage != "handover":
        surface.press_space()
    if stage == "confirmation":
        surface.swap()
    clock.advance(45.0)
    surface.fail(RuntimeError("handover display failed"))
    surface.press_space()
    surface.press_confirm()

    assert results == []
    assert done == [True]
    assert len(failures) == 1
    assert "handover display failed" in str(failures[0])
    assert "Partial task log:" in str(failures[0])
    assert surface.finished
    assert surface.scheduled_delay is None
    assert sorted(code for name, code in events if name == "send_prevalidated") == [11, 12, 100]
    assert sum(name == "backend_closed" for name, _ in events) == 1
    logs = list(tmp_path.glob("sssep_task_events_*.csv"))
    assert len(logs) == 1
    with logs[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["completed"] for row in rows] == ["True", "True", "False", "False"]
    assert [float(row["observed_duration_sec"]) for row in rows[:2]] == pytest.approx([0.2, 0.2])
    assert all(row["cue_onset_time_sec"] == "" for row in rows[2:])
    assert all(row["run_aborted"] == "True" for row in rows)


def test_held_y_before_confirmation_cannot_start_condition_two(tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    runner, factory, clock, events, _, _, _, _ = _start_runner(_settings(tmp_path))
    surface = factory.surface
    _show_handover(surface, clock)
    surface.press_space()
    window = SimpleNamespace(
        _on_space=surface.press_space,
        _on_confirm=surface.press_confirm,
        _on_escape=surface.press_escape,
        _run_callback=lambda callback: callback(),
    )

    def send_y(*, repeat=False):
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.NoModifier,
            "y", repeat, 1,
        )
        _QtCueWindow.keyPressEvent(window, event)
        assert event.isAccepted()

    send_y()  # Pressed too early, before the confirmation frame is visible.
    assert surface._visible_text == CONDITION_CONFIRM_PROMPT
    surface.swap()
    send_y(repeat=True)  # Holding that key must not accept the now-visible screen.
    assert surface._visible_callback is None
    assert surface.scheduled_delay is None
    assert sum(name == "send_prevalidated" for name, _ in events) == 3
    send_y()  # A fresh press after visibility starts the next cue.
    assert surface._visible_callback is not None
    assert sum(name == "send_prevalidated" for name, _ in events) == 3
    surface.swap()
    assert sum(name == "send_prevalidated" for name, _ in events) == 4
    runner.request_stop()


def test_repeated_space_is_ignored_but_escape_always_stops():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    calls = []
    window = SimpleNamespace(
        _on_space=lambda: calls.append("space"),
        _on_confirm=lambda: calls.append("confirm"),
        _on_escape=lambda: calls.append("escape"),
        _run_callback=lambda callback: callback(),
    )
    for key, repeat in [(Qt.Key.Key_Space, True), (Qt.Key.Key_Space, False), (Qt.Key.Key_Escape, True)]:
        event = QKeyEvent(
            QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "", repeat, 1,
        )
        _QtCueWindow.keyPressEvent(window, event)
        assert event.isAccepted()
    assert calls == ["space", "escape"]


def test_countdown_uses_swap_deadline_and_redraws_do_not_repeat_trigger(monkeypatch):
    clock = _FakeMonotonic()
    monkeypatch.setattr("sssep_batch.experiment.runner.perf_counter", clock)
    events = []
    gate = _FrameCallbackGate()
    surface = SimpleNamespace(
        _frame_gate=gate,
        _frame_watchdog=SimpleNamespace(stop=lambda: events.append("watchdog_stop")),
        _countdown_timer=SimpleNamespace(
            start=lambda: events.append("countdown_start"),
            stop=lambda: events.append("countdown_stop"),
        ),
        _phase_duration_sec=15.0,
        _countdown_deadline=None,
        _countdown_seconds=15,
        _allow_close=False,
        _error_reported=False,
        _run_callback=lambda callback: callback(),
        update=lambda: events.append("redraw"),
    )
    surface._refresh_countdown = lambda: _QtCueWindow._refresh_countdown(surface)

    def send_trigger():
        events.append("trigger")
        clock.advance(0.3)  # Slow serial request must not extend the countdown.

    generation = gate.request(send_trigger)
    _QtCueWindow._frame_swapped(surface)
    assert events == []  # No matching paint yet.
    gate.mark_painted(generation)
    _QtCueWindow._frame_swapped(surface)
    assert events.index("trigger") < events.index("countdown_start")
    assert surface._countdown_deadline == 115.0
    assert surface._countdown_seconds == 15

    clock.advance(1.0)
    surface._refresh_countdown()
    assert surface._countdown_seconds == 14
    _QtCueWindow._frame_swapped(surface)  # Countdown repaint's swap.
    assert surface._countdown_deadline == 115.0
    clock.advance(20.0)  # Late timer delivery clamps at zero instead of drifting.
    surface._refresh_countdown()
    assert surface._countdown_seconds == 0
    assert events[-1] == "countdown_stop"
    assert events.count("trigger") == 1
    assert events.count("countdown_start") == 1


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
    _start_first_cue(surface, clock, cue_swap_delay=0.1)

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
    _start_first_cue(surface, clock, cue_swap_delay=0.1)

    clock.advance(0.05)
    runner.request_stop()

    assert failures == []
    assert done == [True]
    assert len(results) == 1
    result = results[0]
    assert result.aborted is True
    assert result.abort_reason == "Application shutdown requested during the task."
    assert len(result.events) == 1
    assert result.events[0].completed is False
    assert result.events[0].cue_offset_time_sec == pytest.approx(5.15)
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
    _start_first_cue(surface, clock, cue_swap_delay=0.1)
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
    _start_first_cue(surface, clock, cue_swap_delay=0.1)

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
    assert [delay for name, delay in observed_events if name == "schedule"] == [5.0]
    assert result.log_path is not None and result.log_path.exists()


@pytest.mark.parametrize("stage", ["begin", "end"])
@pytest.mark.parametrize("visible", [False, True])
@pytest.mark.parametrize("stop_method", ["press_escape", "request_stop"])
def test_aborting_preparation_or_end_screen_stops_timers_and_preserves_markers(
    tmp_path, stage, visible, stop_method,
):
    runner, factory, clock, events, results, failures, _, done = _start_runner(
        _settings(tmp_path)
    )
    surface = factory.surface
    if stage == "begin":
        surface.swap()
        surface.press_space()
        assert surface._visible_text == BEGIN_PROMPT
    else:
        _request_end_screen(surface, clock)
    if visible:
        surface.swap()
        clock.advance(2.0)
    sends_before_abort = [item for item in events if item[0].startswith("send")]
    getattr(surface if stop_method == "press_escape" else runner, stop_method)()
    surface.press_space()
    surface.press_confirm()

    assert failures == []
    assert done == [True]
    assert surface.finished
    assert surface.scheduled_delay is None
    assert surface._visible_callback is None
    assert [item for item in events if item[0].startswith("send")] == sends_before_abort
    result = results[0]
    assert result.aborted
    if stage == "begin":
        assert result.events == ()
        assert sends_before_abort == []
    else:
        assert result.completed_epochs == (4 if visible else 3)
        assert sum(code == 100 for _, code in sends_before_abort) == (2 if visible else 1)
        if visible:
            assert result.events[-1].observed_duration_sec == pytest.approx(0.2)
        else:
            assert result.events[-1].condition_end_trigger_code is None


@pytest.mark.parametrize("failed_condition", [1, 2])
def test_condition_end_marker_failure_aborts_and_keeps_completed_epochs(
    tmp_path, failed_condition,
):
    class FailingEndBackend(_FakeBackend):
        end_count = 0

        def send_prevalidated_trigger(self, code, **kwargs):
            if code == 100:
                self.end_count += 1
                if self.end_count == failed_condition:
                    self.events.append(("send_prevalidated_failed", code))
                    raise SerialTriggerError("condition-end write failed")
            super().send_prevalidated_trigger(code, **kwargs)

    _, factory, clock, events, results, failures, _, done = _start_runner(
        _settings(tmp_path), backend=FailingEndBackend([])
    )
    surface = factory.surface
    if failed_condition == 1:
        _show_handover(surface, clock)
    else:
        _request_end_screen(surface, clock)
        surface.swap()

    assert failures == []
    assert done == [True]
    assert surface.finished
    assert surface.scheduled_delay is None
    result = results[0]
    assert result.aborted
    assert "condition-end write failed" in result.abort_reason
    assert result.completed_epochs == failed_condition * 2
    last = result.events[-1]
    assert last.completed
    assert last.trigger_succeeded
    assert last.condition_end_trigger_code == 100
    assert last.condition_end_trigger_succeeded is False
    assert last.condition_end_trigger_error == "condition-end write failed"
    assert last.condition_end_trigger_time_sec == pytest.approx(last.cue_offset_time_sec)
    assert last.observed_duration_sec == pytest.approx(0.2)
    assert events.count(("send_prevalidated_failed", 100)) == 1
    assert sum(name == "backend_closed" for name, _ in events) == 1
    failed_index = events.index(("send_prevalidated_failed", 100))
    assert events[failed_index - 1] == (
        "swap", CONDITION_HANDOVER_PROMPT if failed_condition == 1 else END_PROMPT,
    )
    assert not any(name.startswith("send") for name, _ in events[failed_index + 1:])
    with result.log_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = rows[failed_condition * 2 - 1]
    assert row["completed"] == "True"
    assert row["trigger_succeeded"] == "True"
    assert row["condition_end_trigger_code"] == "100"
    assert row["condition_end_trigger_succeeded"] == "False"
    assert row["condition_end_trigger_error"] == "condition-end write failed"
    assert float(row["condition_end_trigger_time_sec"]) == pytest.approx(last.cue_offset_time_sec)
    assert all(row["condition_end_trigger_code"] == "" for row in rows[failed_condition * 2:])


def test_end_screen_timer_compensates_for_marker_callback_time(tmp_path):
    clock = _FakeMonotonic()

    class SlowEndBackend(_FakeBackend):
        def send_prevalidated_trigger(self, code, **kwargs):
            super().send_prevalidated_trigger(code, **kwargs)
            if code == 100:
                clock.advance(0.03)

    _, factory, _, events, results, failures, _, _ = _start_runner(
        _settings(tmp_path), backend=SlowEndBackend([]), clock=clock,
    )
    surface = factory.surface
    _request_end_screen(surface, clock)
    surface.swap()
    assert surface.scheduled_delay == pytest.approx(4.97)
    assert results == []
    clock.advance(surface.scheduled_delay)
    surface.fire_scheduled()
    assert failures == []
    assert results[0].completed_epochs == 4
    assert results[0].events[-1].observed_duration_sec == pytest.approx(0.2)
    assert events.count(("send_prevalidated", 100)) == 2
