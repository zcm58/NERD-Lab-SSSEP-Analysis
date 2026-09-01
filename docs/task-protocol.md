# Participant task behavior

This page records the task behavior that the software must preserve.

- **Both hands:** cues alternate between thinking of the left hand and thinking
  of the right hand; the starting cue is randomized.
- **Right hand + right ankle:** cues alternate between thinking of the right
  hand and thinking of the right ankle; the starting cue is randomized.
- The exact fullscreen prompts are `Think of your left hand`, `Think of your
  right hand`, and `Think of your right ankle`; each condition uses its two
  relevant prompts.
- The operator chooses the epoch duration and an even total epoch count.
- Before the ready screen, PsychoPy measures the display refresh rate. The task
  stops with an error if it cannot obtain a finite positive measurement.
- The configured epoch duration is rounded up to a whole display-frame count,
  with at least one frame per cue. Epochs run back-to-back, and the onset
  flip for each cue also closes the preceding cue in the event log.
- After the final cue's full frame count, a black display flip closes its event
  timestamp before the task window closes.
- Each cue has a unique marker from `1` to `255`. Marker `0` is not a cue, and
  marker `100` remains reserved for the Gap/Break baseline.
- Fixed markers are `11` for both-hands/left-hand, `12` for
  both-hands/right-hand, `21` for hand-and-ankle/right-hand, and `22` for
  hand-and-ankle/right-ankle. They are shown disabled and cannot be edited.
- The marker is sent through `COM3` on the exact PsychoPy display flip that
  makes the cue visible.
- `COM3` is fixed and is not editable in the launcher.
- **Space** starts from the fullscreen ready screen; **Escape** aborts.
- A CSV task log records the scheduled and presented epochs and trigger events.
- TENS stimulation is controlled externally.

The analysis tab uses the condition, duration, epoch count, and fixed cue codes
shown in the task tab. Its optional stimulation-frequency field adds
the correct expected-frequency marker and summary values without controlling
the TENS unit. The frequency must be inside the usable plot, filter, and FFT
range (3–50 Hz by default). Leaving it blank still saves the complete
per-electrode FFT.

The software must open and check `COM3` before showing participant
cues. A missing, busy, or failed trigger connection stops the task instead of
continuing silently. Hardware marker values and timing still require BioSemi
bench validation before data collection.

The trigger path follows FPVS Studio commit
`888544b9e0d84c2fa31e9b96b55ab214c1489df0`: validate codes before timed
playback, then call the prevalidated one-byte serial write from
`window.callOnFlip(...)`. No reset byte is sent because the BioSemi USB Trigger
Interface resets the marker automatically.
