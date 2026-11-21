from __future__ import annotations

import pytest

from integra7_conductor.errors import Integra7Error
from integra7_conductor.midi import sysex
from integra7_conductor.midi.protocol import hex_str


def test_checksum_matches_roland_documented_example():
    # MIDI Implementation p.29: address 18 00 06 00, data 02 -> checksum 60H.
    assert sysex.checksum([0x18, 0x00, 0x06, 0x00, 0x02]) == 0x60
    assert hex_str(sysex.build_dt1(0x10, (0x18, 0x00, 0x06, 0x00), [0x02])) == (
        "F0 41 10 00 00 64 12 18 00 06 00 02 60 F7"
    )


def test_checksum_wraps_to_zero():
    assert sysex.checksum([0x40, 0x40]) == 0
    assert sysex.checksum([]) == 0


def test_rq1_for_studio_set_part():
    assert sysex.studio_set_part_address(1) == (0x18, 0x00, 0x20, 0x00)
    assert sysex.studio_set_part_address(16) == (0x18, 0x00, 0x2F, 0x00)
    msg = sysex.build_rq1(0x10, sysex.studio_set_part_address(2), sysex.SIZE_STUDIO_SET_PART)
    assert hex_str(msg) == "F0 41 10 00 00 64 11 18 00 21 00 00 00 00 4D 7A F7"
    assert sysex.checksum(msg[7:-1]) == 0  # address + size + checksum sums to 0 mod 128


def test_identity_request_and_reply():
    assert hex_str(sysex.build_identity_request()) == "F0 7E 7F 06 01 F7"
    reply = sysex.parse_identity_reply(
        [0xF0, 0x7E, 0x10, 0x06, 0x02, 0x41, 0x64, 0x02, 0, 0, 0, 0, 0, 0, 0xF7]
    )
    assert reply.is_integra7 and reply.device_id == 0x10
    assert sysex.parse_identity_reply([0xF0, 0x7E, 0x10, 0x06, 0x01, 0xF7]) is None


def test_parse_dt1_roundtrip_and_validation():
    msg = sysex.build_dt1(0x10, (0x01, 0, 0, 0), [1, 2, 3])
    dt1 = sysex.parse_dt1(msg, expected_device_id=0x10)
    assert dt1.address == (1, 0, 0, 0) and dt1.data == bytes([1, 2, 3])

    corrupt = bytearray(msg)
    corrupt[-2] ^= 0x01
    for bad, text in [
        (bytes(corrupt), "checksum"),
        (msg[:1] + b"\x42" + msg[2:], "not Roland"),
        (msg[:5] + b"\x65" + msg[6:], "model ID"),
        (sysex.build_rq1(0x10, (1, 0, 0, 0), 4), "not DT1"),
        (msg[:-1], "complete"),
    ]:
        with pytest.raises(Integra7Error, match=text) as info:
            sysex.parse_dt1(bad)
        assert info.value.code == "INVALID_SYSEX"
    with pytest.raises(Integra7Error, match="device ID"):
        sysex.parse_dt1(msg, expected_device_id=0x11)
    sysex.parse_dt1(msg, expected_device_id=0x7F)  # broadcast accepts any responder


def test_collect_block_single_and_fragmented():
    addr = (0x18, 0x00, 0x20, 0x00)
    payload = list(range(0x4D))
    whole = sysex.build_dt1(0x10, addr, payload)
    data, problems = sysex.collect_block([whole], addr, 0x4D, expected_device_id=0x10)
    assert data == bytes(payload) and problems == []

    first = sysex.build_dt1(0x10, addr, payload[:0x20])
    second = sysex.build_dt1(0x10, (0x18, 0x00, 0x20, 0x20), payload[0x20:])
    data, _ = sysex.collect_block([second, first], addr, 0x4D)
    assert data == bytes(payload)

    data, problems = sysex.collect_block([first], addr, 0x4D)
    assert data is None and "incomplete" in problems[0]


def test_collect_block_ignores_unrelated_and_reports_corrupt():
    addr = (0x01, 0, 0, 0)
    other = sysex.build_dt1(0x10, (0x02, 0, 0, 0), [9] * 4)
    corrupt = bytearray(sysex.build_dt1(0x10, addr, [1] * 4))
    corrupt[-2] ^= 0x7F
    data, problems = sysex.collect_block([other, bytes(corrupt)], addr, 4)
    assert data is None and any("checksum" in p for p in problems)


@pytest.mark.parametrize("device_id", [0x0F, 0x20, 0x80, -1])
def test_device_id_range(device_id):
    with pytest.raises(Integra7Error):
        sysex.build_rq1(device_id, (1, 0, 0, 0), 1)


def test_data_bytes_must_be_seven_bit():
    with pytest.raises(Integra7Error) as info:
        sysex.build_dt1(0x10, (1, 0, 0, 0), [0x80])
    assert info.value.code == "INVALID_SYSEX"
