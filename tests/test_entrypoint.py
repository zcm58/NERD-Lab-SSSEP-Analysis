"""Checks for the beginner-facing GUI entrypoint."""

import os
import sys
from types import ModuleType

import main as gui_entrypoint
import sssep_bdf_batch_processor as compatibility_entrypoint


def test_main_opens_gui_after_limiting_native_threads(monkeypatch) -> None:
    fake_gui = ModuleType("sssep_batch.gui")
    fake_gui.launch_gui = lambda: 7  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sssep_batch.gui", fake_gui)
    for env_name in gui_entrypoint._NATIVE_THREAD_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    assert gui_entrypoint.main() == 7
    assert compatibility_entrypoint.main is gui_entrypoint.main
    assert all(
        os.environ[env_name] == "1"
        for env_name in gui_entrypoint._NATIVE_THREAD_ENV_VARS
    )
