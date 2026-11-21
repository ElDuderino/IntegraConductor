#!/usr/bin/env python3
"""Generates velvet-hour.json: a slow-swinging speakeasy tune in D minor.

    python3 examples/compose_velvet_hour.py
    integra7 play examples/velvet-hour.json

An original tune in the manner of a late-1920s/1930s small band, played with the
space and cool of the players who came later. Muted trumpet and tenor sax trade
two-bar phrases over a descending minor line, then join in sixths; the upright
piano takes the bridge in F while the horns hold a slow chromatic pad; the last
eight bars lift onto a walking bass and a brush ride before slowing into a held
D minor sixth and a little applause.

Form: 2-bar piano intro, A A' B A'' (8 bars each, the last one ending on the held
chord), 104 bpm. Rhythm guitar four to the bar, string bass in two, brushes.

The drum notes are the Jazz Brushes kit's key map, read from the unit:
36 kick, 37 brush slide, 38 brush tap, 40 soft tap, 43/47/50 brush toms,
44 hi-hat pedal, 51 brush ride, 55 brush splash, 88 applause.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

rng = random.Random(1933)
BAR = 4
TEMPO = 104
SWING = 0.65
T = 1 / 3
NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def n(name: str) -> int:
    return (int(name[-1]) + 1) * 12 + NAMES.index(name[:-1])


def up(name: str, semitones: int = 12) -> str:
    value = n(name) + semitones
    return NAMES[value % 12] + str(value // 12 - 1)


def at(bar: int, beat: float) -> float:
    return round(bar * BAR + beat, 3)


def unswung(beat: float) -> float:
    """The written beat that sounds at this even position once the player swings it."""
    whole, frac = divmod(beat, 1)
    if frac < SWING:
        return whole + frac * (0.5 / SWING)
    return whole + 0.5 + (frac - SWING) * (0.5 / (1 - SWING))


# chord -> (rootless piano voicing, three-note guitar voicing). None holds a note a
# semitone (in any octave) from what the horns or the piano melody play over it.
CHORDS = {
    "Dm":    (["F3", "A3", "D4"], ["A2", "F3", "D4"]),
    "DmM7":  (["F3", "A3", "Db4"], ["A2", "F3", "Db4"]),
    "Dm7":   (["F3", "A3", "C4"], ["A2", "F3", "C4"]),
    "Bm7b5": (["F3", "A3", "B3", "D4"], ["A2", "F3", "B3"]),
    "Dm6":   (["F3", "A3", "B3", "D4"], ["A2", "F3", "B3"]),
    "Bb7":   (["Ab3", "D4", "F4"], ["Bb2", "Ab3", "D4"]),
    "A7":    (["G3", "Db4", "E4"], ["E3", "G3", "Db4"]),
    "Gm6":   (["Bb3", "D4", "E4"], ["D3", "Bb3", "E4"]),
    "Em7b5": (["G3", "Bb3", "D4"], ["Bb2", "G3", "D4"]),
    "Gm7":   (["F3", "Bb3", "D4"], ["D3", "F3", "Bb3"]),
    "C7":    (["E3", "Bb3", "D4"], ["C3", "E3", "Bb3"]),
    "F6":    (["A3", "C4", "D4"], ["C3", "A3", "D4"]),
    "D7b9":  (["F#3", "C4", "Eb4"], ["D3", "F#3", "C4"]),
    "Bbm6":  (["G3", "Bb3", "Db4", "F4"], ["Bb2", "G3", "Db4"]),
}
INTRO = [["Dm6", "A7"], ["Dm6", "A7"]]
A = [["Dm", "DmM7"], ["Dm7", "Bm7b5"], ["Bb7", "A7"], ["Dm6", "A7"],
     ["Gm6"], ["Dm6"], ["Em7b5", "A7"], ["Dm6"]]
A2 = A[:7] + [["Dm6", "D7b9"]]
B = [["Gm7"], ["C7"], ["F6"], ["F6", "D7b9"], ["Gm7"], ["Bbm6"], ["F6"], ["Em7b5", "A7"]]
FORM = INTRO + A + A2 + B + A[:7]
S_A, S_A2, S_B, S_A3 = 2, 10, 18, 26  # first bar of each section
LAST = len(FORM)                      # bar of the held final chord
END = at(LAST, 0)

# String bass: in two, then walking under the last eight.
BASS = [
    None, "D2 A1",
    "D2 Db2", "C2 B1", "Bb1 A1", "D2 A1", "G2 D2", "D2 A1", "E2 A1", "D2 A1",
    "D2 Db2", "C2 B1", "Bb1 A1", "D2 A1", "G2 D2", "D2 A1", "E2 A1", "D2 F#2",
    "G2 D2", "C2 G2", "F2 C2", "F2 D2", "G2 D2", "Bb1 F2", "F2 C2", "E2 A1",
    "D2 A2 Db2 A2", "C2 A2 B1 F2", "Bb1 D2 A1 Db2", "D2 F2 A2 Ab2",
    "G2 Bb2 D3 E3", "D3 C3 A2 F2", "E2 G2 A2 Db2",
]

# Horn lines: section-relative bar -> (beat, pitch, length, velocity[, marks]).
TOGETHER_TPT = [(0, "G4", 1, 76, "breath"), (1, "Bb4", .5, 78), (1.5, "D5", .5, 84),
                (2, "Db5", 1, 86), (3, "Bb4", .5, 76), (3.5, "G4", .5, 72)]
TOGETHER_SAX = [(0, "E4", 1, 72, "breath"), (1, "G4", .5, 74), (1.5, "Bb4", .5, 78),
                (2, "G4", 1, 78), (3, "E4", .5, 70), (3.5, "Db4", .5, 68)]
TRUMPET = {
    S_A: {  # the trumpet calls ...
        0: [(1, "D4", .5, 70, "breath"), (1.5, "F4", .5, 74), (2, "A4", 2, 82)],
        1: [(0, "C5", 1.5, 84), (1.5, "A4", .5, 72), (2, "B4", 1.5, 78)],
        3: [(3, "A4", .5, 72, "breath"), (3.5, "Bb4", .5, 76)],
        4: [(0, "D5", 1.5, 88), (1.5, "Bb4", .5, 74), (2, "G4", 1, 76), (3, "E4", .5, 68),
            (3.5, "G4", .5, 72)],
        5: [(0, "F4", 2.5, 76)],
        6: TOGETHER_TPT,
        7: [(0, "A4", 3, 78)],
    },
    S_A2: {  # ... then answers, higher
        2: [(.5, "D5", .5, 78, "breath"), (1, "F5", 1, 90), (2, "E5", .5, 84), (2.5, "Db5", .5, 80),
            (3, "Bb4", 1, 78)],
        3: [(0, "A4", 2, 78)],
        6: TOGETHER_TPT,
        7: [(0, "A4", 2, 78)],
    },
    S_B: {  # a slow chromatic pad under the piano
        4: [(0, "D4", 4, 56, "breath")], 5: [(0, "Db4", 4, 58)], 6: [(0, "C4", 4, 56)],
        7: [(0, "D4", 2, 58), (2, "Db4", 1, 60)],
    },
    S_A3: {  # both horns, the trumpet on top
        0: [(1, "A4", .5, 80, "breath"), (1.5, "D5", .5, 86), (2, "F5", 2, 96)],
        1: [(0, "D5", 1, 88), (1, "C5", .5, 82), (1.5, "A4", .5, 78), (2, "D5", 1.5, 88)],
        2: [(.5, "D5", .5, 84, "breath"), (1, "F5", 1, 96), (2, "E5", .5, 88), (2.5, "Db5", .5, 84),
            (3, "Bb4", 1, 82)],
        3: [(0, "A4", 2, 82), (3, "A4", .5, 78, "breath"), (3.5, "Bb4", .5, 82)],
        4: [(0, "D5", 1.5, 94), (1.5, "Bb4", .5, 80), (2, "G4", 1, 80), (3, "E4", .5, 72),
            (3.5, "G4", .5, 76)],
        5: [(0, "A4", 2.5, 82)],
        6: TOGETHER_TPT,
        7: [(0, "A4", 6.5, 76)],
    },
}
SAX = {
    S_A: {  # the tenor answers ...
        2: [(.5, "F4", .5, 70, "breath"), (1, "Ab4", 1, 78), (2, "G4", .5, 74), (2.5, "E4", .5, 70),
            (3, "Db4", 1, 70)],
        3: [(0, "D4", 2, 72)],
        6: TOGETHER_SAX,
        7: [(0, "F4", 3, 72)],
    },
    S_A2: {  # ... then calls
        0: [(1, "D4", .5, 72, "breath"), (1.5, "F4", .5, 76), (2, "A4", 2, 84)],
        1: [(0, "C5", 1, 86), (1, "D5", .5, 88), (1.5, "C5", .5, 80), (2, "B4", 1.5, 80)],
        3: [(3, "A4", .5, 74, "breath"), (3.5, "Bb4", .5, 78)],
        4: [(0, "D5", 1.5, 90), (1.5, "Bb4", .5, 76), (2, "G4", 1, 78), (3, "E4", .5, 70),
            (3.5, "G4", .5, 74)],
        5: [(0, "F4", 2.5, 76)],
        6: TOGETHER_SAX,
        7: [(0, "F4", 2, 72)],
    },
    S_B: {
        4: [(0, "Bb3", 8, 54, "breath")], 6: [(0, "A3", 4, 54)], 7: [(0, "G3", 3, 56)],
    },
    S_A3: {  # under the trumpet (a tenth or a thirteenth, once dropped an octave)
        0: [(1, "D4", .5, 74, "breath"), (1.5, "F4", .5, 78), (2, "A4", 2, 86)],
        1: [(0, "A4", 1, 80), (1, "G4", .5, 76), (1.5, "F4", .5, 74), (2, "B4", 1.5, 82)],
        2: [(.5, "F4", .5, 76, "breath"), (1, "Ab4", 1, 86), (2, "G4", .5, 80), (2.5, "E4", .5, 76),
            (3, "Db4", 1, 76)],
        3: [(0, "F4", 2, 76), (3, "Db4", .5, 70, "breath"), (3.5, "E4", .5, 74)],
        4: [(0, "Bb4", 1.5, 84), (1.5, "G4", .5, 74), (2, "E4", 1, 74), (3, "Bb3", .5, 68),
            (3.5, "E4", .5, 72)],
        5: [(0, "F4", 2.5, 76)],
        6: TOGETHER_SAX,
        7: [(0, "F4", 6.5, 70)],
    },
}
# Piano right hand: absolute bar -> (beat, pitch, length, velocity).
PIANO_LEAD = {
    0: [(0, "A5", 1, 76), (1, "F5", .5, 68), (1.5, "D5", .5, 70), (2, "Db5", 1.5, 76), (3.5, "E5", .5, 70)],
    1: [(0, "F5", 1, 76), (1, "D5", .5, 68), (1.5, "A4", .5, 68), (2, "Bb4", 1, 74), (3, "G4", .5, 66),
        (3.5, "E4", .5, 64)],
    S_B: [(0, "Bb4", 1, 82), (1, "D5", .5, 80), (1.5, "F5", 1.5, 90), (3, "D5", .5, 78), (3.5, "F5", .5, 82)],
    S_B + 1: [(0, "E5", 1.5, 88), (1.5, "D5", .5, 78), (2, "Bb4", 1, 80), (3, "G4", 1, 76)],
    S_B + 2: [(0, "A4", 1, 80), (1, "C5", .5, 80), (1.5, "D5", .5, 82), (2, "F5", 2, 90)],
    S_B + 3: [(.5, "D5", .5, 78), (1, "C5", .5, 78), (1.5, "A4", .5, 76), (2, "F#4", 1, 82), (3, "A4", .5, 78),
              (3.5, "C5", .5, 82)],
    S_B + 4: [(0, "Bb4", 1, 82), (1, "D5", .5, 82), (1.5, "G5", 1.5, 94), (3, "F5", .5, 82), (3.5, "D5", .5, 80)],
    S_B + 5: [(0, "Db5", 1.5, 88), (1.5, "Bb4", .5, 78), (2, "G4", 1, 78), (3, "F4", .5, 74), (3.5, "G4", .5, 76)],
    S_B + 6: [(0, "A4", 2, 80), (2, "C5", .5, 78), (2.5, "D5", .5, 80), (3, "F5", 1, 88)],
    S_B + 7: [(0, "E5", 1, 86), (1, "D5", .5, 80), (1.5, "Bb4", .5, 78), (2, "A4", 1, 80)],
}

trumpet, sax, piano_lead, piano, pedal, bass, guitar, drums = [], [], [], [], [], [], [], []

# ------------------------------------------------------------------- horns
for horn, lines in ((trumpet, TRUMPET), (sax, SAX)):
    for start, section in lines.items():
        for rel, phrase in section.items():
            for beat, pitch, length, vel, *marks in phrase:
                horn.append([at(start + rel, beat), pitch, length, vel, marks[0] if marks else ""])

# The tenor is played the way the listener's keyboard plays it, which they found
# far better than the shaped, slurred version: down in its low register (the
# lines above are written an octave high), every note attacked on its own with a
# small gap, struck firmly, and with no controller messages at all.
for note in sax:
    in_bridge = at(S_B, 0) <= note[0] < at(S_A3, 0)
    note[:] = [note[0], note[1] if in_bridge else up(note[1], -12), round(note[2] * 0.85, 3),
               min(note[3] + 24, 110)]

# -------------------------------------------------------- piano right hand
for bar, phrase in PIANO_LEAD.items():
    for beat, pitch, length, vel in phrase:
        piano_lead.append([at(bar, beat), pitch, length, vel])
        if length >= 1.5:  # long notes doubled at the octave
            piano_lead.append([at(bar, beat), up(pitch), length, vel - 10])


def chord_at(bar: int, beat: float) -> str:
    names = FORM[bar]
    return names[int(beat // (BAR / len(names)))]


# ------------------------------------------------- piano, bass and guitar
for bar, names in enumerate(FORM):
    span = BAR / len(names)
    solo = bar < 2 or S_B <= bar < S_A3  # the piano has the tune: no pedal, lighter chords
    for index, name in enumerate(names):
        t = at(bar, index * span)
        voicing = CHORDS[name][0]
        soft = -6 if solo else 0
        piano.append([t, voicing, 1.8 if span == 2 else 2.3, 54 + soft + rng.randint(-4, 4)])
        if span == BAR:
            piano.append([at(bar, 2.5), voicing, 1.3, 46 + soft + rng.randint(-4, 4)])
        if not solo:
            pedal += [[round(max(t - 0.03, 0), 3), 64, 0], [round(t + 0.05, 3), 64, 127]]
        elif index == 0 and bar in (S_B,):
            pedal.append([round(t - 0.03, 3), 64, 0])
    if BASS[bar]:
        pitches = BASS[bar].split()
        step = BAR / len(pitches)
        for i, pitch in enumerate(pitches):
            lean = 5 if i == 0 else 0
            bass.append([at(bar, i * step), pitch, step * 0.92, 84 + lean + rng.randint(-3, 3)])
    if bar >= S_A:
        for beat in range(BAR):  # four to the bar, short and quiet, leaning on two and four
            for string, pitch in enumerate(CHORDS[chord_at(bar, beat)][1]):
                guitar.append([round(at(bar, beat) + string * 0.012, 3), pitch, 0.36,
                               40 + (8 if beat % 2 else 0) + rng.randint(-3, 3)])

# ----------------------------------------------------------------- brushes
KICK, SLIDE, TAP, SOFT_TAP, HH_PEDAL = 36, 37, 38, 40, 44
RIDE, SPLASH, APPLAUSE, TOM_HI, TOM_MID, TOM_LOW = 51, 55, 88, 50, 47, 43
FILL_BAR = S_A3 - 1
for bar in range(1, LAST):
    lifted = bar >= S_A3
    for beat in range(BAR):
        if bar == FILL_BAR and beat >= 2:
            continue
        backbeat = beat % 2 == 1
        drums.append([at(bar, beat), SLIDE, 0.9,
                      (40 if lifted else 46) + (8 if backbeat else 0) + rng.randint(-4, 4)])
        if lifted:  # brush ride: ding, ding-a, ding, ding-a
            drums.append([at(bar, beat), RIDE, 0.9, 62 + (8 if backbeat else 0) + rng.randint(-4, 4)])
            if backbeat:
                drums.append([at(bar, beat + .5), RIDE, 0.4, 50 + rng.randint(-4, 4)])
        if backbeat:
            drums.append([at(bar, beat), TAP, 0.2, (60 if lifted else 54) + rng.randint(-5, 5)])
            drums.append([at(bar, beat), HH_PEDAL, 0.2, 62 if lifted else 50])
            if not lifted:
                drums.append([at(bar, beat + .5), SOFT_TAP, 0.2, 34 + rng.randint(-4, 4)])
        elif bar >= S_A:
            drums.append([at(bar, beat), KICK, 0.2, (58 if lifted else 46) + rng.randint(-3, 3)])
    if bar in (S_A2 - 1, S_B - 1):  # a small figure to turn the corner
        for beat, vel in ((2.5, 44), (3, 50), (3.5, 58)):
            drums.append([at(bar, beat), TAP, 0.2, vel])
for bar, key, vel in ((S_A, RIDE, 46), (S_A2, RIDE, 48), (S_B, SPLASH, 48), (S_A3, SPLASH, 62)):
    drums.append([at(bar, 0), key, 1.5, vel])
# The fill into the last eight: brush taps in triplets, then down the toms.
fill = [(2, TAP, 56), (2 + T, TAP, 62), (2 + 2 * T, TAP, 68),
        (3, TOM_HI, 72), (3 + T, TOM_MID, 78), (3 + 2 * T, TOM_LOW, 84)]
for beat, key, vel in fill:
    drums.append([round(unswung(at(FILL_BAR, 0) + beat), 3), key, 0.2, vel])
drums.append([at(FILL_BAR, 3), KICK, 0.2, 60])

# ------------------------------------------------------------- final chord
piano.append([END, ["D2", "A2", "F3", "B3", "D4"], 7, 62])
piano += [[END + 2, "A5", 1, 46], [END + 3, "D6", 4, 42]]
pedal += [[round(END - 0.03, 3), 64, 0], [round(END + 0.05, 3), 64, 127], [END + 7.5, 64, 0]]
bass.append([END, "D2", 7, 86])
for string, pitch in enumerate(CHORDS["Dm6"][1]):
    guitar.append([round(END + string * 0.03, 3), pitch, 5, 46])
drums += [[END, SPLASH, 4, 56], [END, KICK, 0.2, 60], [END, SLIDE, 3, 50]]
drums.append([END + 7.5, APPLAUSE, 9, 62])  # the room, after the last chord dies


# ------------------------------------------------------------ clash check
def rubs() -> list[str]:
    """Places where a melodic voice sounds a semitone (any octave) from the harmony."""
    found = []
    voices = [("trumpet", trumpet), ("sax", sax), ("piano melody", piano_lead)]
    harmony = [("piano", piano), ("guitar", guitar)]
    pairs = [(a, b) for a in voices for b in harmony] + [(voices[0], voices[1])]
    for (name_a, part_a), (name_b, part_b) in pairs:
        for a in part_a:
            for b in part_b:
                if a[0] < b[0] + b[2] - 0.05 and b[0] < a[0] + a[2] - 0.05:
                    for tone in (b[1] if isinstance(b[1], list) else [b[1]]):
                        if abs(n(a[1]) - n(tone)) % 12 in (1, 11):
                            found.append(f"bar {int(a[0] // BAR)}: {name_a} {a[1]} against "
                                         f"{name_b} {tone}")
    return sorted(set(found))


problems = rubs()
piano += piano_lead


def slow_down(parts: list[list]) -> None:
    """Ease into the last chord: stretch the half bar before it."""
    start = at(LAST - 1, 2)

    def warp(beat: float) -> float:
        if beat <= start:
            return beat
        if beat < END:
            x = beat - start
            return start + x * (1 + 0.16 * x)
        return beat + (END - start) * 0.32

    for events in parts:
        for event in events:
            original = event[0]
            event[0] = round(warp(original), 3)
            if len(event) >= 4:  # a note: keep its end in step with the stretch
                event[2] = round(max(warp(original + event[2]) - event[0], 0.1), 3)


slow_down([trumpet, sax, piano, pedal, bass, guitar, drums])

score = {
    "title": "Velvet Hour",
    "description": "A slow-swinging speakeasy tune in D minor: muted trumpet and tenor sax "
                   "trading phrases, upright piano, string bass, rhythm guitar and brushes.",
    "tempo_bpm": TEMPO,
    "swing": SWING,
    "fx": {
        # Motional Surround off: the listener heard a quartet far more clearly without it.
        "surround": {"switch": "off"},
        "reverb": {"switch": "on", "type": "hall2", "level": 127},
        # Roll the top off and warm the bottom, like an old recording.
        "master_eq": {"switch": "on", "low_freq": 200, "low_gain": 2, "mid_freq": 2500,
                      "mid_gain": -2, "mid_q": "0.5", "high_freq": 4000, "high_gain": -6},
        "parts": {
            # Wind players sound one note at a time: mono + legato lets overlapping notes slur.
            "1": {"reverb_send": 60, "mono_poly": "mono", "legato": "on", "bend_range": "2"},
            "2": {"reverb_send": 30},
            "3": {"reverb_send": 10},
            "4": {"reverb_send": 25},
            "5": {"reverb_send": 70, "mono_poly": "mono", "legato": "on"},
            "10": {"reverb_send": 30},
        },
    },
    "parts": [
        {"part": 5, "patch_id": "sn-a-preset-0221", "level": 106, "pan": 54, "humanize_ms": 18,
         "expression": {"style": "warm_jazz_tenor", "seed": 1933, "intensity": 0.8, "subtone": 0,
                        "scoops": 0, "falls": 0},
         "notes": sorted(trumpet, key=lambda x: x[0])},
        {"part": 1, "patch_id": "sn-a-preset-0236", "level": 100, "pan": 76, "humanize_ms": 14,
         "notes": sorted(sax, key=lambda x: x[0])},
        {"part": 2, "patch_id": "sn-a-preset-0006", "level": 98, "pan": 40, "humanize_ms": 8,
         "controls": sorted(pedal, key=lambda c: c[0]), "notes": sorted(piano, key=lambda x: x[0])},
        {"part": 3, "patch_id": "sn-a-preset-0135", "level": 102, "pan": 68, "humanize_ms": -6,
         "notes": sorted(bass, key=lambda x: x[0])},
        {"part": 4, "patch_id": "sn-a-preset-0099", "level": 66, "pan": 88, "humanize_ms": 4,
         "notes": sorted(guitar, key=lambda x: x[0])},
        {"part": 10, "patch_id": "sn-d-preset-0009", "level": 108, "pan": 60,
         "notes": sorted(drums, key=lambda x: x[0])},
    ],
}

out = Path(__file__).with_name("velvet-hour.json")
with open(out, "w", encoding="utf-8") as fh:
    fh.write("{\n")
    for key in ("title", "description", "tempo_bpm", "swing", "fx"):
        fh.write(f"  {json.dumps(key)}: {json.dumps(score[key])},\n")
    fh.write('  "parts": [\n')
    for index, part in enumerate(score["parts"]):
        head = {k: v for k, v in part.items() if k not in ("notes", "controls")}
        fh.write("    " + json.dumps(head)[:-1])
        if "controls" in part:
            fh.write(', "controls": ' + json.dumps(part["controls"]))
        fh.write(', "notes": [\n')
        fh.write(",\n".join("      " + json.dumps(note) for note in part["notes"]))
        fh.write("\n    ]}" + ("," if index < len(score["parts"]) - 1 else "") + "\n")
    fh.write("  ]\n}\n")
print(f"wrote {out}; about {(END + 8) * 60 / TEMPO:.0f} s of music at {TEMPO} bpm, then applause")
for line in problems:
    print("semitone rub:", line)
print(f"{len(problems)} semitone rubs between the melody and the harmony")
