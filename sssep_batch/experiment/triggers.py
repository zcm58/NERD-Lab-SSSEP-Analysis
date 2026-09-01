"""Hardware and simulated trigger backends for the participant task."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any


BIOSEMI_SERIAL_PORT = "COM3"


class SerialTriggerError(RuntimeError):
    """Raised when a BioSemi trigger cannot be sent."""


@dataclass(frozen=True, slots=True)
class SentTrigger:
    """One trigger that the serial port accepted successfully."""

    code: int
    label: str | None = None
    time_s: float | None = None
    epoch_index: int | None = None


class SerialTriggerBackend:
    """Write one-byte event markers to a BioSemi USB trigger interface."""

    def __init__(
        self,
        port: str = BIOSEMI_SERIAL_PORT,
        baudrate: int = 115200,
        *,
        serial_module: ModuleType | Any | None = None,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial_module = serial_module
        self._connection: Any | None = None
        self._raw_records: list[tuple[int, str | None, float | None, int | None]] = []

    @property
    def records(self) -> tuple[SentTrigger, ...]:
        """Return triggers whose one-byte serial writes succeeded."""

        return tuple(SentTrigger(*record) for record in self._raw_records)

    def connect(self) -> None:
        """Open fixed COM3 using FPVS Studio's serial settings."""

        if self._connection is not None:
            return
        serial_module = self._serial_module or _load_serial_module()
        try:
            self._connection = serial_module.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial_module.EIGHTBITS,
                parity=serial_module.PARITY_NONE,
                stopbits=serial_module.STOPBITS_ONE,
                timeout=0,
                write_timeout=0,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
        except Exception as exc:
            raise SerialTriggerError(
                f"Unable to open BioSemi serial trigger port {self._port!r} at "
                f"{self._baudrate} baud: {exc}"
            ) from exc

    def send_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> SentTrigger:
        """Write one event byte and record it only after a successful write."""

        validated_code = _validate_event_code(code)
        self.send_prevalidated_trigger(
            validated_code,
            label=label,
            time_s=time_s,
            epoch_index=epoch_index,
        )
        return SentTrigger(validated_code, label, time_s, epoch_index)

    def send_prevalidated_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> None:
        """Write an already-validated event without hot-path model creation."""

        if self._connection is None:
            raise SerialTriggerError("BioSemi serial trigger port is not connected.")

        try:
            bytes_written = self._connection.write(bytes([code]))
        except Exception as exc:
            raise SerialTriggerError(
                f"Unable to send trigger code {code} on {self._port!r}: {exc}"
            ) from exc
        if bytes_written != 1:
            raise SerialTriggerError(
                f"Unable to send trigger code {code} on {self._port!r}: "
                f"serial write returned {bytes_written!r}, expected 1."
            )
        self._raw_records.append((code, label, time_s, epoch_index))

    def close(self) -> None:
        """Close the serial port; repeated calls are safe."""

        connection = self._connection
        self._connection = None
        if connection is not None:
            connection.close()


class SimulatedTriggerBackend:
    """Exercise task timing without opening a serial connection."""

    def connect(self) -> None:
        """Prepare test mode without opening COM3."""

    def send_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> SentTrigger:
        """Validate one simulated trigger without hardware output."""

        validated_code = _validate_event_code(code)
        return SentTrigger(validated_code, label, time_s, epoch_index)

    def send_prevalidated_trigger(
        self,
        code: int,
        *,
        label: str | None = None,
        time_s: float | None = None,
        epoch_index: int | None = None,
    ) -> None:
        """Accept an already-validated trigger without hardware output."""

    def close(self) -> None:
        """Finish test mode without hardware cleanup."""


def _validate_event_code(code: object) -> int:
    if not isinstance(code, int) or isinstance(code, bool):
        raise TypeError("Trigger code must be an integer from 1 to 255.")
    if code < 1 or code > 255:
        raise ValueError("Trigger code must be an integer from 1 to 255.")
    return code


def _load_serial_module() -> ModuleType:
    try:
        return importlib.import_module("serial")
    except ModuleNotFoundError as exc:
        raise SerialTriggerError(
            "pyserial is required for BioSemi trigger output but is not installed."
        ) from exc
