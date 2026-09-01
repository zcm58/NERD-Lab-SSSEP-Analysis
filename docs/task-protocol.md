# Participant task behavior

This page records the task behavior that the software must preserve.

- **Both hands:** cues alternate between thinking of the left hand and thinking
  of the right hand; the starting cue is randomized.
- **Right hand + right ankle:** cues alternate between thinking of the right
  hand and thinking of the right ankle; the starting cue is randomized.
- The exact fullscreen prompts are `Think of your left hand`, `Think of your
  right hand`, and `Think of your right ankle`; each condition uses its two
  relevant prompts.
- The operator chooses the epoch duration and an even total epoch count. The
  default duration is 15 seconds.
- After COM3 opens, PySide6 presents the ready frame. The task stops with an
  error if the requested OpenGL frame does not swap within five seconds.
- A precise timer is aligned to each accepted cue-frame swap and requests the
  next cue at the configured software deadline. The next accepted swap closes
  the preceding cue in the event log, so a cue is never intentionally shortened.
- After the final cue duration, a black display-frame swap closes its event
  timestamp before the task window closes.
- Each cue has a unique marker from `1` to `255`. Marker `0` is not a cue, and
  marker `100` remains reserved for the Gap/Break baseline.
- Fixed markers are `11` for both-hands/left-hand, `12` for
  both-hands/right-hand, `21` for hand-and-ankle/right-hand, and `22` for
  hand-and-ankle/right-ankle. They are shown disabled and cannot be edited.
- The marker is sent through `COM3` from the `QOpenGLWindow.frameSwapped`
  handler that matches the newly drawn cue frame. The serial request is the
  first external action in that handler.
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

Recording analysis requires each full configured epoch. It then removes the
first and final 2.5 seconds before averaging same-cue epochs and calculating the
FFT. At the 15-second default, the FFT uses the middle 10 seconds. This analysis
crop does not shorten the participant's fullscreen cue.

The software must open and check `COM3` before showing participant cues. A
missing, busy, or failed trigger connection stops the task instead of continuing
silently. CSV onset and trigger times are software estimates at the Qt swap and
serial-write request. They do not measure the first illuminated pixel or the
marker's arrival in BioSemi. Confirm both with a photodiode and the BioSemi
Status channel before data collection.

The trigger path follows FPVS Studio commit
`888544b9e0d84c2fa31e9b96b55ab214c1489df0`: validate codes before timed
playback, then call the prevalidated one-byte serial write from
the matching `frameSwapped` callback. A Qt `PreciseTimer` advances the
cue schedule. No reset byte is sent because the BioSemi USB Trigger
Interface resets the marker automatically.
