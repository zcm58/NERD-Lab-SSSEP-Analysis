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


CONDITION_ORDER = (
    TaskCondition.BOTH_HANDS,
    TaskCondition.RIGHT_HAND_AND_ANKLE,
)

CONDITION_CUES: dict[TaskCondition, tuple[CueTarget, CueTarget]] = {
    TaskCondition.BOTH_HANDS: (CueTarget.LEFT_HAND, CueTarget.RIGHT_HAND),
    TaskCondition.RIGHT_HAND_AND_ANKLE: (CueTarget.RIGHT_HAND, CueTarget.RIGHT_ANKLE),
}

CUE_PROMPTS: dict[CueTarget, str] = {
    CueTarget.LEFT_HAND: "Think of your left hand",
    CueTarget.RIGHT_HAND: "Think of your right hand",
    CueTarget.RIGHT_ANKLE: "Think of your right ankle",
}

DEFAULT_BREAK_DURATION_SEC = 10.0
DEFAULT_BREAK_PROMPT = "Now let's take a short break."

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
                raise ValueError("Each trigger code must be an integer from 1 to 255.")
        if len(set(codes)) != len(codes):
            raise ValueError("Trigger codes must be unique.")
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
                f"Participant prompt {cue.value!r} is not valid for condition {condition.value!r}."
            ) from exc


@dataclass(frozen=True, slots=True)
class TaskSettings:
    """Settings for one participant's fixed two-condition experiment."""

    epoch_duration_sec: float
    epochs_per_condition: int
    trigger_codes: CueTriggerCodes
    serial_port: str = field(default=BIOSEMI_SERIAL_PORT, init=False)
    output_folder: Path | None = None
    random_seed: int | None = None
    test_mode: bool = False
    break_duration_sec: float = DEFAULT_BREAK_DURATION_SEC
    left_hand_prompt: str = CUE_PROMPTS[CueTarget.LEFT_HAND]
    right_hand_prompt: str = CUE_PROMPTS[CueTarget.RIGHT_HAND]
    right_ankle_prompt: str = CUE_PROMPTS[CueTarget.RIGHT_ANKLE]
    break_prompt: str = DEFAULT_BREAK_PROMPT
    show_timer: bool = True

    def __post_init__(self) -> None:
        for name in ("epoch_duration_sec", "break_duration_sec"):
            duration = getattr(self, name)
            if (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or not isfinite(float(duration))
                or duration <= 0
            ):
                raise ValueError(f"{name} must be a finite number greater than zero.")
            object.__setattr__(self, name, float(duration))
        if (
            not isinstance(self.epochs_per_condition, int)
            or isinstance(self.epochs_per_condition, bool)
            or self.epochs_per_condition <= 0
            or self.epochs_per_condition % 2 != 0
        ):
            raise ValueError(
                "epochs_per_condition must be a positive even integer to balance trigger codes."
            )
        if not isinstance(self.trigger_codes, CueTriggerCodes):
            raise TypeError("trigger_codes must be a CueTriggerCodes value.")
        if self.random_seed is not None and (
            not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool)
        ):
            raise TypeError("random_seed must be an integer or None.")
        if not isinstance(self.test_mode, bool):
            raise TypeError("test_mode must be True or False.")
        if not isinstance(self.show_timer, bool):
            raise TypeError("show_timer must be True or False.")
        for name in (
            "left_hand_prompt", "right_hand_prompt", "right_ankle_prompt", "break_prompt"
        ):
            prompt = getattr(self, name)
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{name} must contain nonblank text.")
            object.__setattr__(self, name, prompt.strip())

        if self.output_folder is not None:
            object.__setattr__(self, "output_folder", Path(self.output_folder))

    @property
    def total_epochs(self) -> int:
        """Return the cue count across both conditions, excluding breaks."""

        return self.epochs_per_condition * len(CONDITION_ORDER)

    def prompt_for(self, cue: CueTarget) -> str:
        """Return the operator's display text without changing the cue identity."""

        return {
            CueTarget.LEFT_HAND: self.left_hand_prompt,
            CueTarget.RIGHT_HAND: self.right_hand_prompt,
            CueTarget.RIGHT_ANKLE: self.right_ankle_prompt,
        }[cue]


@dataclass(frozen=True, slots=True)
class CueEpoch:
    """One cue with a global zero-based index and condition-relative planned onset."""

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
    """Observed cue and boundary-trigger timing for one attention epoch."""

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
    epoch_end_trigger_code: int | None = None
    epoch_end_trigger_time_sec: float | None = None
    epoch_end_trigger_succeeded: bool | None = None
    epoch_end_trigger_error: str | None = None


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
    epoch_duration_sec: float,
    epochs_per_condition: int,
    trigger_codes: CueTriggerCodes,
    target_hz: float | None = None,
) -> AnalysisProtocol:
    """Analyze all four cues using the experiment's duration and per-cue count."""

    validated = TaskSettings(
        epoch_duration_sec=epoch_duration_sec,
        epochs_per_condition=epochs_per_condition,
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
            for condition in CONDITION_ORDER
            for cue in CONDITION_CUES[condition]
        ),
        event_duration_sec=validated.epoch_duration_sec,
        expected_repetitions_per_trigger=validated.epochs_per_condition // 2,
        baseline_event_code=BASELINE_EVENT_CODE,
        baseline_label=TRIGGER_LABELS[BASELINE_EVENT_CODE],
        analyze_baseline=False,
    )
