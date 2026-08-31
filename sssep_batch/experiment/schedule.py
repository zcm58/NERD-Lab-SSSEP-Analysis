"""Balanced cue scheduling for the participant task."""

from __future__ import annotations

import random

from .models import CONDITION_CUES, CUE_PROMPTS, CueEpoch, TaskSettings


def build_cue_schedule(settings: TaskSettings) -> tuple[CueEpoch, ...]:
    """Build a balanced alternating schedule with a randomized starting cue."""

    cues = CONDITION_CUES[settings.condition]
    first_cue = random.Random(settings.random_seed).choice(cues)
    second_cue = cues[1] if first_cue == cues[0] else cues[0]
    cue_order = tuple(
        first_cue if epoch_index % 2 == 0 else second_cue
        for epoch_index in range(settings.total_epochs)
    )

    return tuple(
        CueEpoch(
            epoch_index=epoch_index,
            condition=settings.condition,
            cue=cue,
            prompt=CUE_PROMPTS[cue],
            trigger_code=settings.trigger_codes.code_for(settings.condition, cue),
            scheduled_onset_sec=epoch_index * settings.epoch_duration_sec,
        )
        for epoch_index, cue in enumerate(cue_order)
    )
