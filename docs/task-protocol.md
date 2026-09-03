# Participant task behavior

This page records the task behavior that the software must preserve.

- Every experiment runs **Condition 1: both hands** first (left-hand and
  right-hand cues), then **Condition 2: right hand + right ankle** (right-hand
  and right-ankle cues). The order is fixed and is not an operator setting.
- Each condition freshly randomizes equal numbers of its two cues, allowing no
  more than two identical cues in a row. A double repeat forces the other cue
  next. Randomization does not guarantee a different order every time.
- Default prompts are `Think of your left hand`, `Think of your right hand`,
  and `Think of your right ankle`. The operator can edit these and the break
  text under **File > Settings**. Text changes do not change cue identities or
  marker codes. The home screen starts the whole experiment.
- The operator chooses the epoch duration and an even **epoch count per
  condition**. Defaults are 15 seconds and 10 epochs per condition (20 overall).
- A configurable break (10 seconds by default) separates every pair of cue
  epochs within each condition, including repeated cues. No timed break precedes
  the first or follows the last cue of a condition. The default text is
  `Now let's take a short break.` Its accepted frame swap ends the preceding
  attention epoch and sends fixed code `100`.
- After Condition 1's last full epoch, an untimed screen replaces its cue:
  `Condition 1 complete. Before starting Condition 2, please remove the TENS
  unit electrodes from the left hand and place them on the right ankle. When
  finished, press space to continue the experiment.` The accepted screen swap
  closes the final Condition 1 epoch in the log and sends its fixed code `100`.
- A fresh **Space** press on that visible screen opens a second untimed screen:
  `By continuing, you are confirming that the TENS unit electrodes are properly
  secured on the right hand and right ankle. Press 'Y' to continue.` Only a fresh
  **Y** press after this screen is visible starts Condition 2. Early presses,
  held-key repeats, and additional Space presses cannot bypass confirmation.
  The handover frame sends the final attention epoch's code `100`; confirmation
  sends no marker.
  Neither screen displays a countdown. Escape aborts from either screen. The
  serial connection stays open across the handover.
- **Show countdown timer** in File > Settings controls the top-center countdown
  on timed screens. It defaults to on and persists across launches. Hiding the
  timer does not change phase durations or marker timing. Countdown redraws send
  no markers.
- After COM3 opens, PySide6 presents the ready frame. The task stops with an
  error if the requested OpenGL frame does not swap within five seconds.
- An unchecked test-mode box is the default. If the operator checks it, the
  launcher asks `Are you sure you want to run the experiment in test mode?`
  **Yes** runs the same presentation without opening COM3 or sending markers;
  **No** returns to setup. The task CSV records `test_mode=True`.
- A precise timer is aligned to each accepted cue or break swap. The break's
  accepted swap closes the preceding cue in the event log; the next cue starts
  after the break's deadline. Neither phase is intentionally shortened.
- After the initial ready-screen **Space**, show
  `The experiment is about to begin..` for five seconds measured from its
  accepted frame swap, then present the first randomized cue and its marker.
  Early/held Space presses do not skip this delay. This delay runs only before
  Condition 1; the existing Space-then-Y confirmation still starts Condition 2.
- After the final cue duration, show
  `Thank you for your time! The experiment is now over.` for five seconds before
  closing. Its accepted frame swap closes the final cue and sends code `100`.
- Each cue has a unique marker from `1` to `255`. Marker `0` is not a cue, and
  marker `100` remains reserved for the epoch-end/break-onset marker.
- Send code `100` exactly once at the end of every completed attention epoch,
  as the first external action in the accepted swap callback for the following
  break, handover, or thank-you screen. Log its request time, code, success, and
  any failure on that epoch's row. Abort visibly if this send fails. No end marker
  is sent for a prematurely aborted cue.
- In the recorded marker stream, an attention interval starts with `11`, `12`,
  `21`, or `22` and ends with `100`. An inter-epoch break starts at `100` and
  ends at the next attention onset marker. The handover and closing intervals
  also start with `100`, but have no following attention onset in the same block.
- Process Data retains every `100` in its Status-event audit, but does not use
  these variable break, handover, or closing intervals as FFT baselines. At the
  10-second break default, extracting the same 15-second window used for an
  attention epoch would include five seconds from outside that break. Attention
  FFTs remain fixed windows from `11`, `12`, `21`, and `22` onsets.
- Fixed markers are `11` for both-hands/left-hand, `12` for
  both-hands/right-hand, `21` for hand-and-ankle/right-hand, and `22` for
  hand-and-ankle/right-ankle. They are shown disabled and cannot be edited.
- The marker is sent through `COM3` from the `QOpenGLWindow.frameSwapped`
  handler that matches the newly drawn cue frame. The serial request is the
  first external action in that handler.
- `COM3` is fixed and is not editable in the launcher.
- **Space** begins the five-second lead-in from the fullscreen ready screen;
  **Escape** aborts.
- A CSV task log records the scheduled and presented epochs and trigger events,
  the actual cue text, and the configured break duration and text. One file
  covers both conditions. `total_epochs` counts the whole experiment; additive
  `epochs_per_condition` and `condition_epoch_number` fields identify the blocks.
  Planned `scheduled_onset_sec` values are relative to each condition's planned
  start, explicitly labeled by `scheduled_onset_reference=condition_start`.
  Actual cue/trigger/offset times remain relative to the experiment start and
  include the five-second lead-in and the operator's untimed handover pause.
  Additive `show_timer` and `epoch_end_trigger_*` fields preserve the existing
  one-row-per-epoch log structure while recording the new setting and markers.
- TENS stimulation is controlled externally.

The Process Data view uses both conditions' four fixed cue codes and the duration
and per-condition epoch count from **File > Settings**. The stimulation-frequency
field defaults to **26 Hz** and remains editable to match the external TENS unit.
It adds frequency-specific summary values and a dashed vertical FFT-plot marker
labeled `TENS Unit Stimulation Frequency`, without controlling the TENS unit.
Saved FFT plotting uses the recorded frequency when available; the displayed
frequency selection supplies the marker when plotting from saved data. Neither
the marker nor this default changes the FFT amplitudes. The frequency must be
inside the usable plot, filter, and FFT
range (3–50 Hz by default). Leaving it blank still saves the complete
per-electrode FFT.

Recording analysis requires each full configured epoch. It then removes the
first and final 2.5 seconds before averaging same-cue epochs and calculating the
FFT. At the 15-second default, the FFT uses the middle 10 seconds. This analysis
crop does not shorten the participant's fullscreen cue.

Outside confirmed test mode, the software must open and check `COM3` before
showing participant cues. A missing, busy, or failed trigger connection stops
the task instead of continuing silently. CSV onset and trigger times are
software estimates at the Qt swap and serial-write request. They do not measure
the first illuminated pixel or the marker's arrival in BioSemi. Confirm both
with a photodiode and the BioSemi Status channel before data collection.

The trigger path follows FPVS Studio commit
`888544b9e0d84c2fa31e9b96b55ab214c1489df0`: validate codes before timed
playback, then call the prevalidated one-byte serial write from
the matching `frameSwapped` callback. A Qt `PreciseTimer` advances the
cue schedule. No reset byte is sent because the BioSemi USB Trigger
Interface resets the marker automatically.
