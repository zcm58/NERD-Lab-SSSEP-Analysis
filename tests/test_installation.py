from importlib.metadata import version
from pathlib import Path

from PySide6.QtOpenGL import QOpenGLWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _runtime_requirements() -> list[str]:
    return [
        line.strip().casefold()
        for line in (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_requirements_use_qt_presentation_without_psychopy() -> None:
    requirements = _runtime_requirements()

    assert requirements.count("pyside6==6.9.1") == 1
    assert requirements.count("pyserial==3.5") == 1
    assert not any(line.startswith("psychopy") for line in requirements)


def test_installed_task_libraries_match_pins() -> None:
    assert version("PySide6") == "6.9.1"
    assert version("pyserial") == "3.5"
    assert hasattr(QOpenGLWindow, "frameSwapped")


def test_installer_creates_a_python_313_environment() -> None:
    installer = (PROJECT_ROOT / "install.ps1").read_text(encoding="utf-8")

    assert '"3.13"' in installer
    assert '"-3.13"' in installer
    assert "QOpenGLWindow" in installer
    assert "psychopy" not in installer.casefold()
