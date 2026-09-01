from importlib.metadata import version
from pathlib import Path

import pytest

from sssep_batch.experiment.runner import (
    PsychoPyUnavailableError,
    _load_psychopy_modules,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_requirements_pin_supported_psychopy_release() -> None:
    requirements = [
        line.strip().casefold()
        for line in (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirements.count("psychopy==2026.2.3") == 1


def test_installed_psychopy_matches_pin_and_task_imports() -> None:
    assert version("psychopy") == "2026.2.3"

    visual, core, keyboard_module = _load_psychopy_modules()

    assert visual.__name__ == "psychopy.visual"
    assert core.__name__ == "psychopy.core"
    assert keyboard_module.__name__ == "psychopy.hardware.keyboard"


def test_missing_psychopy_error_points_to_installer(monkeypatch) -> None:
    def fail_import(_name: str):
        raise ModuleNotFoundError("No module named 'psychopy'")

    monkeypatch.setattr(
        "sssep_batch.experiment.runner.importlib.import_module",
        fail_import,
    )

    with pytest.raises(PsychoPyUnavailableError, match=r"install\.ps1") as error:
        _load_psychopy_modules()

    assert "Python 3.11" in str(error.value)
    assert "-Recreate" in str(error.value)
