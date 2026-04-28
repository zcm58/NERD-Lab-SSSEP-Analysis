---
name: pyside6-gui-cleanup
description: Use for SSSEP PySide6 launcher cleanup, widget/layout changes, folder dialogs, saved GUI settings, worker-thread progress, status/error UX, QAction import checks, and non-blocking GUI behavior in sssep_batch/gui.py.
---

# PySide6 GUI Cleanup

## Workflow

1. Read `AGENTS.md`, `architecture.md`, `README.md`, and
   `tests/test_gui_settings.py`.
2. Keep the PyCharm workflow intact: users run `sssep_bdf_batch_processor.py`
   and interact with the launcher.
3. Use PySide6 only. Do not introduce CustomTkinter or another GUI framework.
4. Import `QAction` from `PySide6.QtGui` if actions are added.
5. Keep long processing work off the UI thread. Use the existing `QThread`
   pattern or an equally simple PySide6 worker pattern.
6. Workers must not mutate widgets directly. Emit signals and let the widget
   layer update UI state.
7. Preserve folder validation through `validate_batch_request()`.
8. Treat GUI saved-folder defaults as local convenience only. Do not edit
   `config.py` from the GUI.
9. Keep errors visible to the user without hiding processing failures. Do not
   add fallbacks that silently continue with the wrong folder or settings.
10. Add or update a lightweight pytest for helper behavior when practical. If a
    full GUI smoke is needed and pytest-qt is not available, document exact
    manual smoke steps instead of adding an unrun dependency.

## Manual Smoke Steps

Use these when widget behavior changes and automated GUI coverage is not
available:

1. Run `sssep_bdf_batch_processor.py` from PyCharm or the project interpreter.
2. Confirm the launcher opens.
3. Choose an input folder and output folder.
4. Confirm Cancel leaves the existing folder text unchanged.
5. Start a small batch or validation-failure path.
6. Confirm controls disable during work, progress/status updates appear, errors
   are shown, and "View Output" only opens an existing output folder.

## Return

Report files touched, whether processing behavior changed, automated tests run,
and manual smoke steps completed or skipped.
