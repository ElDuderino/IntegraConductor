"""Application context and shared transaction helpers for the service layer."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from .. import errors
from ..catalog import database
from ..config import Config
from ..errors import Integra7Error
from ..midi import sysex
from ..midi.backend import (
    BACKEND_MOCK,
    BACKEND_NATIVE,
    MidiBackend,
    NativeBackend,
    request_step,
)
from ..models import MOCKED, NOT_SENT, SENT_UNVERIFIED, Patch

NO_REPLY_HINT = (
    "No SysEx reply. Check that the unit is on and connected, SYSTEM > MIDI > Rx Exclusive is "
    "ON, device_id matches the unit (default 17 = 0x10), and input_port names the INTEGRA-7 "
    "MIDI input (`integra7 ports`)."
)


def make_backend(config: Config) -> MidiBackend:
    if config.backend == BACKEND_MOCK:
        from ..midi import windows_adapter
        from ..midi.mock_backend import MockBackend

        mock = MockBackend()
        # Whatever port names the real setup uses, the simulated device has them too.
        for name, direction in (
            (config.performance_port, "outputs"),
            (config.control_port, "outputs"),
            (config.input_port, "inputs"),
        ):
            try:
                windows_adapter.resolve_port(name, mock.ports[direction], direction)
            except windows_adapter.AdapterError:
                mock.ports[direction].append(name)
        return mock
    if config.backend == BACKEND_NATIVE:
        return NativeBackend(config.lock_path(), config.lock_timeout_s)
    from ..midi.wsl_interop import WindowsBackend

    return WindowsBackend(
        windows_python=config.windows_python,
        windows_adapter_exe=config.windows_adapter,
        timeout_s=config.adapter_timeout_s,
        lock_path=config.lock_path(),
        lock_timeout_s=config.lock_timeout_s,
    )


class AppContext:
    """Everything a service call needs. CLI and MCP build one of these per call."""

    def __init__(self, config: Config, backend: MidiBackend | None = None) -> None:
        self.config = config
        self._backend = backend
        self._conn: sqlite3.Connection | None = None
        self._patches: list[Patch] | None = None
        self._aliases: dict[str, list[str]] | None = None

    @property
    def backend(self) -> MidiBackend:
        if self._backend is None:
            self._backend = make_backend(self.config)
        return self._backend

    @property
    def backend_name(self) -> str:
        return self._backend.name if self._backend is not None else self.config.backend

    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = database.open_catalog(self.config.resolved_db_path())
        return self._conn

    def patches(self) -> list[Patch]:
        if self._patches is None:
            self._patches = database.all_patches(self.conn())
        return self._patches

    def aliases(self) -> dict[str, list[str]]:
        if self._aliases is None:
            self._aliases = database.aliases_by_patch(self.conn())
        return self._aliases

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def sysex_out_port(self) -> str:
        c = self.config
        return c.performance_port if c.sysex_port == "performance" else c.control_port

    def live_inject(self, messages: Sequence[bytes]) -> bool:
        """Hand messages to a running `integra7 play`, if there is one.

        Playback holds the MIDI port for its whole length, so a second command
        cannot open it. Returns False when nothing is playing (the caller then
        sends normally).
        """
        path = self.config.live_path()
        if not path.exists():
            return False
        if not self.backend.is_busy():
            path.unlink(missing_ok=True)  # left over from an interrupted playback
            return False
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps([list(m) for m in messages]) + "\n")
        return True

    def sent_status(self) -> str:
        """Status for bytes that left through this backend without a matching readback."""
        return MOCKED if self.backend.is_mock else SENT_UNVERIFIED

    def rq1_step(self, address, size: int) -> dict[str, Any]:
        return request_step(
            self.sysex_out_port(),
            sysex.build_rq1(self.config.device_id, address, size),
            self.config.readback_timeout_ms,
        )

    def transact(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Run steps as one atomic hardware transaction, tagging failures with a status."""
        try:
            return self.backend.transact(steps, input_port=self.config.input_port)
        except Integra7Error as exc:
            sent = exc.details.get("sent") if isinstance(exc.details, dict) else None
            if exc.code == errors.DEVICE_TIMEOUT:
                exc.verification_status = SENT_UNVERIFIED  # unknown; do not claim not_sent
            else:
                exc.verification_status = self.sent_status() if sent else NOT_SENT
            raise


def block_from_reply(ctx: AppContext, result: dict[str, Any], index: int, address, size: int):
    """Extract one requested block from a transaction result.

    Returns (data or None, info) where info explains the outcome without guessing.
    """
    replies = result.get("replies") or []
    entry = replies[index] if index < len(replies) else None
    if entry is None:
        return None, {"status": "skipped", "reason": "no request was made"}
    if entry.get("skipped"):
        input_error = (result.get("input") or {}).get("error") or {}
        return None, {
            "status": "skipped",
            "reason": entry["skipped"],
            "input_error": input_error or None,
        }
    data, problems = sysex.collect_block(
        entry.get("messages") or [], address, size, expected_device_id=ctx.config.device_id
    )
    if data is None:
        status = "no_reply" if not entry.get("messages") else "invalid_reply"
        return None, {"status": status, "problems": problems}
    return data, {"status": "received", "problems": problems}


def read_blocks(
    ctx: AppContext, requests: Sequence[tuple[tuple[int, ...], int]]
) -> list[bytes]:
    """Read documented blocks; raise a structured error if any cannot be read."""
    result = ctx.transact([ctx.rq1_step(addr, size) for addr, size in requests])
    blocks = []
    for index, (addr, size) in enumerate(requests):
        data, info = block_from_reply(ctx, result, index, addr, size)
        if data is None:
            input_error = info.get("input_error")
            if input_error:
                raise Integra7Error(
                    input_error.get("code", errors.PORT_NOT_FOUND),
                    f"Cannot read from the device: {input_error.get('message')}",
                    details=input_error.get("details"),
                    hint=input_error.get("hint"),
                )
            raise Integra7Error(
                errors.DEVICE_TIMEOUT,
                "The device did not return the requested data "
                f"(address {' '.join(f'{b:02X}' for b in addr)}: {info['status']})",
                details={"readback": info, "input": result.get("input")},
                hint=NO_REPLY_HINT,
            )
        blocks.append(data)
    return blocks
