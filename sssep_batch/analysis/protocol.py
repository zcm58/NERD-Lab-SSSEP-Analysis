"""Build the event/timing settings passed through one FFT analysis batch."""

from sssep_batch.config import (
    ACTIVE_EVENT_CODES,
    BASELINE_EVENT_CODE,
    EVENT_DURATION_SEC,
    EXPECTED_REPETITIONS_PER_TRIGGER,
    TRIGGER_HZ_MAP,
    TRIGGER_LABELS,
)
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


def default_analysis_protocol() -> AnalysisProtocol:
    """Return the analysis protocol defined in ``sssep_batch.config``."""

    return AnalysisProtocol(
        active_triggers=tuple(
            AnalysisTrigger(
                code=code,
                label=TRIGGER_LABELS[code],
                target_hz=TRIGGER_HZ_MAP[code],
            )
            for code in ACTIVE_EVENT_CODES
        ),
        event_duration_sec=EVENT_DURATION_SEC,
        expected_repetitions_per_trigger=EXPECTED_REPETITIONS_PER_TRIGGER,
        baseline_event_code=BASELINE_EVENT_CODE,
        baseline_label=TRIGGER_LABELS[BASELINE_EVENT_CODE],
    )
