from __future__ import annotations

from collections import Counter
from itertools import product

import pytest

from sssep_batch.config import BASELINE_EVENT_CODE, FMAX, FMIN
from sssep_batch.experiment.models import (
    CONDITION_ORDER,
    CUE_PROMPTS,
    CueTarget,
    CueTriggerCodes,
    ParticipantInformation,
    TaskCondition,
    TaskSettings,
    analysis_protocol_for_task,
)
from sssep_batch.experiment.schedule import build_cue_schedule
from sssep_batch.experiment.triggers import BIOSEMI_SERIAL_PORT
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


def _codes() -> CueTriggerCodes:
    return CueTriggerCodes(
        both_hands_left_hand=11,
        both_hands_right_hand=12,
        right_hand_and_ankle_right_hand=21,
        right_hand_and_ankle_right_ankle=22,
    )


@pytest.mark.parametrize("epochs_per_condition", [0, -2, 1, 3, True, 2.0, "2"])
def test_task_settings_require_a_positive_even_epoch_count(
    epochs_per_condition: object,
) -> None:
    with pytest.raises(ValueError, match="positive even"):
        TaskSettings(
            epoch_duration_sec=1.0,
            epochs_per_condition=epochs_per_condition,  # type: ignore[arg-type]
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
            epochs_per_condition=2,
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
            epoch_duration_sec=1.0,
            epochs_per_condition=2,
            trigger_codes=_codes(),
            **{field: prompt},
        )


def test_task_defaults_use_ten_second_breaks_and_existing_cue_text() -> None:
    settings = TaskSettings(
        epoch_duration_sec=15.0,
        epochs_per_condition=10,
        trigger_codes=_codes(),
    )

    assert settings.break_duration_sec == 10.0
    assert settings.break_prompt == "Now let's take a short break."
    assert {cue: settings.prompt_for(cue) for cue in CueTarget} == CUE_PROMPTS
    assert settings.epochs_per_condition == 10
    assert settings.total_epochs == 20


def test_task_serial_port_is_fixed_to_com3() -> None:
    settings = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=2,
        trigger_codes=_codes(),
    )

    assert BIOSEMI_SERIAL_PORT == "COM3"
    assert settings.serial_port == BIOSEMI_SERIAL_PORT
    with pytest.raises(TypeError, match="serial_port"):
        TaskSettings(
            epoch_duration_sec=1.0,
            epochs_per_condition=2,
            trigger_codes=_codes(),
            serial_port="COM7",  # type: ignore[call-arg]
        )


def test_task_test_mode_is_explicit_and_boolean() -> None:
    normal = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=2,
        trigger_codes=_codes(),
    )
    test = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=2,
        trigger_codes=_codes(),
        test_mode=True,
    )

    assert normal.test_mode is False
    assert test.test_mode is True
    with pytest.raises(TypeError, match="test_mode"):
        TaskSettings(
            epoch_duration_sec=1.0,
            epochs_per_condition=2,
            trigger_codes=_codes(),
            test_mode=1,  # type: ignore[arg-type]
        )


def test_participant_information_preserves_leading_zeroes_and_validates_fields(
) -> None:
    information = ParticipantInformation(
        participant_number=" 0012 ",
        age=24,
        sex="Female",
        handedness="Right handed",
        colorblind=False,
    )

    assert information.participant_number == "0012"

    invalid_values = [
        {"participant_number": "P12"},
        {"age": 0},
        {"age": True},
        {"sex": "Other"},
        {"handedness": "Right"},
        {"colorblind": None},
    ]
    baseline = {
        "participant_number": "0012",
        "age": 24,
        "sex": "Female",
        "handedness": "Right handed",
        "colorblind": False,
    }
    for replacement in invalid_values:
        with pytest.raises((TypeError, ValueError)):
            ParticipantInformation(**(baseline | replacement))


def test_trigger_codes_must_be_unique_normal_biosemi_codes() -> None:
    with pytest.raises(ValueError, match="unique"):
        CueTriggerCodes(1, 2, 3, 3)
    with pytest.raises(ValueError, match="1 to 255"):
        CueTriggerCodes(0, 2, 3, 4)
    with pytest.raises(ValueError, match="1 to 255"):
        CueTriggerCodes(1, 2, 3, 256)
    with pytest.raises(ValueError, match="reserved"):
        CueTriggerCodes(1, 2, 3, BASELINE_EVENT_CODE)


def test_schedule_balances_both_fixed_order_conditions() -> None:
    settings = TaskSettings(
        epoch_duration_sec=1.5,
        epochs_per_condition=10,
        trigger_codes=_codes(),
        random_seed=314,
        break_duration_sec=0.75,
    )

    schedule = build_cue_schedule(settings)

    assert CONDITION_ORDER == (
        TaskCondition.BOTH_HANDS, TaskCondition.RIGHT_HAND_AND_ANKLE
    )
    assert [epoch.condition for epoch in schedule] == [
        *([TaskCondition.BOTH_HANDS] * 10),
        *([TaskCondition.RIGHT_HAND_AND_ANKLE] * 10),
    ]
    assert Counter(epoch.trigger_code for epoch in schedule) == {
        11: 5, 12: 5, 21: 5, 22: 5
    }
    assert {epoch.cue for epoch in schedule[:10]} == {
        CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND
    }
    assert {epoch.cue for epoch in schedule[10:]} == {
        CueTarget.RIGHT_HAND, CueTarget.RIGHT_ANKLE
    }
    assert [epoch.epoch_index for epoch in schedule] == list(range(20))
    assert [epoch.scheduled_onset_sec for epoch in schedule] == [
        index * 2.25 for index in range(10)
    ] * 2


def test_schedule_uses_custom_text_without_changing_cue_codes() -> None:
    settings = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=2,
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
        assert epoch.trigger_code == _codes().code_for(epoch.condition, epoch.cue)


def test_schedule_seed_reproduces_the_exact_cue_order() -> None:
    settings = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=20,
        trigger_codes=_codes(),
        random_seed=91,
    )

    first = build_cue_schedule(settings)
    second = build_cue_schedule(settings)

    assert first == second


@pytest.mark.parametrize("epochs_per_condition", [2, 4, 6, 10, 20, 100, 1000, 10000])
def test_schedule_limits_repeats_without_losing_balance(
    epochs_per_condition: int,
) -> None:
    for seed in range(20):
        schedule = build_cue_schedule(
            TaskSettings(
                epoch_duration_sec=1.0,
                epochs_per_condition=epochs_per_condition,
                trigger_codes=_codes(),
                random_seed=seed,
            )
        )

        for block_index, condition in enumerate(CONDITION_ORDER):
            start = block_index * epochs_per_condition
            block = schedule[start:start + epochs_per_condition]
            cues = [epoch.cue for epoch in block]
            assert all(epoch.condition == condition for epoch in block)
            assert sorted(Counter(cues).values()) == [epochs_per_condition // 2] * 2
            assert not any(
                first == second == third
                for first, second, third in zip(cues, cues[1:], cues[2:], strict=False)
            )


@pytest.mark.parametrize("epochs_per_condition", [2, 4, 6, 8, 10])
def test_schedule_can_generate_every_valid_small_balanced_order(
    monkeypatch, epochs_per_condition: int,
) -> None:
    from sssep_batch.experiment import schedule as schedule_module

    valid_orders = [
        order
        for order in product((0, 1), repeat=epochs_per_condition)
        if order.count(0) == epochs_per_condition // 2
        and not any(
            first == second == third
            for first, second, third in zip(order, order[1:], order[2:], strict=False)
        )
    ]
    settings = TaskSettings(
        epoch_duration_sec=1.0,
        epochs_per_condition=epochs_per_condition,
        trigger_codes=_codes(),
    )

    for expected_order in valid_orders:
        class ScriptedRandom:
            choices_made = 0

            def choice(self, choices):
                position = self.choices_made % epochs_per_condition
                prefix = expected_order[:position]
                possible_next = {
                    order[position] for order in valid_orders if order[:position] == prefix
                }
                assert set(choices) == possible_next
                self.choices_made += 1
                return expected_order[position]

        rng = ScriptedRandom()
        monkeypatch.setattr(schedule_module.random, "Random", lambda seed: rng)
        schedule = build_cue_schedule(settings)

        assert rng.choices_made == settings.total_epochs
        assert [epoch.trigger_code for epoch in schedule] == [
            *[11 + index for index in expected_order],
            *[21 + index for index in expected_order],
        ]


def test_schedule_repeat_limit_resets_after_the_condition_handover(monkeypatch) -> None:
    from sssep_batch.experiment import schedule as schedule_module

    class ScriptedRandom:
        choices = iter((0, 0, 1, 1, 0, 0, 1, 1))

        def choice(self, available):
            selected = next(self.choices)
            assert selected in available
            return selected

    monkeypatch.setattr(schedule_module.random, "Random", lambda seed: ScriptedRandom())
    schedule = build_cue_schedule(
        TaskSettings(
            epoch_duration_sec=1.0,
            epochs_per_condition=4,
            trigger_codes=_codes(),
        )
    )

    assert [epoch.trigger_code for epoch in schedule] == [11, 11, 12, 12, 21, 21, 22, 22]


@pytest.mark.parametrize(
    ("start_index", "expected_cues"),
    [
        (0, {CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND}),
        (2, {CueTarget.RIGHT_HAND, CueTarget.RIGHT_ANKLE}),
    ],
)
def test_schedule_randomizes_which_cue_starts_each_condition(
    start_index: int, expected_cues: set[CueTarget]
) -> None:
    starting_cues = {
        build_cue_schedule(
            TaskSettings(
                epoch_duration_sec=1.0,
                epochs_per_condition=2,
                trigger_codes=_codes(),
                random_seed=seed,
            )
        )[start_index].cue
        for seed in range(20)
    }

    assert starting_cues == expected_cues


@pytest.mark.parametrize("start_index", [0, 10])
def test_schedule_shuffles_each_condition_and_allows_consecutive_repeats(
    start_index: int,
) -> None:
    orders = {
        tuple(
            epoch.cue
            for epoch in build_cue_schedule(
                TaskSettings(
                    epoch_duration_sec=1.0,
                    epochs_per_condition=10,
                    trigger_codes=_codes(),
                    random_seed=seed,
                )
            )[start_index:start_index + 10]
        )
        for seed in range(20)
    }

    assert len(orders) > 2
    assert any(
        first == second
        for order in orders
        for first, second in zip(order, order[1:], strict=False)
    )


def test_schedule_starts_a_fresh_random_generator_for_each_run(monkeypatch) -> None:
    from sssep_batch.experiment import schedule as schedule_module

    seeds = []
    real_random = schedule_module.random.Random

    def tracked_random(seed):
        seeds.append(seed)
        return real_random(seed)

    monkeypatch.setattr(schedule_module.random, "Random", tracked_random)
    settings = TaskSettings(
        epoch_duration_sec=15.0,
        epochs_per_condition=10,
        trigger_codes=_codes(),
    )
    build_cue_schedule(settings)
    build_cue_schedule(settings)

    assert settings.random_seed is None
    assert seeds == [None, None]


def test_analysis_protocol_uses_both_conditions_and_per_cue_counts() -> None:
    protocol = analysis_protocol_for_task(
        epoch_duration_sec=3.25,
        epochs_per_condition=8,
        trigger_codes=_codes(),
        target_hz=12.0,
    )

    assert protocol.active_event_codes == (11, 12, 21, 22)
    assert protocol.event_duration_sec == 3.25
    assert protocol.expected_repetitions_per_trigger == 4
    assert protocol.analyze_baseline is False
    assert [trigger.label for trigger in protocol.active_triggers] == [
        "BothHands Left Hand",
        "BothHands Right Hand",
        "HandAnkle Right Hand",
        "HandAnkle Right Ankle",
    ]
    assert [trigger.target_hz for trigger in protocol.active_triggers] == [12.0] * 4


@pytest.mark.parametrize("seed", [1, 4, 91])
def test_analysis_protocol_matches_both_shuffled_conditions(seed: int) -> None:
    settings = TaskSettings(
        epoch_duration_sec=15.0,
        epochs_per_condition=10,
        trigger_codes=_codes(),
        random_seed=seed,
    )
    protocol = analysis_protocol_for_task(
        epoch_duration_sec=settings.epoch_duration_sec,
        epochs_per_condition=settings.epochs_per_condition,
        trigger_codes=settings.trigger_codes,
    )

    observed_counts = Counter(
        epoch.trigger_code for epoch in build_cue_schedule(settings)
    )

    assert observed_counts == {
        code: protocol.expected_repetitions_per_trigger
        for code in protocol.active_event_codes
    }
    assert set(observed_counts) == {11, 12, 21, 22}
    assert protocol.baseline_event_code == BASELINE_EVENT_CODE
    assert BASELINE_EVENT_CODE not in observed_counts


def test_analysis_protocol_requires_a_boolean_baseline_setting() -> None:
    with pytest.raises(TypeError, match="analyze_baseline must be True or False"):
        AnalysisProtocol(
            active_triggers=(AnalysisTrigger(11, "BothHands Left Hand"),),
            event_duration_sec=15.0,
            expected_repetitions_per_trigger=1,
            baseline_event_code=BASELINE_EVENT_CODE,
            analyze_baseline=1,
        )


@pytest.mark.parametrize("target_hz", [FMIN - 0.01, FMAX + 0.01])
def test_analysis_protocol_rejects_frequency_outside_plotted_range(
    target_hz: float,
) -> None:
    with pytest.raises(ValueError, match=rf"between {FMIN:g} and {FMAX:g} Hz"):
        analysis_protocol_for_task(
            epoch_duration_sec=3.25,
            epochs_per_condition=8,
            trigger_codes=_codes(),
            target_hz=target_hz,
        )


def test_analysis_protocol_rejects_frequency_above_final_nyquist(monkeypatch) -> None:
    import sssep_batch.models as analysis_models

    monkeypatch.setattr(analysis_models, "FMAX", 200.0)
    monkeypatch.setattr(analysis_models, "HIGHCUT", None)

    with pytest.raises(ValueError, match=r"between 3 and 128 Hz"):
        analysis_protocol_for_task(
            epoch_duration_sec=3.25,
            epochs_per_condition=8,
            trigger_codes=_codes(),
            target_hz=150.0,
        )
