#!/usr/bin/env python3
"""Generates half-past-blue.json: a 30-second medium-swing tune in C minor.

    python3 examples/compose_half_past_blue.py
    integra7 play examples/half-past-blue.json

Vibraphone (Vibes Soft) lead over a piano trio (grand piano, walking string bass, sticks on
the Jazz Kit). Sixteen bars at 138 bpm: an eight-bar phrase, its answer an octave lower and climbing back
higher, with a few mallet rolls, a one-bar break for the vibes and a held C minor 6/9.

Drum notes are the ones the Jazz Kit was heard to answer to: 36 kick, 38 snare,
44 pedal hi-hat, 51 ride, 49 crash.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

rng = random.Random(1959)
BAR = 4
TEMPO = 138
PICKUP = 1  # one beat before bar 0
BARS = 16   # bar 15 is the break, bar 16 the held last chord


NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def n(name: str) -> int:
    return (int(name[-1]) + 1) * 12 + NAMES.index(name[:-1])


def at(bar: int, beat: float) -> float:
    return round(PICKUP + bar * BAR + beat, 3)


SWING = 0.66
ROLL_RATE = 5  # strokes per beat: about 11 a second at this tempo


def swung(beat: float) -> float:
    """Where the player puts a written beat (same map as services/play.py)."""
    whole, frac = divmod(beat, 1)
    if frac < 0.5:
        return whole + frac * (SWING / 0.5)
    return whole + SWING + (frac - 0.5) * ((1 - SWING) / 0.5)


def unswung(beat: float) -> float:
    """The written beat that will sound at this even position after swing."""
    whole, frac = divmod(beat, 1)
    if frac < SWING:
        return whole + frac * (0.5 / SWING)
    return whole + 0.5 + (frac - SWING) * (0.5 / (1 - SWING))


def roll(start: float, length: float, pitches: list, first: int, last: int) -> list[list]:
    """A mallet roll: evenly spaced strokes cycling through pitches, first to last velocity."""
    begin, finish = swung(start), swung(start + length)
    count = max(int(round((finish - begin) * ROLL_RATE)), 3)
    strokes = []
    for i in range(count):
        t = round(unswung(begin + (finish - begin) * i / count), 3)
        vel = first if i == 0 else round(first - 16 + (last - first + 16) * i / (count - 1))
        strokes.append([t, pitches[i % len(pitches)], 2.0, vel + rng.randint(-2, 2)])
    return strokes


T = 1 / 3  # a triplet eighth, written so that it comes out even under swing

# chord -> rootless piano voicing. Each avoids a note a semitone (or a minor ninth)
# from what the vibes play over it: no D under the melody's Eb on C minor or G7,
# no F under its F# on Ab7.
VOICINGS = {
    "Cm6":    ["Eb3", "A3", "C4"],
    "Dm7b5":  ["F3", "Ab3", "C4"],
    "G7":     ["F3", "Ab3", "B3"],
    "Gm7b5":  ["F3", "Bb3", "Db4"],
    "C7b9":   ["E3", "Bb3", "Db4"],
    "Fm7":    ["Ab3", "C4", "Eb4"],
    "Bb7":    ["Ab3", "C4", "D4"],
    "Ebmaj7": ["G3", "Bb3", "D4"],
    "Ab7":    ["F#3", "C4", "Eb4"],
}
# Voicings for the bars where the piano sits above the vibes.
HIGH = {"Cm6": ["G4", "A4", "C5"], "G7": ["F4", "B4", "D5"]}
# One or two chords per bar (two = half a bar each).
FORM = [
    ["Cm6"], ["Dm7b5", "G7"], ["Cm6"], ["Gm7b5", "C7b9"],
    ["Fm7"], ["Bb7"], ["Ebmaj7"], ["Dm7b5", "G7"],
    ["Cm6"], ["Dm7b5", "G7"], ["Cm6"], ["Gm7b5", "C7b9"],
    ["Fm7"], ["Dm7b5", "G7"], ["Cm6", "Ab7"],
]
# Walking bass, four to the bar, each bar ending a step from the next root.
WALK = [
    "C2 Eb2 G2 Eb2", "D2 F2 G2 B1", "C2 D2 Eb2 F#2", "G2 Bb2 C3 E3",
    "F3 Eb3 C3 B2", "Bb2 Ab2 F2 D2", "Eb2 G2 Bb2 Eb3", "D3 Ab2 G2 Db2",
    "C2 G2 A2 Eb2", "D2 F2 G2 B1", "C2 Eb2 F2 F#2", "G2 Bb2 C3 E2",
    "F2 Ab2 C3 Eb3", "D3 Ab2 G2 Db2", "C2 Eb2 Ab2 Ab1",
]
# Vibes: bar -> (beat, pitch, length in beats, velocity). Bar -1 is the pickup.
MELODY = {
    -1: [(3, "G4", .5, 78), (3.5, "C5", .5, 84)],
    0: [(0, "Eb5", 1.5, 96), (1.5, "D5", .5, 80), (2, "C5", 1, 86), (3, "G4", .5, 76), (3.5, "A4", .5, 80)],
    1: [(0, "Ab4", 1, 86), (1, "F4", .5, 74), (1.5, "Ab4", .5, 80), (2, "B4", 1, 88), (3, "D5", .5, 84),
        (3.5, "Eb5", 1.5, 94)],
    2: [(1.5, "C5", .5, 80), (2, "A4", 1, 84), (3, "G4", .5, 76), (3.5, "Bb4", .5, 82)],
    3: [(0, "Db5", 1.5, 92), (1.5, "Bb4", .5, 78), (2, "G4", .5, 78), (2.5, "Bb4", .5, 82),
        (3, "Db5", .5, 86), (3.5, "E5", .5, 92)],
    4: [(0, "F5", 1.5, 100), (1.5, "Eb5", .5, 84), (2, "C5", .5, 84), (2.5, "Ab4", .5, 78), (3, "C5", 1, 86)],
    5: [(0, "D5", 1, 90), (1.5, "Bb4", .5, 80), (2, "Ab4", .5, 82), (2.5, "F4", .5, 76), (3, "D4", .5, 74),
        (3.5, "F4", .5, 80)],
    6: [(0, "G4", 2, 88, "roll"), (2, "Bb4", .5, 80), (2.5, "D5", .5, 86), (3, "G5", 1, 98)],
    # the run down: the second phrase is played an octave lower
    7: [(0, "F5", .5, 90), (.5, "D5", .5, 82), (1, "C5", .5, 84), (1.5, "Ab4", .5, 78), (2, "B4", .5, 88),
        (2.5, "Ab4", .5, 84), (3, "F4", .5, 82), (3.5, "D4", .5, 84)],
    8: [(0, "Eb4", 1.5, 96), (1.5, "D4", .5, 82), (2, "C4", 1, 88), (3, "G3", .5, 80), (3.5, "A3", .5, 84)],
    9: [(0, "Ab3", 1, 90), (1, "F3", .5, 80), (1.5, "Ab3", .5, 84), (2, "B3", .5, 86), (2.5, "D4", .5, 90),
        (3, "F4", .5, 92), (3.5, "G4", 1.5, 98)],
    10: [(1.5, "Eb4", .5, 86), (2, "C4", .5, 84), (2.5, "A3", .5, 82), (3, "C4", .5, 86), (3.5, "Eb4", .5, 90)],
    # ... and the run back up: a diminished arpeggio in triplets, two octaves in two beats
    11: [(0, "G4", 1, 96), (1, "F4", .5, 86), (1.5, "Db4", .5, 84), (2, "E4", T, 84), (2 + T, "G4", T, 88),
         (2 + 2 * T, "Bb4", T, 92), (3, "Db5", T, 96), (3 + T, "E5", T, 100), (3 + 2 * T, "G5", T, 104)],
    12: [(0, "Ab5", 1.5, 110, "roll"), (1.5, "G5", .5, 92), (2, "F5", .5, 92), (2.5, "Eb5", .5, 86),
         (3, "C5", 1, 88)],
    13: [(0, "D5", .5, 86), (.5, "F5", .5, 92), (1, "Ab5", 1, 104), (2, "G5", .5, 94), (2.5, "F5", .5, 90),
         (3, "Eb5", .5, 88), (3.5, "B4", .5, 84)],
    14: [(0, "C5", 1.5, 94), (1.5, "Eb5", .5, 88), (2, "F#5", 1, 100), (3, "Eb5", .5, 88), (3.5, "C5", .5, 86)],
    # the break: the band stops on one and the vibes run down alone
    15: [(.5, "D5", .5, 92), (1, "B4", .5, 88), (1.5, "Ab4", .5, 86), (2, "G4", .5, 86), (2.5, "F4", .5, 84),
         (3, "Eb4", .5, 84), (3.5, "D4", .5, 88)],
}

vibes, vibes_pedal, piano, piano_pedal, bass, drums = [], [], [], [], [], []
END = at(BARS, 0)

# ------------------------------------------------------------------- vibes
for bar, phrase in MELODY.items():
    for beat, pitch, length, vel, *mark in phrase:
        if mark:  # a long note kept alive with a roll, swelling a little
            vibes += roll(at(bar, beat), length, [pitch], vel, vel - 4)
            # pedal down for the roll only, so its strokes run into each other
            vibes_pedal += [[round(at(bar, beat) + 0.05, 3), 64, 127],
                            [round(at(bar, beat) + length, 3), 64, 0]]
        else:
            whole, frac = divmod(beat, 1)
            if abs(frac * 3 - round(frac * 3)) < 1e-6 and frac not in (0, .5):
                beat = whole + unswung(frac)  # triplets
            vibes.append([at(bar, beat), pitch, length, vel])
# The last chord: struck, then rolled between two pairs of bars, dying away.
vibes.append([END, ["C4", "G4", "A4", "D5"], 2.0, 98])
vibes += roll(END + 0.2, 3.3, [["C4", "A4"], ["G4", "D5"]], 84, 44)[1:]
vibes.append([END + 3.5, "G5", 2.3, 74])
vibes.sort(key=lambda x: x[0])
# Vibes need to ring, but at this tempo a pedal held through the bar lets
# neighbouring notes of a line pile up and beat against each other. So the line
# is played with the pedal up and damped the way a player's mallets would:
# a note rings about a beat and a half (a beat in the low octave), and is
# stopped when the bar a step away, or the same bar, is struck.
for i, note in enumerate(vibes):
    later = vibes[i + 1:]
    again = [other[0] for other in later if other[1] == note[1]]
    ring = max(note[2], 2.0)
    if note[0] < END:
        ring = max(note[2], 1.5 if n(note[1]) >= n("C4") else 1.0)
        steps = [other[0] for other in later
                 if isinstance(other[1], str) and 0 < abs(n(other[1]) - n(note[1])) <= 2]
        if steps:
            ring = min(ring, steps[0] - note[0])
    if again:
        ring = min(ring, again[0] - note[0] - 0.05)
    note[2] = round(max(ring, 0.1), 3)
vibes_pedal.append([0, 64, 0])

# ------------------------------------------------- piano, bass, pedal marks
for bar, chords in enumerate(FORM):
    span = BAR / len(chords)
    for index, name in enumerate(chords):
        t = at(bar, index * span)
        voicing = VOICINGS[name]
        if bar in (8, 9, 10) or (bar == 11 and index == 0):
            # the vibes are down in the piano's octave here, so the piano moves above them
            voicing = HIGH.get(name) or [NAMES[n(v) % 12] + str(n(v) // 12) for v in voicing]
        if span == BAR:
            # Comping: one of three figures per bar, chosen by the seed.
            figure = rng.choice([[(0, 1.3), (1.5, .4)], [(1.5, .5), (3, .7)], [(0, .5), (2.5, .9)]])
        else:
            figure = [(0, .7), (1.5, .35)] if rng.random() < 0.4 else [(0, .8)]
        for offset, length in figure:
            accent = 6 if offset in (1.5, 2.5) else 0
            piano.append([round(t + offset, 3), voicing, length, 70 + accent + rng.randint(-4, 4)])
    for beat, pitch in enumerate(WALK[bar].split()):
        lean = 6 if beat == 0 else (3 if beat == 2 else 0)
        bass.append([at(bar, beat), pitch, 0.92, 84 + lean + rng.randint(-3, 3)])

# A vibes note still ringing when the piano plays a chord with a note a semitone
# from it (in any octave) is damped as that chord lands.
for note in vibes:
    if note[0] >= END or not isinstance(note[1], str):
        continue
    for hit in sorted(piano, key=lambda x: x[0]):
        if note[0] + 0.01 < hit[0] < note[0] + note[2] and any(
                abs(n(note[1]) - n(tone)) % 12 in (1, 11) for tone in hit[1]):
            note[2] = round(max(hit[0] - note[0], 0.25), 3)
            break

# ------------------------------------------------------------------- drums
KICK, SNARE, HH_PEDAL, RIDE, CRASH = 36, 38, 44, 51, 49
drums += [[at(-1, 3), SNARE, .2, 68], [at(-1, 3.5), SNARE, .2, 82]]
for bar in range(15):
    for beat in range(BAR):
        # ding, ding-a, ding, ding-a
        drums.append([at(bar, beat), RIDE, .9, 88 + (8 if beat % 2 else 0) + rng.randint(-4, 4)])
        if beat % 2 == 1:
            drums.append([at(bar, beat + .5), RIDE, .4, 72 + rng.randint(-4, 4)])
            drums.append([at(bar, beat), HH_PEDAL, .2, 100 + rng.randint(-4, 4)])  # the "tssch" on two and four
        drums.append([at(bar, beat), KICK, .2, (62 if beat % 2 else 90) + rng.randint(-3, 3)])
    if bar in (7, 14):  # set up the next phrase
        for beat, vel in ((2.5, 62), (3, 72), (3.5, 86)):
            drums.append([at(bar, beat), SNARE, .2, vel])
    elif rng.random() < 0.6:  # a quiet snare comment off the beat
        drums.append([at(bar, rng.choice([1.5, 2.5, 3.5])), SNARE, .2, 56 + rng.randint(-4, 6)])
drums.append([at(0, 0), CRASH, 2, 74])
drums.append([at(8, 0), CRASH, 2, 70])

# ------------------------------------------------- the break and the ending
stop = at(15, 0)
piano.append([stop, ["F3", "B3", "Eb4", "Ab4"], .4, 82])
bass.append([stop, "G1", .5, 96])
drums += [[stop, KICK, .2, 112], [stop, SNARE, .2, 96],
          [at(15, 1), HH_PEDAL, .2, 96], [at(15, 3), HH_PEDAL, .2, 100]]

# A snare fill under the end of the vibes' run: three triplets, then a fast
# six-stroke ruff, growing all the way into the last chord, with the kick pushing.
# (Snare and kick only: the Jazz Kit's tom keys have not been read from the unit.)
fill = [(2, 52), (2 + T, 60), (2 + 2 * T, 68)] + [(3 + i / 6, 72 + i * 5) for i in range(6)]
for beat, vel in fill:
    drums.append([round(unswung(at(15, 0) + beat), 3), SNARE, .15, vel])
drums += [[at(15, 2), KICK, .2, 70], [at(15, 3), KICK, .2, 80],
          [round(unswung(at(15, 3) + 2 * T), 3), KICK, .2, 88]]

vibes_pedal += [[round(END - 0.03, 3), 64, 0], [round(END + 0.05, 3), 64, 127], [END + 5.8, 64, 0]]
piano.append([END, ["C2", "G2", "Eb3", "A3", "C4", "G4"], 5.5, 80])
piano_pedal += [[round(END + 0.05, 3), 64, 127], [END + 5.8, 64, 0]]
bass.append([END, "C2", 5.5, 96])
drums += [[END, CRASH, 4, 92], [END, KICK, .2, 114], [END, RIDE, 3, 80]]

score = {
    "title": "Half Past Blue",
    "description": "Thirty seconds of medium swing in C minor: vibraphone over grand piano, "
                   "walking bass and sticks, with a one-bar break before the last chord.",
    "tempo_bpm": TEMPO,
    "swing": SWING,
    "fx": {
        # Motional Surround off: with it on (big hall, band set well back) the listener
        # could hardly hear the piano and drums in this tune; off, everything was clear.
        # The plain reverb takes over, with the sends the listener heard it with.
        "surround": {"switch": "off"},
        "reverb": {"switch": "on", "type": "hall2", "level": 127},
        "master_eq": {"switch": "on", "low_freq": 200, "low_gain": 2, "mid_freq": 2500,
                      "mid_gain": -2, "mid_q": "0.5", "high_freq": 4000, "high_gain": -6},
        "parts": {
            # Part 1 may have been left monophonic by a saxophone score.
            "1": {"reverb_send": 127, "mono_poly": "tone", "legato": "tone",
                  "bend_range": "tone"},
            "2": {"reverb_send": 25},
            "3": {"reverb_send": 10},
            "10": {"reverb_send": 25},
        },
    },
    "parts": [
        {"part": 1, "patch_id": "sn-a-preset-0169", "level": 94, "pan": 66, "humanize_ms": 12,
         "controls": sorted(vibes_pedal, key=lambda c: c[0]),
         "notes": sorted(vibes, key=lambda x: x[0])},
        {"part": 2, "patch_id": "sn-a-preset-0001", "level": 102, "pan": 44, "humanize_ms": 6,
         "controls": piano_pedal, "notes": sorted(piano, key=lambda x: x[0])},
        {"part": 3, "patch_id": "sn-a-preset-0135", "level": 102, "pan": 70, "humanize_ms": -6,
         "notes": sorted(bass, key=lambda x: x[0])},
        {"part": 10, "patch_id": "sn-d-preset-0007", "level": 114, "pan": 58,
         "notes": sorted(drums, key=lambda x: x[0])},
    ],
}

out = Path(__file__).with_name("half-past-blue.json")
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
print(f"wrote {out}; {(END + 5.8) * 60 / TEMPO:.1f} s at {TEMPO} bpm")
