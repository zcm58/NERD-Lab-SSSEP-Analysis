# AGENTS.md

## Role

This package runs the participant cue task. TENS is controlled externally.

- `models.py`: validated conditions, cue codes, settings, and records.
- `schedule.py`: fresh balanced cue order, capped at two repeats, with breaks.
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
- Require positive cue/break durations and a positive even epoch count per
  condition. Always run both hands then right hand/right ankle, shuffling
  balanced cues within each block; at most two identical cues may appear in a row.
- Show editable cue/break text and an optional top-center countdown, controlled
  by persistent `show_timer` (default true). Hiding it must not change timing.
  Add breaks only
  between cue epochs; never send a marker for a break or countdown redraw.
- Align a Qt `PreciseTimer` deadline to each accepted cue/break swap. Close each
  cue on the following break, handover, or thank-you screen swap.
- Between conditions, wait for Space on the visible electrode handover screen,
  then a fresh Y on its separately visible confirmation. Neither admin screen
  has a timer. Send code `100` once on the first handover swap; confirmation
  sends no marker. Escape still aborts; held-key repeats cannot advance.
- Initial ready-screen Space starts a five-second lead-in, then the first cue.
  Show the final thank-you screen for five seconds before closing; its first
  swap sends code `100` once. The marker must precede logging/progress/timers.
  Log condition-end code/time/success/error on the final epoch row and abort
  after failure. Do not send completion markers for prematurely aborted cues.
- Log planned onsets relative to each condition, explicitly label their
  timebase, and retain actual times relative to the whole experiment start.
- Abort visibly after trigger failure; never continue with a null backend.
  Test mode uses the concrete simulated backend.
- Run the participant presenter on the Qt main thread.
- Preserve planned and observed rows in the task log, including aborted runs.

Record protocol changes in `docs/task-protocol.md` and test scheduling, flip
order, failure behavior, and log fields without opening a real window.

For an optional live OpenGL visual check, capture `grabFramebuffer()` inside
`paintGL()` after drawing, before the buffer swap. Captures outside that phase
can show stale or discarded buffers instead of the newly drawn frame.
