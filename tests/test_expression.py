from __future__ import annotations

import json

import pytest

from integra7_conductor.errors import Integra7Error
from integra7_conductor.services import expression, play

PHRASE = [
    [0, "G4", 1.5, 74, "breath"], [1.5, "F4", 0.5, 66], [2, "Eb4", 1, 68], [3, "G4", 1, 72],
    [4, "Ab4", 3, 78],
    [8, "C5", 1, 84, "breath"], [9, "C5", 1, 80], [10, "Bb4", 4, 76],
]
SETTINGS = {"style": "breathy_ballad_tenor", "seed": 7}
TEMPO = 76


def controls_for(controls, controller):
    return [c for c in controls if c[1] == controller]


def test_same_seed_same_performance_different_seed_differs():
    a = expression.render([list(n) for n in PHRASE], SETTINGS, TEMPO)
    b = expression.render([list(n) for n in PHRASE], SETTINGS, TEMPO)
    c = expression.render([list(n) for n in PHRASE], {**SETTINGS, "seed": 8}, TEMPO)
    assert a == b and a != c


def test_pitches_are_never_changed():
    notes, _ = expression.render([list(n) for n in PHRASE], SETTINGS, TEMPO)
    assert [n[1] for n in notes] == [n[1] for n in PHRASE]


def test_slurred_notes_overlap_and_tongued_notes_have_a_gap():
    notes, _ = expression.render([list(n) for n in PHRASE], SETTINGS, TEMPO)
    ends = [n[0] + n[2] for n in notes]
    assert ends[0] > notes[1][0] and ends[1] > notes[2][0]  # slurred: overlap
    assert ends[5] < notes[6][0]  # repeated pitch (C5, C5) must be re-tongued
    assert ends[4] < notes[5][0] - 0.25  # a breath before the second phrase


def test_dynamics_rise_to_the_peak_then_relax():
    _, controls = expression.render([list(n) for n in PHRASE], SETTINGS, TEMPO)
    first_phrase = [c[2] for c in controls_for(controls, 1) if 0.05 < c[0] < 7.5]
    peak = first_phrase.index(max(first_phrase))
    assert 0 < peak < len(first_phrase) - 1
    assert first_phrase[-1] < max(first_phrase) - 10 and first_phrase[0] < max(first_phrase)
    steps = [abs(a - b) for a, b in zip(first_phrase, first_phrase[1:], strict=False)]
    assert max(steps) <= 8  # a smooth curve, not jumps


def test_vibrato_is_delayed_only_on_long_notes_and_released():
    notes, controls = expression.render(
        [list(n) for n in PHRASE], {**SETTINGS, "style": "aggressive_blues_tenor"}, TEMPO
    )
    touch = [c for c in controls_for(controls, "aftertouch") if c[2] > 0]
    assert touch
    beat_ms = 60000 / TEMPO
    for at, _, _ in touch:
        owner = [n for n in notes if n[0] <= at <= n[0] + n[2]]
        assert owner and owner[-1][2] * beat_ms >= 650  # never on short notes
        assert (at - owner[-1][0]) * beat_ms >= 150  # never at the attack
    assert controls_for(controls, "aftertouch")[-1][2] == 0
    none = expression.render([list(n) for n in PHRASE], {**SETTINGS, "vibrato": 0}, TEMPO)[1]
    assert not [c for c in controls_for(none, "aftertouch") if c[2] > 0]


def test_subtone_only_on_quiet_phrases_and_always_switched_off():
    quiet = [[0, "D4", 2, 60, "breath"], [2, "C4", 2, 58]]
    loud = [[8, "C5", 2, 100, "breath"], [10, "Eb5", 2, 104]]
    _, controls = expression.render(quiet + loud, SETTINGS, TEMPO)
    sub = controls_for(controls, 82)
    on = [c[0] for c in sub if c[2] == 127]
    assert len(on) == 1 and on[0] < 0.1
    assert sub[-1][2] == 0
    off = expression.render(quiet, {**SETTINGS, "subtone": False}, TEMPO)[1]
    assert not [c for c in controls_for(off, 82) if c[2]]


def test_marked_articulations_use_rolands_controllers_and_reset():
    notes = [[0, "G4", 0.5, 80, "stacc"], [1, "G4", 1, 90, "scoop"], [3, "Bb4", 1, 96, "fall"]]
    out, controls = expression.render(notes, {"style": "pop_sax", "seed": 1}, 120)
    assert [c[2] for c in controls_for(controls, 80)][:3] == [0, 127, 0]
    assert 127 in [c[2] for c in controls_for(controls, 81)]
    bends = [c[2] for c in controls_for(controls, "bend")]
    assert min(bends) < -500 and bends[-1] == 0
    assert out[0][2] < 0.3  # staccato is short
    for controller in (80, 81, 82, "aftertouch", "bend"):
        assert controls_for(controls, controller)[-1][2] == 0  # nothing left switched on


def test_growl_only_in_styles_that_ask_for_it():
    notes = [[0, "C5", 2, 118, "breath"]]
    blues = expression.render(notes, {"style": "aggressive_blues_tenor"}, 120)[1]
    ballad = expression.render(notes, SETTINGS, 120)[1]
    assert max(c[2] for c in controls_for(blues, 18)) >= 90
    assert max(c[2] for c in controls_for(ballad, 18)) <= 10


@pytest.mark.parametrize(
    "settings", [{"style": "kenny"}, {"vibrato": 5}, {"wat": 1}, {"bend_range_semitones": 0}]
)
def test_bad_settings_rejected(settings):
    with pytest.raises(Integra7Error):
        expression.render([list(n) for n in PHRASE], settings, TEMPO)
    with pytest.raises(Integra7Error):
        expression.render([[0, ["C4", "E4"], 1, 80]], SETTINGS, TEMPO)
    with pytest.raises(Integra7Error):
        expression.render([[0, "C4", 1, 80, "yodel"]], SETTINGS, TEMPO)


def test_score_part_with_expression_plays_and_dumps_events(ctx, backend, tmp_path):
    dump = tmp_path / "events.json"
    score = {"tempo_bpm": TEMPO, "parts": [{"part": 1, "expression": SETTINGS,
                                             "notes": [list(n) for n in PHRASE]}]}
    result = play.play_score(ctx, score, dump_events=str(dump))
    assert result["data"]["note_count"] == len(PHRASE)
    sent = backend.sent_hex()
    assert any(h.startswith("D0") for h in sent)  # channel aftertouch
    assert any(h.startswith("B0 01") for h in sent) and any(h.startswith("B0 52") for h in sent)
    assert backend.device.notes_on == set()
    events = json.loads(dump.read_text())
    assert [e["hex"] for e in events] == sent  # the dump is exactly what was sent, in order
