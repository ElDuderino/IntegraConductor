"""Roland SysEx (RQ1/DT1) for the INTEGRA-7, per the published MIDI Implementation.

Only addresses printed in Roland's Parameter Address Map are defined here.
Undocumented address ranges (for example the community-reported 0F 00 xx xx
expansion commands) are deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import errors
from ..errors import Integra7Error, usage_error

ROLAND_ID = 0x41
MODEL_ID = (0x00, 0x00, 0x64)
CMD_RQ1 = 0x11
CMD_DT1 = 0x12
DEFAULT_DEVICE_ID = 0x10  # displayed as 17 on the unit
BROADCAST_DEVICE_ID = 0x7F

# Documented block start addresses and total sizes. The MI says requests must use
# the fixed start address and size of a block, so whole blocks are always requested.
ADDR_SETUP = (0x01, 0x00, 0x00, 0x00)
SIZE_SETUP = 0x38
ADDR_SYSTEM_COMMON = (0x02, 0x00, 0x00, 0x00)
SIZE_SYSTEM_COMMON = 0x2F
ADDR_TEMP_STUDIO_SET = (0x18, 0x00, 0x00, 0x00)
OFFSET_STUDIO_SET_PART_1 = 0x20  # third address byte; +1 per part
SIZE_STUDIO_SET_PART = 0x4D

# Offsets inside the blocks above.
SETUP_SOUND_MODE = 0x00
SETUP_STUDIO_SET_BS_MSB = 0x04
SETUP_STUDIO_SET_BS_LSB = 0x05
SETUP_STUDIO_SET_PC = 0x06
SYSTEM_STUDIO_SET_CONTROL_CHANNEL = 0x11  # 0-15 = ch 1-16, 16 = OFF
SYSTEM_RX_PROGRAM_CHANGE = 0x29
SYSTEM_RX_BANK_SELECT = 0x2A
PART_RX_CHANNEL = 0x00  # 0-15 = ch 1-16
PART_RX_SWITCH = 0x01
PART_BANK_MSB = 0x06
PART_BANK_LSB = 0x07
PART_PROGRAM = 0x08
SOUND_MODES = {1: "STUDIO", 2: "GM1", 3: "GM2", 4: "GS"}


def checksum(payload: bytes | list[int] | tuple[int, ...]) -> int:
    """Roland checksum over address + data (or size): (128 - sum % 128) % 128."""
    return (128 - (sum(payload) % 128)) % 128


def validate_device_id(device_id: int) -> int:
    if isinstance(device_id, bool) or not isinstance(device_id, int):
        raise usage_error(errors.INVALID_ARGUMENT, f"device_id must be an integer: {device_id!r}")
    if not (0x10 <= device_id <= 0x1F or device_id == BROADCAST_DEVICE_ID):
        raise usage_error(
            errors.INVALID_ARGUMENT,
            f"device_id must be 0x10-0x1F (displayed 17-32) or 0x7F, got {device_id:#04x}",
        )
    return device_id


def _seven_bit(values, what: str) -> tuple[int, ...]:
    values = tuple(values)
    if any((not isinstance(v, int)) or v < 0 or v > 0x7F for v in values):
        raise usage_error(errors.INVALID_SYSEX, f"{what} bytes must be 0-127: {values!r}")
    return values


def size_bytes(size: int) -> tuple[int, int, int, int]:
    return ((size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F)


def address_to_int(address) -> int:
    a = _seven_bit(address, "address")
    return (a[0] << 21) | (a[1] << 14) | (a[2] << 7) | a[3]


def address_add(address, offset: int) -> tuple[int, int, int, int]:
    """Add a byte offset to a 4-byte, 7-bits-per-byte Roland address."""
    value = address_to_int(address) + offset
    return ((value >> 21) & 0x7F, (value >> 14) & 0x7F, (value >> 7) & 0x7F, value & 0x7F)


def temporary_tone_address(part: int) -> tuple[int, int, int, int]:
    """Start of Temporary Tone for a part: 19 00 00 00, 19 20 00 00, ... 1C 60 00 00."""
    if not 1 <= part <= 16:
        raise usage_error(errors.INVALID_PART, f"part must be 1-16, got {part}")
    return address_add((0x19, 0x00, 0x00, 0x00), (part - 1) * (0x20 << 14))


def studio_set_part_address(part: int) -> tuple[int, int, int, int]:
    if not 1 <= part <= 16:
        raise usage_error(errors.INVALID_PART, f"part must be 1-16, got {part}")
    a = ADDR_TEMP_STUDIO_SET
    return (a[0], a[1], OFFSET_STUDIO_SET_PART_1 + part - 1, 0x00)


def build_rq1(device_id: int, address, size: int) -> bytes:
    addr = _seven_bit(address, "address")
    if len(addr) != 4:
        raise usage_error(errors.INVALID_SYSEX, "address must be 4 bytes")
    body = (*addr, *size_bytes(size))
    return bytes(
        [0xF0, ROLAND_ID, validate_device_id(device_id), *MODEL_ID, CMD_RQ1, *body,
         checksum(body), 0xF7]
    )


def build_dt1(device_id: int, address, data) -> bytes:
    """Encode a DT1 write. Not exposed to agents as a raw-SysEx facility."""
    addr = _seven_bit(address, "address")
    payload = _seven_bit(data, "data")
    if len(addr) != 4 or not payload:
        raise usage_error(errors.INVALID_SYSEX, "DT1 needs a 4-byte address and data")
    body = (*addr, *payload)
    return bytes(
        [0xF0, ROLAND_ID, validate_device_id(device_id), *MODEL_ID, CMD_DT1, *body,
         checksum(body), 0xF7]
    )


def build_identity_request(device_id: int = BROADCAST_DEVICE_ID) -> bytes:
    return bytes([0xF0, 0x7E, validate_device_id(device_id), 0x06, 0x01, 0xF7])


@dataclass(frozen=True)
class DT1:
    device_id: int
    address: tuple[int, int, int, int]
    data: bytes


@dataclass(frozen=True)
class IdentityReply:
    device_id: int
    manufacturer: int
    family_code: tuple[int, int]
    family_number: tuple[int, int]
    software_revision: tuple[int, int, int, int]

    @property
    def is_integra7(self) -> bool:
        return self.manufacturer == ROLAND_ID and self.family_code == (0x64, 0x02)


def parse_dt1(message, *, expected_device_id: int | None = None) -> DT1:
    """Validate framing, manufacturer, model, command and checksum of a DT1 message."""
    m = bytes(message)
    if len(m) < 14 or m[0] != 0xF0 or m[-1] != 0xF7:
        raise Integra7Error(errors.INVALID_SYSEX, "not a complete SysEx DT1 message")
    if m[1] != ROLAND_ID:
        raise Integra7Error(errors.INVALID_SYSEX, f"manufacturer {m[1]:#04x} is not Roland")
    if tuple(m[3:6]) != MODEL_ID:
        raise Integra7Error(errors.INVALID_SYSEX, "model ID is not INTEGRA-7 (00 00 64)")
    if m[6] != CMD_DT1:
        raise Integra7Error(errors.INVALID_SYSEX, f"command {m[6]:#04x} is not DT1")
    body, received = m[7:-2], m[-2]
    if checksum(body) != received:
        raise Integra7Error(
            errors.INVALID_SYSEX,
            f"checksum mismatch: computed {checksum(body):#04x}, received {received:#04x}",
        )
    if (
        expected_device_id is not None
        and expected_device_id != BROADCAST_DEVICE_ID
        and m[2] != expected_device_id
    ):
        raise Integra7Error(
            errors.INVALID_SYSEX,
            f"reply device ID {m[2]:#04x} does not match configured {expected_device_id:#04x}",
        )
    return DT1(device_id=m[2], address=(body[0], body[1], body[2], body[3]), data=bytes(body[4:]))


def parse_identity_reply(message) -> IdentityReply | None:
    m = bytes(message)
    if len(m) != 15 or m[0] != 0xF0 or m[1] != 0x7E or m[3:5] != b"\x06\x02" or m[-1] != 0xF7:
        return None
    return IdentityReply(
        device_id=m[2],
        manufacturer=m[5],
        family_code=(m[6], m[7]),
        family_number=(m[8], m[9]),
        software_revision=(m[10], m[11], m[12], m[13]),
    )


def collect_block(
    replies, address, size: int, *, expected_device_id: int | None = None
) -> tuple[bytes | None, list[str]]:
    """Find the DT1 data for a requested block among raw replies.

    Handles a reply split into consecutive packets (the unit splits data above 256
    bytes). Returns (data or None, problems). Unrelated or invalid messages are
    reported, never trusted.
    """
    start = address_to_int(address)
    problems: list[str] = []
    chunks: dict[int, bytes] = {}
    for raw in replies:
        try:
            dt1 = parse_dt1(raw, expected_device_id=expected_device_id)
        except Integra7Error as exc:
            if bytes(raw[:2]) == bytes([0xF0, ROLAND_ID]):
                problems.append(exc.message)
            continue
        offset = address_to_int(dt1.address) - start
        if 0 <= offset < size:
            chunks[offset] = dt1.data
    data = b""
    while len(data) < size and len(data) in chunks:
        data += chunks[len(data)]
    if len(data) < size:
        if chunks:
            problems.append(f"incomplete reply: got {len(data)} of {size} bytes")
        return None, problems
    return data[:size], problems
