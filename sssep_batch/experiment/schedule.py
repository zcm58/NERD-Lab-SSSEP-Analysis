"""Balanced cue scheduling for the participant task."""

from __future__ import annotations

import random

from .models import CONDITION_CUES, CONDITION_ORDER, CueEpoch, TaskSettings


def build_cue_schedule(settings: TaskSettings) -> tuple[CueEpoch, ...]:
    """Randomize balanced cues, with at most two repeats, within each condition.

    Planned onsets reset for each condition because the operator controls the
    duration of the pause between conditions.
    """

    rng = random.Random(settings.random_seed)
    schedule = []
    for condition in CONDITION_ORDER:
        remaining = [settings.epochs_per_condition // 2] * 2
        cue_order = []
        previous = None
        repeats = 0
        for _ in range(settings.epochs_per_condition):
            choices = []
            for index in (0, 1):
                next_repeats = repeats + 1 if index == previous else 1
                same_left = remaining[index] - 1
                other_left = remaining[1 - index]
                # Each opposite cue can separate two more repeats. Keep only
                # choices whose remaining counts still fit those available gaps.
                if (
                    same_left >= 0
                    and next_repeats <= 2
                    and same_left <= 2 * other_left + 2 - next_repeats
                    and other_left <= 2 * (same_left + 1)
                ):
                    choices.append(index)
            selected = rng.choice(choices)
            repeats = repeats + 1 if selected == previous else 1
            previous = selected
            remaining[selected] -= 1
            cue_order.append(CONDITION_CUES[condition][selected])
        for condition_epoch_index, cue in enumerate(cue_order):
            schedule.append(
                CueEpoch(
                    epoch_index=len(schedule),
                    condition=condition,
                    cue=cue,
                    prompt=settings.prompt_for(cue),
                    trigger_code=settings.trigger_codes.code_for(condition, cue),
                    scheduled_onset_sec=condition_epoch_index * (
                        settings.epoch_duration_sec + settings.break_duration_sec
                    ),
                )
            )
    return tuple(schedule)
