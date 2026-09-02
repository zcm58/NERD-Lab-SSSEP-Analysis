# AGENTS.md

## Role

This package runs the participant cue task. TENS is controlled externally.

- `models.py`: validated conditions, cue codes, settings, and records.
- `schedule.py`: a fresh shuffle of balanced cues, including break intervals.
- `runner.py`: PySide6 cues, breaks, countdowns, and task-event CSVs.
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
- Require positive cue/break durations and a positive even total epoch count.
  Shuffle equal cue counts for each run; consecutive repeats are allowed.
- Show editable cue/break text and a top-center countdown. Add breaks only
  between cue epochs; never send a marker for a break or countdown redraw.
- Align a Qt `PreciseTimer` deadline to each accepted cue/break swap. Close each
  cue on the following break swap, or the terminal black swap for the final cue.
- Abort visibly after trigger failure; never continue with a null backend.
  Test mode uses the concrete simulated backend.
- Run the participant presenter on the Qt main thread.
- Preserve planned and observed rows in the task log, including aborted runs.

Record protocol changes in `docs/task-protocol.md` and test scheduling, flip
order, failure behavior, and log fields without opening a real window.

For an optional live OpenGL visual check, capture `grabFramebuffer()` inside
`paintGL()` after drawing, before the buffer swap. Captures outside that phase
can show stale or discarded buffers instead of the newly drawn frame.
