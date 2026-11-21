from __future__ import annotations

import json

import pytest

from integra7_conductor import cli
from integra7_conductor.errors import Integra7Error
from integra7_conductor.midi import sysex
from integra7_conductor.services import fx, play


def test_dt1_bytes_match_rolands_documented_example(ctx, backend):
    # MIDI Implementation p.29: Reverb Type = Room 2 -> F0 41 10 00 00 64 12 18 00 06 00 02 60 F7
    result = fx.apply(ctx, {"reverb": {"type": "room2"}})
    assert result["data"]["sysex_hex"] == ["F0 41 10 00 00 64 12 18 00 06 00 02 60 F7"]
    assert backend.sent_hex()[0] == "F0 41 10 00 00 64 12 18 00 06 00 02 60 F7"
    assert result["verification_status"] == "mocked"
    assert result["data"]["readback"]["status"] == "matched"


def test_nested_and_dotted_settings_encode_the_same(ctx):
    nested = {"master_eq": {"switch": True, "high_gain": -6, "high_freq": 4000},
              "parts": {"3": {"surround_lr": -20, "reverb_send": 40}}}
    dotted = {"master_eq.switch": "on", "master_eq.high_gain": "-6",
              "master_eq.high_freq": "4000", "part.3.surround_lr": "-20",
              "part.3.reverb_send": "40"}
    a = fx.apply(ctx, nested, dry_run=True)["data"]
    b = fx.apply(ctx, dotted, dry_run=True)["data"]
    assert a["sysex_hex"] == b["sysex_hex"] and len(a["sysex_hex"]) == 5
    assert a["settings"]["master_eq.high_gain"] == -6
    # part 3 block is 18 00 22 00; surround L-R is offset 44, -20 -> 44 (0x2C)
    assert "F0 41 10 00 00 64 12 18 00 22 44 2C" in " ".join(a["sysex_hex"])


def test_show_reflects_what_was_set(ctx):
    fx.apply(ctx, {"surround.switch": "on", "surround.room_size": "small",
                   "surround.ambience_level": 70, "part.1.ambience_send": 55})
    data = fx.show(ctx, [1])["data"]
    assert data["surround"]["switch"] == "on" and data["surround"]["room_size"] == "small"
    assert data["surround"]["ambience_level"] == 70
    assert data["parts"][0]["ambience_send"] == 55


@pytest.mark.parametrize(
    "settings",
    [{"reverb.type": "cathedral"}, {"reverb.level": 128}, {"master_eq.low_gain": 16},
     {"part.17.reverb_send": 1}, {"part.1.nonsense": 1}, {"raw.sysex": "F0"},
     {"surround.ambience_time": 101}, {"reverb.level": "loud"}, {}],
)
def test_invalid_settings_send_nothing(ctx, backend, settings):
    with pytest.raises(Integra7Error) as info:
        fx.apply(ctx, settings)
    assert info.value.code in ("INVALID_ARGUMENT", "INVALID_PART") and backend.sent == []


def test_real_backend_verified_only_when_readback_matches(ctx, backend):
    backend.is_mock = False
    assert fx.apply(ctx, {"reverb.level": 80})["verification_status"] == "verified"
    backend.device.ignore_writes = True
    with pytest.raises(Integra7Error) as info:
        fx.apply(ctx, {"reverb.level": 20})
    assert info.value.code == "MIDI_NOT_VERIFIED"
    assert info.value.details["readback"]["mismatches"]["reverb.level"] == {
        "requested": 20, "device": 80,
    }
    backend.device.respond = False
    assert fx.apply(ctx, {"reverb.level": 30})["verification_status"] == "sent_unverified"


def test_score_fx_block_is_applied_before_playback(ctx, backend):
    score = {"fx": {"reverb": {"type": "room1", "level": 60}},
             "parts": [{"part": 1, "notes": [[0, 60, 1, 90]]}]}
    result = play.play_score(ctx, score)
    assert result["data"]["fx"]["settings"] == {"reverb.type": "room1", "reverb.level": 60}
    hexes = backend.sent_hex()
    assert hexes[0].startswith("F0 41") and hexes.index("90 3C 5A") > 1
    with pytest.raises(Integra7Error):
        play.play_score(ctx, {**score, "fx": {"reverb": {"type": "nope"}}}, dry_run=True)


def test_address_helpers():
    assert sysex.address_add((0x18, 0x00, 0x06, 0x00), 0x01) == (0x18, 0x00, 0x06, 0x01)
    assert sysex.temporary_tone_address(1) == (0x19, 0x00, 0x00, 0x00)
    assert sysex.temporary_tone_address(2) == (0x19, 0x20, 0x00, 0x00)
    assert sysex.temporary_tone_address(5) == (0x1A, 0x00, 0x00, 0x00)
    assert sysex.temporary_tone_address(16) == (0x1C, 0x60, 0x00, 0x00)


def test_cli_fx_commands(full_db, capsys):
    base = ["--db", str(full_db), "--backend", "mock", "--json"]
    assert cli.main(["fx", "set", "reverb.type=hall1", "part.2.reverb_send=50", *base]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["readback"]["status"] == "matched"
    assert cli.main(["fx", "list", *base]) == 0
    assert "surround.room_type" in json.loads(capsys.readouterr().out)["data"]["global"]
    assert cli.main(["fx", "show", "--part", "2", *base]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["parts"]) == 1
    assert cli.main(["fx", "set", "reverb.type", *base]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "INVALID_ARGUMENT"
