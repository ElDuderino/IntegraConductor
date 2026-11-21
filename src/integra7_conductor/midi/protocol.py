"""Channel-message encoding and range validation.

Human-facing values: part 1-16, channel 1-16, displayed program 1-128.
Wire values: channel nibble 0-15, program 0-127. Conversions happen only here.
"""

from __future__ import annotations

from .. import errors
from ..errors import usage_error

CC_BANK_MSB = 0x00
CC_BANK_LSB = 0x20
STUDIO_SET_BANK_MSB = 85
STUDIO_SET_BANK_LSB = 0
STUDIO_SET_COUNT = 64

AUDITION_MAX_DURATION_MS = 5000
AUDITION_DEFAULT_DURATION_MS = 800
AUDITION_DEFAULT_VELOCITY = 90
AUDITION_DEFAULT_NOTE = 60


def _int(value, name: str, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise usage_error(code, f"{name} must be an integer, got {value!r}")
    return value


def validate_part(part) -> int:
    part = _int(part, "part", errors.INVALID_PART)
    if not 1 <= part <= 16:
        raise usage_error(errors.INVALID_PART, f"part must be 1-16, got {part}")
    return part


def validate_channel(channel) -> int:
    channel = _int(channel, "channel", errors.INVALID_CHANNEL)
    if not 1 <= channel <= 16:
        raise usage_error(errors.INVALID_CHANNEL, f"MIDI channel must be 1-16, got {channel}")
    return channel


def validate_bank(value, name: str = "bank value") -> int:
    value = _int(value, name, errors.INVALID_BANK)
    if not 0 <= value <= 127:
        raise usage_error(errors.INVALID_BANK, f"{name} must be 0-127, got {value}")
    return value


def validate_program(program) -> int:
    """Zero-based MIDI program number (0-127)."""
    program = _int(program, "program", errors.INVALID_PROGRAM)
    if not 0 <= program <= 127:
        raise usage_error(
            errors.INVALID_PROGRAM, f"zero-based MIDI program must be 0-127, got {program}"
        )
    return program


def program_from_display(display_pc) -> int:
    """Convert Roland's printed PC (1-128) to the zero-based wire value."""
    display_pc = _int(display_pc, "displayed program", errors.INVALID_PROGRAM)
    if not 1 <= display_pc <= 128:
        raise usage_error(
            errors.INVALID_PROGRAM, f"displayed program must be 1-128, got {display_pc}"
        )
    return display_pc - 1


def validate_note(note) -> int:
    note = _int(note, "note", errors.INVALID_NOTE)
    if not 0 <= note <= 127:
        raise usage_error(errors.INVALID_NOTE, f"note must be 0-127, got {note}")
    return note


def validate_velocity(velocity) -> int:
    velocity = _int(velocity, "velocity", errors.INVALID_NOTE)
    if not 1 <= velocity <= 127:
        raise usage_error(errors.INVALID_NOTE, f"note-on velocity must be 1-127, got {velocity}")
    return velocity


def validate_duration_ms(duration_ms) -> int:
    duration_ms = _int(duration_ms, "duration_ms", errors.INVALID_ARGUMENT)
    if not 1 <= duration_ms <= AUDITION_MAX_DURATION_MS:
        raise usage_error(
            errors.INVALID_ARGUMENT,
            f"duration_ms must be 1-{AUDITION_MAX_DURATION_MS}, got {duration_ms}",
        )
    return duration_ms


def validate_studio_set_number(number) -> int:
    number = _int(number, "studio set number", errors.INVALID_PROGRAM)
    if not 1 <= number <= STUDIO_SET_COUNT:
        raise usage_error(
            errors.INVALID_PROGRAM, f"studio set number must be 1-{STUDIO_SET_COUNT}, got {number}"
        )
    return number


def control_change(channel: int, controller: int, value: int) -> bytes:
    ch = validate_channel(channel) - 1
    return bytes([0xB0 | ch, validate_bank(controller, "controller"), validate_bank(value)])


def program_change(channel: int, program: int) -> bytes:
    ch = validate_channel(channel) - 1
    return bytes([0xC0 | ch, validate_program(program)])


def note_on(channel: int, note: int, velocity: int) -> bytes:
    ch = validate_channel(channel) - 1
    return bytes([0x90 | ch, validate_note(note), validate_velocity(velocity)])


def note_off(channel: int, note: int) -> bytes:
    ch = validate_channel(channel) - 1
    return bytes([0x80 | ch, validate_note(note), 0])


def pitch_bend(channel: int, value: int) -> bytes:
    """Pitch bend, -8192 (full down) to +8191 (full up); 0 is centered."""
    ch = validate_channel(channel) - 1
    value = _int(value, "pitch bend", errors.INVALID_ARGUMENT)
    if not -8192 <= value <= 8191:
        raise usage_error(errors.INVALID_ARGUMENT, f"pitch bend must be -8192..8191, got {value}")
    raw = value + 8192
    return bytes([0xE0 | ch, raw & 0x7F, (raw >> 7) & 0x7F])


def channel_pressure(channel: int, value: int) -> bytes:
    """Channel aftertouch, 0-127."""
    ch = validate_channel(channel) - 1
    return bytes([0xD0 | ch, validate_bank(value, "aftertouch")])


def bank_program_select(channel: int, msb: int, lsb: int, program: int) -> list[bytes]:
    """CC#0 (bank MSB), CC#32 (bank LSB), then Program Change with a zero-based program."""
    return [
        control_change(channel, CC_BANK_MSB, validate_bank(msb, "bank MSB")),
        control_change(channel, CC_BANK_LSB, validate_bank(lsb, "bank LSB")),
        program_change(channel, program),
    ]


def hex_str(message: bytes | list[int] | tuple[int, ...]) -> str:
    return " ".join(f"{b:02X}" for b in message)
