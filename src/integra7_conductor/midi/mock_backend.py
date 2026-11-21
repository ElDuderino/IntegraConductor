"""Mock MIDI backend with a small simulated INTEGRA-7.

It records every byte that would be sent and answers documented RQ1 requests, so
service logic (including readback parsing) is testable without hardware. Results
produced through this backend are always reported as ``mocked``.
"""

from __future__ import annotations

from typing import Any

from . import sysex, windows_adapter
from .backend import BACKEND_MOCK, MidiBackend, unwrap

MOCK_PORTS = {
    "inputs": ["INTEGRA-7 0", "INTEGRA-7 CTRL 1"],
    "outputs": ["Microsoft GS Wavetable Synth 0", "INTEGRA-7 1", "INTEGRA-7 CTRL 2"],
}


class FakeIntegra7:
    """Just enough device behavior to exercise bank/program selection and readback."""

    def __init__(self, device_id: int = sysex.DEFAULT_DEVICE_ID) -> None:
        self.device_id = device_id
        self.respond = True  # False simulates a unit that ignores SysEx
        self.control_channel = 16  # 1-16, or 0 for OFF
        self.studio_set_pc = 0
        self.parts = {
            p: {"channel": p, "rx_switch": 1, "msb": 89, "lsb": 64, "program": 0}
            for p in range(1, 17)
        }
        self._pending_bank: dict[int, list[int]] = {}
        self.memory: dict[int, int] = {}  # parameter bytes written with DT1
        self.ignore_writes = False
        self.notes_on: set[tuple[int, int]] = set()

    def receive(self, msg: list[int]) -> list[list[int]]:
        status = msg[0] & 0xF0
        channel = (msg[0] & 0x0F) + 1
        if status == 0xB0 and msg[1] in (0x00, 0x20):
            bank = self._pending_bank.setdefault(channel, [0, 0])
            bank[0 if msg[1] == 0x00 else 1] = msg[2]
        elif status == 0xC0:
            msb, lsb = self._pending_bank.get(channel, [0, 0])
            if channel == self.control_channel and msb == 85:
                self.studio_set_pc = msg[1]
            else:
                for part in self.parts.values():
                    if part["channel"] == channel and part["rx_switch"]:
                        part.update(msb=msb, lsb=lsb, program=msg[1])
        elif status == 0x90 and msg[2] > 0:
            self.notes_on.add((channel, msg[1]))
        elif status in (0x80, 0x90):
            self.notes_on.discard((channel, msg[1]))
        elif msg[0] == 0xF0 and self.respond:
            return self._sysex(msg)
        return []

    def _sysex(self, msg: list[int]) -> list[list[int]]:
        if msg[1] == 0x7E and msg[3:5] == [0x06, 0x01]:
            return [[0xF0, 0x7E, self.device_id, 0x06, 0x02, 0x41, 0x64, 0x02, 0, 0, 0, 0, 0, 0,
                     0xF7]]
        if msg[1] == sysex.ROLAND_ID and msg[6] == sysex.CMD_DT1:
            if not self.ignore_writes:
                start = sysex.address_to_int(msg[7:11])
                for i, value in enumerate(msg[11:-2]):
                    self.memory[start + i] = value
            return []
        if msg[1] != sysex.ROLAND_ID or msg[6] != sysex.CMD_RQ1:
            return []
        if msg[2] not in (self.device_id, sysex.BROADCAST_DEVICE_ID):
            return []
        address = tuple(msg[7:11])
        block = self._block(address)
        if block is None:
            block = self._effect_block(address)
        if block is None:
            return []
        start = sysex.address_to_int(address)
        block = [self.memory.get(start + i, value) for i, value in enumerate(block)]
        return [list(sysex.build_dt1(self.device_id, address, block))]

    _EFFECT_BLOCKS = {0x00: 0x54, 0x04: 0x54, 0x06: 0x63, 0x08: 0x10, 0x09: 0x07}

    def _effect_block(self, address: tuple[int, ...]) -> list[int] | None:
        if address[:2] == (0x18, 0x00) and address[3] == 0 and address[2] in self._EFFECT_BLOCKS:
            return [0] * self._EFFECT_BLOCKS[address[2]]
        return None

    def _block(self, address: tuple[int, ...]) -> list[int] | None:
        if address == sysex.ADDR_SETUP:
            data = [0] * sysex.SIZE_SETUP
            data[sysex.SETUP_SOUND_MODE] = 1
            data[sysex.SETUP_STUDIO_SET_BS_MSB] = 85
            data[sysex.SETUP_STUDIO_SET_PC] = self.studio_set_pc
            return data
        if address == sysex.ADDR_SYSTEM_COMMON:
            data = [0] * sysex.SIZE_SYSTEM_COMMON
            data[sysex.SYSTEM_STUDIO_SET_CONTROL_CHANNEL] = (
                self.control_channel - 1 if self.control_channel else 16
            )
            data[sysex.SYSTEM_RX_PROGRAM_CHANGE] = 1
            data[sysex.SYSTEM_RX_BANK_SELECT] = 1
            return data
        for part, state in self.parts.items():
            if address == sysex.studio_set_part_address(part):
                data = [0] * sysex.SIZE_STUDIO_SET_PART
                data[sysex.PART_RX_CHANNEL] = state["channel"] - 1
                data[sysex.PART_RX_SWITCH] = state["rx_switch"]
                data[sysex.PART_BANK_MSB] = state["msb"]
                data[sysex.PART_BANK_LSB] = state["lsb"]
                data[sysex.PART_PROGRAM] = state["program"]
                return data
        return None


class FakeIO:
    def __init__(self, backend: MockBackend) -> None:
        self._b = backend

    def versions(self) -> dict[str, Any]:
        return {"mido": "mock", "python_rtmidi": "mock"}

    def list_ports(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._b.ports.items()}

    def open_output(self, name: str):
        backend = self._b
        if backend.fail_open:
            raise OSError("mock: port is in use")

        class _Out:
            def send(self, data) -> None:
                if (
                    backend.fail_after_messages is not None
                    and len(backend.sent) >= backend.fail_after_messages
                ):
                    # Fail once, as a transient fault, so cleanup sends can be observed.
                    backend.fail_after_messages = None
                    raise OSError("mock: device disconnected")
                backend.sent.append((name, bytes(data)))
                backend.input_queue.extend(backend.device.receive(list(data)))

            def close(self) -> None:
                pass

        return _Out()

    def open_input(self, name: str):
        backend = self._b

        class _In:
            def poll(self) -> list[list[int]]:
                out, backend.input_queue[:] = list(backend.input_queue), []
                return out

            def close(self) -> None:
                pass

        return _In()


class MockBackend(MidiBackend):
    name = BACKEND_MOCK
    is_mock = True

    def __init__(self, device: FakeIntegra7 | None = None) -> None:
        self.device = device or FakeIntegra7()
        self.ports: dict[str, list[str]] = {k: list(v) for k, v in MOCK_PORTS.items()}
        self.sent: list[tuple[str, bytes]] = []
        self.requests: list[dict[str, Any]] = []
        self.input_queue: list[list[int]] = []
        self.fail_open = False
        self.fail_after_messages: int | None = None
        self._now = 0.0

    # A virtual clock keeps mock transactions instant and deterministic.
    def _sleep(self, seconds: float) -> None:
        self._now += seconds

    def _clock(self) -> float:
        return self._now

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return unwrap(
            windows_adapter.run_request(
                request, lambda: FakeIO(self), sleep=self._sleep, clock=self._clock
            )
        )

    def sent_hex(self) -> list[str]:
        return [" ".join(f"{b:02X}" for b in data) for _, data in self.sent]
