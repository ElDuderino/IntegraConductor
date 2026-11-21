from __future__ import annotations

import json

import pytest

from conftest import REPO
from integra7_conductor import cli
from integra7_conductor.errors import Integra7Error
from integra7_conductor.midi import windows_adapter
from integra7_conductor.services import play

SCORE = {
    "tempo_bpm": 120,
    "swing": 0.66,
    "parts": [
        {"part": 1, "patch_id": "sn-a-preset-0001", "level": 100,
         "notes": [[0, "C4", 1, 90], [0.5, ["E4", 67], 0.5, 80]]},
        {"part": 10, "notes": [[1, 51, 0.25, 70]]},
    ],
}


def test_pitch_names_and_swing():
    assert [play.parse_pitch(p) for p in ("C4", "Bb3", "F#2", "a0", 60)] == [60, 58, 42, 21, 60]
    assert play.swing_beat(0.5, 0.66) == pytest.approx(0.66)
    assert play.swing_beat(2.0, 0.66) == pytest.approx(2.0)
    assert play.swing_beat(3.5, 0.5) == pytest.approx(3.5)
    with pytest.raises(Integra7Error):
        play.parse_pitch("H9")


def test_play_selects_patches_then_plays_every_note_and_releases_it(ctx, backend):
    result = play.play_score(ctx, SCORE)
    assert result["verification_status"] == "mocked"
    assert result["data"]["note_count"] == 4
    sent = backend.sent_hex()
    assert sent[:4] == ["B0 00 59", "B0 20 40", "C0 00", "B0 07 64"]  # setup first
    assert sent[4] == "90 3C 5A"  # C4 on beat 0
    assert sum(h.startswith("9") for h in sent) == sum(h.startswith("8") for h in sent) == 4
    assert "99 33 46" in sent  # part 10 on channel 10
    assert backend.device.notes_on == set()
    steps = backend.requests[-1]["steps"]
    assert [s["type"] for s in steps] == ["send", "sleep", "sequence"]
    times = [e["t_ms"] for e in steps[2]["events"]]
    assert times == sorted(times) and 330.0 in times  # swung off-beat: 0.66 * 500 ms


def test_play_dry_run_and_validation(ctx, backend):
    dry = play.play_score(ctx, SCORE, dry_run=True, tempo_bpm=60)
    assert dry["verification_status"] == "not_sent" and dry["data"]["tempo_bpm"] == 60
    for broken in (
        {"parts": []},
        {"parts": [{"part": 1, "notes": [[0, 60, 1]]}]},
        {"parts": [{"part": 1, "notes": [[0, 200, 1, 90]]}]},
        {"parts": [{"part": 1, "notes": [[0, 60, 1, 90]]}, {"part": 1, "notes": [[0, 60, 1, 90]]}]},
        {"tempo_bpm": 5, "parts": [{"part": 1, "notes": [[0, 60, 1, 90]]}]},
        {"parts": [{"part": 1, "patch_id": "studio-set-01", "notes": [[0, 60, 1, 90]]}]},
        {"parts": [{"part": 1, "notes": [[0, 60, 1, 90], [900, 60, 1, 90]]}]},  # too long
    ):
        with pytest.raises(Integra7Error):
            play.play_score(ctx, broken)
    assert backend.sent == []


def test_interrupted_sequence_releases_sounding_notes(ctx, backend):
    backend.fail_after_messages = 5  # setup (4) + first note-on, then the port dies once
    with pytest.raises(Integra7Error) as info:
        play.play_score(ctx, SCORE)
    assert info.value.code == "MIDI_SEND_FAILED"
    assert backend.device.notes_on == set()


def test_bundled_example_score_plays_on_mock(full_db, capsys):
    score = str(REPO / "examples" / "blue-conductor.json")
    code = cli.main(["play", score, "--db", str(full_db), "--backend", "mock", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["verification_status"] == "mocked"
    assert {p["patch_name"] for p in result["data"]["parts"]} == {
        "Vibraphone", "Full Grand 1", "Ac Bass 1", "Jazz Kit",
    }
    assert all(p["patch_id"].startswith(("sn-a-preset", "sn-d-preset"))
               for p in result["data"]["parts"])  # no expansion needed


def test_sequence_step_validation():
    def run(events):
        return windows_adapter.run_request(
            {"op": "transact", "steps": [{"type": "sequence", "port": "x", "events": events}]},
            lambda: pytest.fail("must validate before opening ports"),
        )

    for events in ([], [{"t_ms": -1, "message": [0x90, 60, 90]}],
                   [{"t_ms": 10**9, "message": [0x90, 60, 90]}], [{"t_ms": 0, "message": [1]}]):
        assert run(events)["error"]["code"] == "INVALID_ARGUMENT"


def test_default_io_falls_back_only_on_windows(monkeypatch):
    def no_mido():
        raise windows_adapter.AdapterError("ADAPTER_DEPENDENCY_MISSING", "no mido")

    monkeypatch.setattr(windows_adapter, "MidoIO", no_mido)
    with pytest.raises(windows_adapter.AdapterError):  # Linux: no WinMM to fall back to
        windows_adapter.default_io()


def test_solo_parts(ctx, backend):
    result = play.play_score(ctx, SCORE, only_parts=[10])
    assert [p["part"] for p in result["data"]["parts"]] == [10]
    assert all(h[1] == "9" for h in backend.sent_hex())  # only channel 10 traffic
    with pytest.raises(Integra7Error):
        play.play_score(ctx, SCORE, only_parts=[5])


def test_controls_are_timed_between_note_off_and_note_on(ctx, backend):
    score = {"tempo_bpm": 120, "parts": [{"part": 1, "controls": [[0, 64, 127], [1, 64, 0]],
                                          "notes": [[0, 60, 1, 90], [1, 62, 1, 90]]}]}
    result = play.play_score(ctx, score)
    assert result["data"]["note_count"] == 2
    assert backend.sent_hex() == [
        "B0 40 7F", "90 3C 5A", "80 3C 00", "B0 40 00", "90 3E 5A", "80 3E 00",
    ]
    for bad in ([[0, 64]], [[0, 200, 1]], "x"):
        with pytest.raises(Integra7Error):
            play.play_score(ctx, {"parts": [{"part": 1, "controls": bad,
                                             "notes": [[0, 60, 1, 90]]}]})


def test_pitch_bend_and_humanize(ctx, backend):
    score = {"tempo_bpm": 120, "parts": [{"part": 1, "humanize_ms": 20,
             "controls": [[0, "bend", -2048], [1, "bend", 0]], "notes": [[0, 60, 1, 90]]}]}
    play.play_score(ctx, score)
    assert backend.sent_hex()[:2] == ["E0 00 30", "90 3C 5A"] and "E0 00 40" in backend.sent_hex()
    events = backend.requests[-1]["steps"][-1]["events"]
    assert events[0]["t_ms"] == 20.0  # shifted behind the beat


def test_live_messages_reach_a_running_playback(ctx, backend, monkeypatch):
    from integra7_conductor.services import parts as parts_service

    live = ctx.config.live_path()
    assert not ctx.live_inject([b"\xc0\x05"])  # nothing playing: caller sends normally

    def play_with_someone_typing(seconds):
        # While the sequence waits, another command selects a patch on part 1.
        if live.exists() and not backend.sent_hex().count("C0 6B"):
            monkeypatch.setattr(backend, "is_busy", lambda: True)
            result = parts_service.select_patch(ctx, 1, patch_id="sn-a-preset-0236")
            assert result["data"]["readback"]["reason"] == "playback in progress"
        backend._now += seconds

    backend._sleep = play_with_someone_typing
    score = {"tempo_bpm": 60, "parts": [{"part": 1, "notes": [[0, 60, 1, 90], [4, 62, 1, 90]]}]}
    result = play.play_score(ctx, score)
    assert result["data"]["live_messages_sent"] == 3
    sent = backend.sent_hex()
    assert sent.index("C0 6B") < sent.index("90 3E 5A")  # arrived before the second note
    assert not live.exists()


def test_stale_live_file_is_ignored(ctx, backend):
    ctx.config.live_path().parent.mkdir(parents=True, exist_ok=True)
    ctx.config.live_path().write_text("")
    assert ctx.live_inject([b"\xc0\x05"]) is False and not ctx.config.live_path().exists()


def test_loop_and_keep_patch(ctx, backend):
    result = play.play_score(ctx, SCORE, loops=3, keep_patch=[1])
    assert result["data"]["note_count"] == 12
    assert not any(h.startswith("C0") for h in backend.sent_hex())  # part 1 patch untouched
    with pytest.raises(Integra7Error):
        play.play_score(ctx, SCORE, loops=0)


def test_keep_fx_skips_the_scores_effect_block(ctx, backend):
    score = {"fx": {"reverb": {"type": "hall2"}}, "parts": [{"part": 1, "notes": [[0, 60, 1, 90]]}]}
    result = play.play_score(ctx, score, keep_fx=True)
    assert "fx" not in result["data"] and not any(h.startswith("F0") for h in backend.sent_hex())
