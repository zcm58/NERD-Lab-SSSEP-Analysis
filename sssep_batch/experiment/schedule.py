"""Balanced cue scheduling for the participant task."""

from __future__ import annotations

import random

from .models import CONDITION_CUES, CONDITION_ORDER, CueEpoch, TaskSettings


def build_cue_schedule(settings: TaskSettings) -> tuple[CueEpoch, ...]:
    """Shuffle balanced cues within each fixed-order condition.

    Planned onsets reset for each condition because the operator controls the
    duration of the pause between conditions.
    """

    rng = random.Random(settings.random_seed)
    schedule = []
    for condition in CONDITION_ORDER:
        cue_order = list(CONDITION_CUES[condition]) * (settings.epochs_per_condition // 2)
        rng.shuffle(cue_order)
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
