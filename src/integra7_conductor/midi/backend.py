"""Backend interface shared by mock, Windows-adapter and native MIDI access.

Every backend accepts the same adapter request dictionaries (see
windows_adapter.py) and returns the adapter's ``data`` dictionary, so the service
layer is identical for offline tests and real hardware.
"""

from __future__ import annotations

import contextlib
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .. import errors
from ..errors import Integra7Error
from . import windows_adapter

BACKEND_MOCK = "mock"
BACKEND_WINDOWS = "windows"
BACKEND_NATIVE = "native"
BACKENDS = (BACKEND_MOCK, BACKEND_WINDOWS, BACKEND_NATIVE)


def send_step(port: str, messages: list[bytes]) -> dict[str, Any]:
    return {"type": "send", "port": port, "messages": [list(m) for m in messages]}


def sleep_step(ms: int) -> dict[str, Any]:
    return {"type": "sleep", "ms": int(ms)}


def request_step(port: str, message: bytes, timeout_ms: int, quiet_ms: int = 60) -> dict[str, Any]:
    return {
        "type": "request",
        "port": port,
        "message": list(message),
        "timeout_ms": int(timeout_ms),
        "quiet_ms": int(quiet_ms),
    }


def sequence_step(
    port: str, events: list[tuple[float, bytes]], inject_file: str | None = None
) -> dict[str, Any]:
    """Timed playback: (offset in ms from the step's start, message) pairs.

    ``inject_file`` (a path the adapter process can read) lets other commands feed
    messages into the running sequence; see AppContext.live_inject.
    """
    step: dict[str, Any] = {
        "type": "sequence",
        "port": port,
        "events": [{"t_ms": round(t, 1), "message": list(m)} for t, m in events],
    }
    if inject_file:
        step["inject_file"] = inject_file
    return step


def unwrap(response: dict[str, Any]) -> dict[str, Any]:
    """Turn an adapter response envelope into data, or raise a structured error."""
    if response.get("ok"):
        return response.get("data") or {}
    err = response.get("error") or {}
    raise Integra7Error(
        err.get("code") or errors.ADAPTER_FAILED,
        err.get("message") or "MIDI adapter failed",
        details=err.get("details"),
        hint=err.get("hint"),
    )


class MidiBackend(ABC):
    name: str
    is_mock = False

    @abstractmethod
    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run one adapter request; return its data or raise Integra7Error."""

    def list_ports(self) -> dict[str, Any]:
        return self.call({"op": "ports"})

    def adapter_path(self, path: Path) -> str:
        """A local path as the adapter process must spell it."""
        return str(path)

    def is_busy(self) -> bool:
        """True while another process holds the hardware (for example a running `play`)."""
        return False

    def transact(
        self, steps: list[dict[str, Any]], *, input_port: str | None = None
    ) -> dict[str, Any]:
        return self.call({"op": "transact", "steps": steps, "input_port": input_port})


@contextlib.contextmanager
def hardware_lock(path: Path, timeout_s: float):
    """Serialize hardware transactions across processes (bank select + PC must not interleave)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")  # noqa: SIM115 - held for the lock's lifetime
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                _lock(fh)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise Integra7Error(
                        errors.DEVICE_BUSY,
                        f"Another integra7 process held the hardware lock for {timeout_s:g}s",
                        details={"lock_file": str(path)},
                        hint="Retry shortly; hardware operations are serialized.",
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()


def lock_is_held(path: Path) -> bool:
    try:
        with hardware_lock(path, 0):
            return False
    except Integra7Error:
        return True


if os.name == "nt":  # pragma: no cover - exercised only on native Windows
    import msvcrt

    def _lock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]

    def _unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]

else:
    import fcntl

    def _lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class NativeBackend(MidiBackend):
    """In-process mido/python-rtmidi. Used when the CLI itself runs on Windows
    (or on Linux/macOS with a directly attached device)."""

    name = BACKEND_NATIVE

    def __init__(self, lock_path: Path, lock_timeout_s: float) -> None:
        self._lock_path = lock_path
        self._lock_timeout_s = lock_timeout_s

    def is_busy(self) -> bool:
        return lock_is_held(self._lock_path)

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("op") != "transact":
            return unwrap(windows_adapter.run_request(request, windows_adapter.default_io))
        with hardware_lock(self._lock_path, self._lock_timeout_s):
            return unwrap(windows_adapter.run_request(request, windows_adapter.default_io))
