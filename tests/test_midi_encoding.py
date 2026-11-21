from __future__ import annotations

import pytest

from integra7_conductor.errors import Integra7Error
from integra7_conductor.midi import protocol


def hexes(messages):
    return [protocol.hex_str(m) for m in messages]


def test_full_grand_1_on_channel_1_exact_bytes():
    assert hexes(protocol.bank_program_select(1, 89, 64, 0)) == ["B0 00 59", "B0 20 40", "C0 00"]


def test_channel_is_one_based_for_humans_zero_based_on_wire():
    assert hexes(protocol.bank_program_select(4, 89, 64, 0)) == ["B3 00 59", "B3 20 40", "C3 00"]
    assert hexes(protocol.bank_program_select(16, 85, 0, 11)) == ["BF 00 55", "BF 20 00", "CF 0B"]


def test_program_is_zero_based_and_display_pc_converts():
    assert protocol.program_change(1, 127) == bytes([0xC0, 0x7F])
    assert protocol.program_from_display(1) == 0
    assert protocol.program_from_display(128) == 127


def test_notes():
    assert protocol.note_on(3, 60, 90) == bytes([0x92, 60, 90])
    assert protocol.note_off(3, 60) == bytes([0x82, 60, 0])


@pytest.mark.parametrize(
    ("fn", "args", "code"),
    [
        (protocol.validate_channel, (0,), "INVALID_CHANNEL"),
        (protocol.validate_channel, (17,), "INVALID_CHANNEL"),
        (protocol.validate_channel, ("1",), "INVALID_CHANNEL"),
        (protocol.validate_channel, (True,), "INVALID_CHANNEL"),
        (protocol.validate_part, (0,), "INVALID_PART"),
        (protocol.validate_part, (17,), "INVALID_PART"),
        (protocol.validate_bank, (128,), "INVALID_BANK"),
        (protocol.validate_bank, (-1,), "INVALID_BANK"),
        (protocol.validate_program, (128,), "INVALID_PROGRAM"),
        (protocol.validate_program, (-1,), "INVALID_PROGRAM"),
        (protocol.program_from_display, (0,), "INVALID_PROGRAM"),
        (protocol.program_from_display, (129,), "INVALID_PROGRAM"),
        (protocol.validate_note, (128,), "INVALID_NOTE"),
        (protocol.validate_velocity, (0,), "INVALID_NOTE"),
        (protocol.validate_velocity, (128,), "INVALID_NOTE"),
        (protocol.validate_duration_ms, (0,), "INVALID_ARGUMENT"),
        (protocol.validate_duration_ms, (5001,), "INVALID_ARGUMENT"),
        (protocol.validate_studio_set_number, (0,), "INVALID_PROGRAM"),
        (protocol.validate_studio_set_number, (65,), "INVALID_PROGRAM"),
        (protocol.bank_program_select, (1, 128, 0, 0), "INVALID_BANK"),
        (protocol.bank_program_select, (0, 89, 64, 0), "INVALID_CHANNEL"),
    ],
)
def test_out_of_range_values_are_rejected(fn, args, code):
    with pytest.raises(Integra7Error) as info:
        fn(*args)
    assert info.value.code == code
    assert info.value.exit_code == 2
