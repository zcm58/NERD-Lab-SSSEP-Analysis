# AGENTS.md

## Role

This package runs the participant cue task. TENS is controlled externally.

- `models.py`: validated conditions, cue codes, settings, and records.
- `schedule.py`: balanced alternation with a randomized starting cue.
- `runner.py`: PsychoPy fullscreen presentation and task-event CSVs.
- `triggers.py`: BioSemi USB serial output.

## Preserve

- Open the fixed `COM3` connection before creating participant-facing screens.
- Send every cue code with `window.callOnFlip(...)` on the cue-onset flip.
- Use one raw byte per event (`1..255`) over fixed COM3 at 115200 baud, 8N1.
- Keep both-hands codes fixed at `11`/`12` and hand/ankle codes fixed at
  `21`/`22`. Keep their GUI controls disabled. Code `0` is not an event.
- Require a positive duration and positive even total epoch count.
- Measure display refresh before the ready screen, compile each duration to a
  whole frame count, and close cues on the next onset or terminal black flip.
- Abort visibly after trigger failure; never continue with a null backend.
- Keep PsychoPy imports lazy and presentation on the persistent GUI worker.
- Preserve planned and observed rows in the task log, including aborted runs.

Record protocol changes in `docs/task-protocol.md` and test scheduling, flip
order, failure behavior, and log fields without opening a real window.
