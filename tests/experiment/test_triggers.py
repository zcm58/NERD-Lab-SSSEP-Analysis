"""Tests for the BioSemi serial trigger backend."""

from __future__ import annotations

import importlib

import pytest

from sssep_batch.experiment.triggers import (
    SentTrigger,
    SerialTriggerBackend,
    SerialTriggerError,
    SimulatedTriggerBackend,
)


class _FakePort:
    def __init__(self, *, fail_write: bool = False, bytes_written: int = 1) -> None:
        self.fail_write = fail_write
        self.bytes_written = bytes_written
        self.writes: list[bytes] = []
        self.close_count = 0

    def write(self, payload: bytes) -> int:
        if self.fail_write:
            raise OSError("write failed")
        self.writes.append(payload)
        return self.bytes_written

    def close(self) -> None:
        self.close_count += 1


class _FakeSerialModule:
    EIGHTBITS = 8
    PARITY_NONE = "N"
    STOPBITS_ONE = 1

    def __init__(
        self,
        *,
        fail_open: bool = False,
        fail_write: bool = False,
        bytes_written: int = 1,
    ) -> None:
        self.fail_open = fail_open
        self.open_calls: list[dict[str, object]] = []
        self.port = _FakePort(fail_write=fail_write, bytes_written=bytes_written)

    def Serial(self, **kwargs: object) -> _FakePort:  # noqa: N802
        self.open_calls.append(dict(kwargs))
        if self.fail_open:
            raise OSError("open failed")
        return self.port


def test_simulated_backend_accepts_triggers_without_serial_hardware() -> None:
    backend = SimulatedTriggerBackend()

    backend.connect()
    record = backend.send_trigger(
        11,
        label="left_hand",
        time_s=1.25,
        epoch_index=3,
    )
    backend.close()

    assert record == SentTrigger(11, "left_hand", 1.25, 3)


def test_connect_uses_biosemi_com3_defaults() -> None:
    serial_module = _FakeSerialModule()
    backend = SerialTriggerBackend(serial_module=serial_module)

    backend.connect()

    assert serial_module.open_calls == [
        {
            "port": "COM3",
            "baudrate": 115200,
            "bytesize": _FakeSerialModule.EIGHTBITS,
            "parity": _FakeSerialModule.PARITY_NONE,
            "stopbits": _FakeSerialModule.STOPBITS_ONE,
            "timeout": 0,
            "write_timeout": 0,
            "rtscts": False,
            "dsrdtr": False,
            "xonxoff": False,
        }
    ]


@pytest.mark.parametrize("code", [1, 55, 127, 128, 255])
def test_send_trigger_writes_exactly_one_raw_byte(code: int) -> None:
    serial_module = _FakeSerialModule()
    backend = SerialTriggerBackend(serial_module=serial_module)
    backend.connect()

    record = backend.send_trigger(
        code,
        label="left_hand",
        time_s=1.25,
        epoch_index=3,
    )

    assert serial_module.port.writes == [bytes([code])]
    assert record.code == code
    assert record.label == "left_hand"
    assert record.time_s == 1.25
    assert record.epoch_index == 3
    assert backend.records == (record,)


def test_send_prevalidated_trigger_writes_exactly_one_raw_byte() -> None:
    serial_module = _FakeSerialModule()
    backend = SerialTriggerBackend(serial_module=serial_module)
    backend.connect()

    backend.send_prevalidated_trigger(
        55,
        label="left_hand",
        time_s=1.25,
        epoch_index=3,
    )

    assert serial_module.port.writes == [bytes([55])]
    assert backend.records == (
        SentTrigger(
            code=55,
            label="left_hand",
            time_s=1.25,
            epoch_index=3,
        ),
    )


@pytest.mark.parametrize("code", [-1, 0, 256, None, "55", True])
def test_send_trigger_rejects_codes_outside_event_range(code: object) -> None:
    serial_module = _FakeSerialModule()
    backend = SerialTriggerBackend(serial_module=serial_module)
    backend.connect()

    with pytest.raises((TypeError, ValueError), match="1 to 255"):
        backend.send_trigger(code)  # type: ignore[arg-type]

    assert serial_module.port.writes == []
    assert backend.records == ()


def test_connect_and_write_failures_are_immediate_and_not_recorded() -> None:
    open_failure = SerialTriggerBackend(
        serial_module=_FakeSerialModule(fail_open=True)
    )
    with pytest.raises(SerialTriggerError, match="Unable to open"):
        open_failure.connect()

    serial_module = _FakeSerialModule(fail_write=True)
    write_failure = SerialTriggerBackend(serial_module=serial_module)
    write_failure.connect()
    with pytest.raises(SerialTriggerError, match="Unable to send trigger code 8"):
        write_failure.send_trigger(8)

    assert write_failure.records == ()


@pytest.mark.parametrize("bytes_written", [0, 2])
def test_short_or_extra_write_is_not_recorded(bytes_written: int) -> None:
    serial_module = _FakeSerialModule(bytes_written=bytes_written)
    backend = SerialTriggerBackend(serial_module=serial_module)
    backend.connect()

    with pytest.raises(SerialTriggerError, match="expected 1"):
        backend.send_trigger(8)

    assert backend.records == ()


def test_send_requires_connection_and_close_is_idempotent() -> None:
    serial_module = _FakeSerialModule()
    backend = SerialTriggerBackend(serial_module=serial_module)

    with pytest.raises(SerialTriggerError, match="not connected"):
        backend.send_trigger(8)

    backend.connect()
    backend.close()
    backend.close()

    assert serial_module.port.close_count == 1


def test_missing_pyserial_has_clear_setup_error(monkeypatch) -> None:
    def _missing_serial(_name: str) -> object:
        raise ModuleNotFoundError("serial")

    monkeypatch.setattr(importlib, "import_module", _missing_serial)

    with pytest.raises(SerialTriggerError, match="pyserial is required"):
        SerialTriggerBackend().connect()
