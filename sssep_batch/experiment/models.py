"""Validated settings and records for the participant cue task."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from pathlib import Path

from sssep_batch.config import BASELINE_EVENT_CODE, TRIGGER_LABELS
from sssep_batch.experiment.triggers import BIOSEMI_SERIAL_PORT
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


class TaskCondition(str, Enum):
    """The two supported TENS electrode layouts."""

    BOTH_HANDS = "both_hands"
    RIGHT_HAND_AND_ANKLE = "right_hand_and_ankle"


class CueTarget(str, Enum):
    """The body site named by a participant prompt."""

    LEFT_HAND = "left_hand"
    RIGHT_HAND = "right_hand"
    RIGHT_ANKLE = "right_ankle"


CONDITION_CUES: dict[TaskCondition, tuple[CueTarget, CueTarget]] = {
    TaskCondition.BOTH_HANDS: (CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND),
    TaskCondition.RIGHT_HAND_AND_ANKLE: (CueTarget.RIGHT_HAND, CueTarget.RIGHT_ANKLE),
}

CUE_PROMPTS: dict[CueTarget, str] = {
    CueTarget.LEFT_HAND: "Think of your left hand",
    CueTarget.RIGHT_HAND: "Think of your right hand",
    CueTarget.RIGHT_ANKLE: "Think of your right ankle",
}

ANALYSIS_CONDITION_LABELS: dict[TaskCondition, str] = {
    TaskCondition.BOTH_HANDS: "BothHands",
    TaskCondition.RIGHT_HAND_AND_ANKLE: "HandAnkle",
}

ANALYSIS_CUE_LABELS: dict[CueTarget, str] = {
    CueTarget.LEFT_HAND: "Left Hand",
    CueTarget.RIGHT_HAND: "Right Hand",
    CueTarget.RIGHT_ANKLE: "Right Ankle",
}


@dataclass(frozen=True, slots=True)
class CueTriggerCodes:
    """Explicit event codes for each condition and cue combination.

    Right-hand cues use separate codes in the two conditions so a recorded
    Status event identifies both the stimulation layout and attended site.
    """

    both_hands_left_hand: int
    both_hands_right_hand: int
    right_hand_and_ankle_right_hand: int
    right_hand_and_ankle_right_ankle: int

    def __post_init__(self) -> None:
        codes = (
            self.both_hands_left_hand,
            self.both_hands_right_hand,
            self.right_hand_and_ankle_right_hand,
            self.right_hand_and_ankle_right_ankle,
        )
        for code in codes:
            if not isinstance(code, int) or isinstance(code, bool) or not 1 <= code <= 255:
                raise ValueError("Each cue trigger code must be an integer from 1 to 255.")
        if len(set(codes)) != len(codes):
            raise ValueError("Cue trigger codes must be unique.")
        if BASELINE_EVENT_CODE in codes:
            raise ValueError(
                f"Trigger code {BASELINE_EVENT_CODE} is reserved for the Gap/Break baseline."
            )

    def code_for(self, condition: TaskCondition, cue: CueTarget) -> int:
        """Return the code for one valid condition/cue pair."""

        code_lookup = {
            (TaskCondition.BOTH_HANDS, CueTarget.LEFT_HAND): self.both_hands_left_hand,
            (TaskCondition.BOTH_HANDS, CueTarget.RIGHT_HAND): self.both_hands_right_hand,
            (
                TaskCondition.RIGHT_HAND_AND_ANKLE,
                CueTarget.RIGHT_HAND,
            ): self.right_hand_and_ankle_right_hand,
            (
                TaskCondition.RIGHT_HAND_AND_ANKLE,
                CueTarget.RIGHT_ANKLE,
            ): self.right_hand_and_ankle_right_ankle,
        }
        try:
            return code_lookup[(condition, cue)]
        except KeyError as exc:
            raise ValueError(
                f"Cue {cue.value!r} is not valid for condition {condition.value!r}."
            ) from exc


@dataclass(frozen=True, slots=True)
class TaskSettings:
    """Settings supplied by the operator GUI for one participant task."""

    condition: TaskCondition
    epoch_duration_sec: float
    total_epochs: int
    trigger_codes: CueTriggerCodes
    serial_port: str = field(default=BIOSEMI_SERIAL_PORT, init=False)
    output_folder: Path | None = None
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.condition, TaskCondition):
            raise TypeError("condition must be a TaskCondition value.")
        if (
            not isinstance(self.epoch_duration_sec, (int, float))
            or isinstance(self.epoch_duration_sec, bool)
            or not isfinite(float(self.epoch_duration_sec))
            or self.epoch_duration_sec <= 0
        ):
            raise ValueError("epoch_duration_sec must be a finite number greater than zero.")
        if (
            not isinstance(self.total_epochs, int)
            or isinstance(self.total_epochs, bool)
            or self.total_epochs <= 0
            or self.total_epochs % 2 != 0
        ):
            raise ValueError("total_epochs must be a positive even integer for cue balance.")
        if not isinstance(self.trigger_codes, CueTriggerCodes):
            raise TypeError("trigger_codes must be a CueTriggerCodes value.")
        if self.random_seed is not None and (
            not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool)
        ):
            raise TypeError("random_seed must be an integer or None.")

        object.__setattr__(self, "epoch_duration_sec", float(self.epoch_duration_sec))
        if self.output_folder is not None:
            object.__setattr__(self, "output_folder", Path(self.output_folder))


@dataclass(frozen=True, slots=True)
class CueEpoch:
    """One planned cue epoch; ``epoch_index`` is zero based."""

    epoch_index: int
    condition: TaskCondition
    cue: CueTarget
    prompt: str
    trigger_code: int
    scheduled_onset_sec: float

    @property
    def label(self) -> str:
        return f"{self.condition.value}:{self.cue.value}"


@dataclass(frozen=True, slots=True)
class CuePresentationRecord:
    """Observed cue and trigger timing from one presentation flip."""

    epoch_index: int
    condition: TaskCondition
    cue: CueTarget
    trigger_code: int
    scheduled_onset_sec: float
    cue_onset_time_sec: float
    trigger_time_sec: float
    cue_offset_time_sec: float | None = None
    observed_duration_sec: float | None = None
    completed: bool = False
    trigger_succeeded: bool = True
    trigger_error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    """Schedule, observed events, and completion state for one run."""

    run_id: str
    started_at_utc: str
    settings: TaskSettings
    schedule: tuple[CueEpoch, ...]
    events: tuple[CuePresentationRecord, ...]
    aborted: bool
    abort_reason: str | None = None
    log_path: Path | None = None

    @property
    def completed_epochs(self) -> int:
        return sum(record.completed for record in self.events)


def analysis_protocol_for_task(
    *,
    condition: TaskCondition,
    epoch_duration_sec: float,
    total_epochs: int,
    trigger_codes: CueTriggerCodes,
    target_hz: float | None = None,
) -> AnalysisProtocol:
    """Build analysis settings from the participant-task fields in the GUI."""

    validated = TaskSettings(
        condition=condition,
        epoch_duration_sec=epoch_duration_sec,
        total_epochs=total_epochs,
        trigger_codes=trigger_codes,
    )
    return AnalysisProtocol(
        active_triggers=tuple(
            AnalysisTrigger(
                code=trigger_codes.code_for(condition, cue),
                label=(
                    f"{ANALYSIS_CONDITION_LABELS[condition]} "
                    f"{ANALYSIS_CUE_LABELS[cue]}"
                ),
                target_hz=target_hz,
            )
            for cue in CONDITION_CUES[condition]
        ),
        event_duration_sec=validated.epoch_duration_sec,
        expected_repetitions_per_trigger=validated.total_epochs // 2,
        baseline_event_code=BASELINE_EVENT_CODE,
        baseline_label=TRIGGER_LABELS[BASELINE_EVENT_CODE],
    )
