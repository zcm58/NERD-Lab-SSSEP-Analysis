# AGENTS.md

## Role

This package runs the participant cue task. TENS is controlled externally.

- `models.py`: validated conditions, cue codes, settings, and records.
- `schedule.py`: balanced alternation with a randomized starting cue.
- `runner.py`: PySide6 fullscreen presentation and task-event CSVs.
- `triggers.py`: BioSemi USB serial output.

## Preserve

- Open the fixed `COM3` connection before creating participant-facing screens
  in normal runs. The only exception is the explicit GUI test mode after its
  yes/no confirmation; test mode must be recorded in the task log.
- Send every cue code as the first external action in the matching
  `QOpenGLWindow.frameSwapped` callback for its newly drawn frame.
- Use one raw byte per event (`1..255`) over fixed COM3 at 115200 baud, 8N1.
- Keep both-hands codes fixed at `11`/`12` and hand/ankle codes fixed at
  `21`/`22`. Keep their GUI controls disabled. Code `0` is not an event.
- Require a positive duration and positive even total epoch count.
- Align a Qt `PreciseTimer` deadline to each accepted cue swap and close cues on
  the next onset or terminal black swap.
- Abort visibly after trigger failure; never continue with a null backend.
  Test mode uses the concrete simulated backend.
- Run the participant presenter on the Qt main thread.
- Preserve planned and observed rows in the task log, including aborted runs.

Record protocol changes in `docs/task-protocol.md` and test scheduling, flip
order, failure behavior, and log fields without opening a real window.
