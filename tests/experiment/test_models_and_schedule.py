from __future__ import annotations

from collections import Counter

import pytest

from sssep_batch.config import BASELINE_EVENT_CODE, FMAX, FMIN
from sssep_batch.experiment.models import (
    CUE_PROMPTS,
    CueTarget,
    CueTriggerCodes,
    TaskCondition,
    TaskSettings,
    analysis_protocol_for_task,
)
from sssep_batch.experiment.schedule import build_cue_schedule
from sssep_batch.experiment.triggers import BIOSEMI_SERIAL_PORT


def _codes() -> CueTriggerCodes:
    return CueTriggerCodes(
        both_hands_left_hand=11,
        both_hands_right_hand=12,
        right_hand_and_ankle_right_hand=21,
        right_hand_and_ankle_right_ankle=22,
    )


@pytest.mark.parametrize("total_epochs", [0, -2, 1, 3, True])
def test_task_settings_require_a_positive_even_epoch_count(total_epochs: object) -> None:
    with pytest.raises(ValueError, match="positive even"):
        TaskSettings(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=1.0,
            total_epochs=total_epochs,  # type: ignore[arg-type]
            trigger_codes=_codes(),
        )


@pytest.mark.parametrize("field", ["epoch_duration_sec", "break_duration_sec"])
@pytest.mark.parametrize("duration", [0, -1.0, float("inf"), float("nan"), True, "1"])
def test_task_settings_require_positive_finite_durations(
    field: str, duration: object
) -> None:
    durations = {"epoch_duration_sec": 1.0, "break_duration_sec": 10.0}
    durations[field] = duration
    with pytest.raises(ValueError, match=f"{field} must be a finite number"):
        TaskSettings(
            condition=TaskCondition.BOTH_HANDS,
            total_epochs=2,
            trigger_codes=_codes(),
            **durations,
        )


@pytest.mark.parametrize(
    "field", ["left_hand_prompt", "right_hand_prompt", "right_ankle_prompt", "break_prompt"]
)
@pytest.mark.parametrize("prompt", ["", " \n\t ", None, 123])
def test_task_settings_reject_blank_or_nontext_prompts(field: str, prompt: object) -> None:
    with pytest.raises(ValueError, match=f"{field} must contain nonblank text"):
        TaskSettings(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=1.0,
            total_epochs=2,
            trigger_codes=_codes(),
            **{field: prompt},
        )


def test_task_defaults_use_ten_second_breaks_and_existing_cue_text() -> None:
    settings = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=15.0,
        total_epochs=10,
        trigger_codes=_codes(),
    )

    assert settings.break_duration_sec == 10.0
    assert settings.break_prompt == "Now let's take a short break."
    assert {cue: settings.prompt_for(cue) for cue in CueTarget} == CUE_PROMPTS


def test_task_serial_port_is_fixed_to_com3() -> None:
    settings = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=1.0,
        total_epochs=2,
        trigger_codes=_codes(),
    )

    assert BIOSEMI_SERIAL_PORT == "COM3"
    assert settings.serial_port == BIOSEMI_SERIAL_PORT
    with pytest.raises(TypeError, match="serial_port"):
        TaskSettings(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=1.0,
            total_epochs=2,
            trigger_codes=_codes(),
            serial_port="COM7",  # type: ignore[call-arg]
        )


def test_task_test_mode_is_explicit_and_boolean() -> None:
    normal = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=1.0,
        total_epochs=2,
        trigger_codes=_codes(),
    )
    test = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=1.0,
        total_epochs=2,
        trigger_codes=_codes(),
        test_mode=True,
    )

    assert normal.test_mode is False
    assert test.test_mode is True
    with pytest.raises(TypeError, match="test_mode"):
        TaskSettings(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=1.0,
            total_epochs=2,
            trigger_codes=_codes(),
            test_mode=1,  # type: ignore[arg-type]
        )


def test_trigger_codes_must_be_unique_normal_biosemi_codes() -> None:
    with pytest.raises(ValueError, match="unique"):
        CueTriggerCodes(1, 2, 3, 3)
    with pytest.raises(ValueError, match="1 to 255"):
        CueTriggerCodes(0, 2, 3, 4)
    with pytest.raises(ValueError, match="1 to 255"):
        CueTriggerCodes(1, 2, 3, 256)
    with pytest.raises(ValueError, match="reserved"):
        CueTriggerCodes(1, 2, 3, BASELINE_EVENT_CODE)


@pytest.mark.parametrize(
    ("condition", "expected_cues", "expected_codes"),
    [
        (
            TaskCondition.BOTH_HANDS,
            {CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND},
            {11, 12},
        ),
        (
            TaskCondition.RIGHT_HAND_AND_ANKLE,
            {CueTarget.RIGHT_HAND, CueTarget.RIGHT_ANKLE},
            {21, 22},
        ),
    ],
)
def test_schedule_is_balanced_and_uses_only_the_selected_condition(
    condition: TaskCondition,
    expected_cues: set[CueTarget],
    expected_codes: set[int],
) -> None:
    settings = TaskSettings(
        condition=condition,
        epoch_duration_sec=1.5,
        total_epochs=10,
        trigger_codes=_codes(),
        random_seed=314,
        break_duration_sec=0.75,
    )

    schedule = build_cue_schedule(settings)

    assert Counter(epoch.cue for epoch in schedule) == {
        cue: 5 for cue in expected_cues
    }
    assert {epoch.trigger_code for epoch in schedule} == expected_codes
    assert [epoch.epoch_index for epoch in schedule] == list(range(10))
    assert [epoch.scheduled_onset_sec for epoch in schedule] == [
        index * 2.25 for index in range(10)
    ]


@pytest.mark.parametrize("condition", list(TaskCondition))
def test_schedule_uses_custom_text_without_changing_cue_codes(
    condition: TaskCondition,
) -> None:
    settings = TaskSettings(
        condition=condition,
        epoch_duration_sec=1.0,
        total_epochs=2,
        trigger_codes=_codes(),
        left_hand_prompt="  Focus on your left hand  ",
        right_hand_prompt="  Focus on your right hand  ",
        right_ankle_prompt="  Focus on your ankle  ",
        break_prompt="  Rest until the next cue.  ",
    )

    schedule = build_cue_schedule(settings)
    expected_prompts = {
        CueTarget.LEFT_HAND: "Focus on your left hand",
        CueTarget.RIGHT_HAND: "Focus on your right hand",
        CueTarget.RIGHT_ANKLE: "Focus on your ankle",
    }

    assert settings.break_prompt == "Rest until the next cue."
    for epoch in schedule:
        assert epoch.prompt == expected_prompts[epoch.cue]
        assert epoch.trigger_code == _codes().code_for(condition, epoch.cue)


def test_schedule_seed_reproduces_the_exact_cue_order() -> None:
    settings = TaskSettings(
        condition=TaskCondition.BOTH_HANDS,
        epoch_duration_sec=1.0,
        total_epochs=20,
        trigger_codes=_codes(),
        random_seed=91,
    )

    first = build_cue_schedule(settings)
    second = build_cue_schedule(settings)

    assert [epoch.cue for epoch in first] == [epoch.cue for epoch in second]


def test_schedule_randomizes_which_cue_starts() -> None:
    starting_cues = {
        build_cue_schedule(
            TaskSettings(
                condition=TaskCondition.BOTH_HANDS,
                epoch_duration_sec=1.0,
                total_epochs=2,
                trigger_codes=_codes(),
                random_seed=seed,
            )
        )[0].cue
        for seed in range(20)
    }

    assert starting_cues == {CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND}


def test_schedule_shuffles_all_epochs_and_allows_consecutive_repeats() -> None:
    orders = {
        tuple(
            epoch.cue
            for epoch in build_cue_schedule(
                TaskSettings(
                    condition=TaskCondition.BOTH_HANDS,
                    epoch_duration_sec=1.0,
                    total_epochs=10,
                    trigger_codes=_codes(),
                    random_seed=seed,
                )
            )
        )
        for seed in range(20)
    }

    assert len(orders) > 2
    assert any(
        first == second
        for order in orders
        for first, second in zip(order, order[1:], strict=False)
    )


def test_analysis_protocol_uses_the_selected_task_condition_and_timing() -> None:
    protocol = analysis_protocol_for_task(
        condition=TaskCondition.RIGHT_HAND_AND_ANKLE,
        epoch_duration_sec=3.25,
        total_epochs=8,
        trigger_codes=_codes(),
        target_hz=12.0,
    )

    assert protocol.active_event_codes == (21, 22)
    assert protocol.event_duration_sec == 3.25
    assert protocol.expected_repetitions_per_trigger == 4
    assert [trigger.label for trigger in protocol.active_triggers] == [
        "HandAnkle Right Hand",
        "HandAnkle Right Ankle",
    ]
    assert [trigger.target_hz for trigger in protocol.active_triggers] == [12.0, 12.0]


@pytest.mark.parametrize("target_hz", [FMIN - 0.01, FMAX + 0.01])
def test_analysis_protocol_rejects_frequency_outside_plotted_range(
    target_hz: float,
) -> None:
    with pytest.raises(ValueError, match=rf"between {FMIN:g} and {FMAX:g} Hz"):
        analysis_protocol_for_task(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=3.25,
            total_epochs=8,
            trigger_codes=_codes(),
            target_hz=target_hz,
        )


def test_analysis_protocol_rejects_frequency_above_final_nyquist(monkeypatch) -> None:
    import sssep_batch.models as analysis_models

    monkeypatch.setattr(analysis_models, "FMAX", 200.0)
    monkeypatch.setattr(analysis_models, "HIGHCUT", None)

    with pytest.raises(ValueError, match=r"between 3 and 128 Hz"):
        analysis_protocol_for_task(
            condition=TaskCondition.BOTH_HANDS,
            epoch_duration_sec=3.25,
            total_epochs=8,
            trigger_codes=_codes(),
            target_hz=150.0,
        )
