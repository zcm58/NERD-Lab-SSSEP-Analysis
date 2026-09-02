"""Balanced cue scheduling for the participant task."""

from __future__ import annotations

import random

from .models import CONDITION_CUES, CueEpoch, TaskSettings


def build_cue_schedule(settings: TaskSettings) -> tuple[CueEpoch, ...]:
    """Shuffle equal cue counts, with a break between successive epochs."""

    cues = CONDITION_CUES[settings.condition]
    cue_order = list(cues) * (settings.total_epochs // 2)
    random.Random(settings.random_seed).shuffle(cue_order)

    return tuple(
        CueEpoch(
            epoch_index=epoch_index,
            condition=settings.condition,
            cue=cue,
            prompt=settings.prompt_for(cue),
            trigger_code=settings.trigger_codes.code_for(settings.condition, cue),
            scheduled_onset_sec=epoch_index * (
                settings.epoch_duration_sec + settings.break_duration_sec
            ),
        )
        for epoch_index, cue in enumerate(cue_order)
    )
