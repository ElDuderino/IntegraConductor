#!/usr/bin/env python3
"""Generates last-set-at-the-blue-room.json: a late-1940s club ballad for the INTEGRA-7.

    python3 examples/compose_last_set.py            # rewrite the score next to this file
    integra7 play examples/last-set-at-the-blue-room.json

    python3 examples/compose_last_set.py vibes      # same tune, different lead instrument
    integra7 play examples/last-set-at-the-blue-room-vibes.json

Leads: sax (default), vibes, clarinet, piano (a drummerless trio: piano, guitar, bass).

Tenor sax lead, upright piano, string bass in two, four-to-the-bar rhythm guitar,
brushes, and a muted trumpet answering from the back of the room. Eb major, AA'
with a two-bar piano intro and a held last chord, heard from across a large room.

The drum notes are the Jazz Brushes kit's real key map, read from the unit:
36 jazz kick, 37 brush slide, 38 brush tap, 39 brush slap, 40 soft tap,
44 hi-hat pedal, 51 brush ride, 55 brush splash, 88 applause.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

LEAD = sys.argv[1] if len(sys.argv) > 1 else "sax"
if LEAD not in ("sax", "vibes", "clarinet", "piano"):
    sys.exit(f"unknown lead {LEAD!r}: choose sax, vibes, clarinet or piano")
rng = random.Random(1947)
BAR = 4
TEMPO = 76
NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def n(name: str) -> int:
    m = re.fullmatch(r"([A-G][#b]?)(-?\d)", name)
    pc = {"C#": 1, "D#": 3, "Gb": 6, "G#": 8, "A#": 10, "Cb": 11}.get(m.group(1))
    if pc is None:
        pc = NAMES.index(m.group(1))
    return (int(m.group(2)) + 1) * 12 + pc - (12 if m.group(1) == "Cb" else 0)


def at(bar: int, beat: float) -> float:
    return bar * BAR + beat


# chord -> (bass root, piano left-hand shell, piano right hand, guitar voicing)
CHORDS = {
    "Eb6":   ("Eb2", ["G3", "C4"], ["Eb4", "G4", "Bb4"], ["Bb2", "G3", "C4"]),
    "Edim":  ("E2", ["G3", "Db4"], ["E4", "G4", "Bb4"], ["Bb2", "G3", "Db4"]),
    "Fm7":   ("F2", ["Ab3", "Eb4"], ["F4", "Ab4", "C5"], ["C3", "Ab3", "Eb4"]),
    "Bb7":   ("Bb1", ["Ab3", "D4"], ["F4", "Bb4", "C5"], ["F3", "Ab3", "D4"]),
    "Bb7b9": ("Bb1", ["Ab3", "D4"], ["F4", "B4", "D5"], ["F3", "Ab3", "D4"]),
    "Bb7+":  ("Bb1", ["Ab3", "D4"], ["F#4", "Bb4", "D5"], ["F#3", "Ab3", "D4"]),
    "Gm7b5": ("G2", ["F3", "Bb3"], ["Db4", "F4", "G4"], ["Db3", "F3", "Bb3"]),
    "C7b9":  ("C2", ["E3", "Bb3"], ["Db4", "E4", "G4"], ["C3", "E3", "Bb3"]),
    "C7":    ("C2", ["E3", "Bb3"], ["D4", "E4", "G4"], ["C3", "E3", "Bb3"]),
    "Eb7/G": ("G2", ["G3", "Db4"], ["Eb4", "G4", "Bb4"], ["Bb2", "G3", "Db4"]),
    "Ab6":   ("Ab2", ["Ab3", "C4"], ["Eb4", "F4", "Ab4"], ["Eb3", "Ab3", "C4"]),
    "Abm6":  ("Ab2", ["Ab3", "B3"], ["Eb4", "F4", "Ab4"], ["Eb3", "Ab3", "B3"]),
    "Eb/Bb": ("Bb1", ["G3", "Bb3"], ["Eb4", "G4", "Bb4"], ["Bb2", "G3", "Bb3"]),
    "Eb69":  ("Eb2", ["G3", "C4"], ["F4", "Bb4", "Eb5"], ["Bb2", "G3", "C4"]),
}
A1 = [
    ["Eb6", "Edim"], ["Fm7", "Bb7"], ["Eb6", ("Gm7b5", "C7b9")], ["Fm7", "Bb7"],
    ["Eb6", "Eb7/G"], ["Ab6", "Abm6"], ["Eb/Bb", "C7"], ["Fm7", "Bb7"],
]
A2 = A1[:6] + [["Fm7", "Bb7b9"], ["Eb6", "Abm6"]]
FORM = [["Fm7", "Bb7"], ["Eb6", "Bb7+"]] + A1 + A2  # bars 0-1 are the piano intro
LAST = len(FORM)  # bar index of the held final chord


def changes(bar: int) -> list[tuple[float, str]]:
    """(beat within bar, chord) pairs; a tuple in a half bar splits it into quarters."""
    out = []
    for half, item in enumerate(FORM[bar]):
        if isinstance(item, tuple):
            out += [(half * 2, item[0]), (half * 2 + 1, item[1])]
        else:
            out.append((half * 2, item))
    return out


sax, sax_cc, piano, pedal, bass, guitar, drums, trumpet = [], [], [], [], [], [], [], []

# ---------------------------------------------------------------- tenor sax
# (beat in bar, pitch, length in beats, velocity); "~" after the pitch = start a new breath
MELODY_A1 = [
    [(0, "G4~", 1.5, 74), (1.5, "F4", .5, 66), (2, "Eb4", 1, 68), (3, "G4", 1, 72)],
    [(0, "Ab4", 2, 78), (2, "F4~", .5, 64), (2.5, "G4", .5, 66), (3, "Ab4", .5, 70), (3.5, "Bb4", .5, 74)],
    [(0, "C5", 1.5, 84), (1.5, "Bb4", .5, 72), (2, "G4", 1, 74), (3, "E4", .5, 68), (3.5, "Db4", .5, 66)],
    [(0, "C4", 2.5, 70), (3, "Bb3~", .5, 60), (3.5, "D4", .5, 64)],
    [(0, "Eb4", 1, 70), (1, "G4", .5, 70), (1.5, "Bb4", 1.5, 80), (3, "Db5", 1, 86)],
    [(0, "C5", 1.5, 84), (1.5, "Ab4", .5, 72), (2, "B4", 1.5, 82), (3.5, "Ab4", .5, 70)],
    [(0, "G4", 2, 76), (2, "E4~", .5, 66), (2.5, "G4", .5, 70), (3, "Bb4", .5, 76), (3.5, "Ab4", .5, 72)],
    [(0, "G4", 1, 74), (1, "F4", 1, 68), (2, "D4", 1.5, 66), (3.5, "Bb3~", .5, 58)],
]
MELODY_A2 = [
    [(0, "G4~", 1, 76), (1, "Bb4", .5, 74), (1.5, "F4", .5, 66), (2, "Eb4", 1, 68), (3, "G4", 1, 74)],
    [(0, "Ab4", 1.5, 80), (1.5, "C5", .5, 78), (2, "F4~", .5, 66), (2.5, "G4", .5, 68), (3, "Ab4", .5, 72), (3.5, "Bb4", .5, 78)],
    [(0, "C5", 1, 86), (1, "Eb5", .5, 90), (1.5, "Bb4", .5, 76), (2, "G4", 1, 76), (3, "E4", .5, 70), (3.5, "Db4", .5, 68)],
    [(0, "C4", 2.5, 72), (3, "Bb3~", .5, 62), (3.5, "D4", .5, 66)],
    [(0, "Eb4", 1, 72), (1, "G4", .5, 72), (1.5, "Bb4", 1.5, 82), (3, "Db5", 1, 90)],
    [(0, "C5", 1.5, 88), (1.5, "Ab4", .5, 74), (2, "B4", 1.5, 84), (3.5, "Ab4", .5, 72)],
    [(0, "Ab4", 1, 78), (1, "F4", .5, 68), (1.5, "G4", .5, 70), (2, "B4", 1, 80), (3, "Bb4", .5, 74), (3.5, "F4", .5, 66)],
    [(0, "Eb4", 2, 72), (2, "F4~", 1, 64), (3, "Ab4", 1, 70)],
]


def sax_note(beat: float, pitch: str, length: float, vel: int, marks: str = "") -> None:
    # Here we only write the tune and mark where breaths fall. The clarinet variant has
    # its phrasing (slurs, breath, dynamics, vibrato) added at play time by the expression
    # layer; the tenor is played plain, an octave down (see the lead options below).
    sax.append([round(beat, 3), pitch, length, vel, marks])


for section, start_bar in ((MELODY_A1, 2), (MELODY_A2, 10)):
    for i, bar in enumerate(section):
        for beat, pitch, length, vel in bar:
            marks = "breath" if pitch.endswith("~") else ""
            sax_note(at(start_bar + i, beat), pitch.rstrip("~"), length, vel, marks)
sax_note(at(LAST, 0), "G4", 6.5, 74, "breath")  # last note, held over the final chord

# ------------------------------------------------- muted trumpet, far away
for bar, phrase in (
    (5, [(1.5, "C5", .5, 50), (2, "Eb5", .5, 54), (2.5, "D5", 1.2, 52)]),
    (9, [(2.5, "F5", .5, 52), (3, "D5", .9, 50)]),
    (13, [(1.5, "Eb5", .5, 52), (2, "F5", .5, 56), (2.5, "D5", 1.2, 54)]),
    (15, [(3.5, "Eb5", .5, 50)]),
    (17, [(0.5, "Bb4", .5, 50), (1, "C5", .9, 52)]),
):
    for beat, pitch, length, vel in phrase:
        trumpet.append([at(bar, beat), pitch, length, vel])
trumpet.append([at(LAST, 0), "C5", 6.5, 48])

# ------------------------------------------- piano, bass, guitar, per chord
for bar in range(LAST):
    chords = changes(bar)
    intro = bar < 2
    for index, (beat, name) in enumerate(chords):
        root, shell, right, gtr = CHORDS[name]
        span = (chords[index + 1][0] if index + 1 < len(chords) else BAR) - beat
        t = at(bar, beat)
        # Piano: soft left-hand shell on the change, right hand answering a beat later.
        piano.append([t, shell, min(span, 1.9), 50 + rng.randint(-4, 4) + (10 if intro else 0)])
        if span >= 2:
            piano.append([t + 1, right, 0.85, 44 + rng.randint(-4, 5) + (12 if intro else 0)])
            if (bar + index) % 3 == 0 and not intro:
                piano.append([t + 1.5, right[-1], 0.4, 36])  # a little grace on the off-beat
        pedal.append([max(t - 0.03, 0), 64, 0])
        pedal.append([t + 0.05, 64, 127])
        # Bass in two: root, then a fifth or a leading tone on the weak half.
        bass.append([t, root, min(span, 2) * 0.92, 82 + rng.randint(-4, 4)])
        if span >= 2 and bar >= 2 and bar % 4 == 3 and index == 1:
            following = CHORDS[changes(bar + 1)[0][1]][0] if bar + 1 < LAST else "Eb2"
            bass.append([t + 1.5, NAMES[(n(following) - 1) % 12] + "2", 0.45, 66])
        # Rhythm guitar: four to the bar, short and quiet, leaning on two and four.
        if bar >= 2:
            for q in range(int(span)):
                accent = 8 if (beat + q) % 2 == 1 else 0
                for string, note in enumerate(gtr):
                    guitar.append([round(t + q + string * 0.012, 3), note, 0.36,
                                   40 + accent + rng.randint(-3, 3)])
    if intro:  # a right-hand line to lead the band in
        line = [(0, "C5"), (1, "Ab4"), (2, "Bb4"), (3, "D5")] if bar == 0 else \
               [(0, "Eb5"), (1, "Bb4"), (2, "D5"), (2.5, "F#5"), (3, "Bb5")]
        for beat, pitch in line:
            piano.append([at(bar, beat), pitch, 0.9, 62])

# ----------------------------------------------------------------- brushes
KICK, SLIDE, TAP, SLAP, SOFT_TAP = 36, 37, 38, 39, 40
HH_PEDAL, RIDE, SPLASH, APPLAUSE = 44, 51, 55, 88
for bar in range(1, LAST):
    for beat in range(BAR):
        drums.append([at(bar, beat), SLIDE, 0.9, 46 + (8 if beat % 2 else 0) + rng.randint(-4, 4)])
        if beat % 2 == 1:
            drums.append([at(bar, beat), TAP, 0.2, 52 + rng.randint(-5, 5)])
            drums.append([at(bar, beat), HH_PEDAL, 0.2, 44])
            drums.append([at(bar, beat + 0.5), SOFT_TAP, 0.2, 34 + rng.randint(-4, 4)])
        elif bar >= 2:
            drums.append([at(bar, beat), KICK, 0.2, 28 + rng.randint(-3, 3)])  # feathered
    if bar in (9, 17):  # a small turnaround figure
        for beat, vel in ((2.5, 44), (3, 50), (3.5, 58)):
            drums.append([at(bar, beat), TAP, 0.2, vel])
    if bar in (2, 10):
        drums.append([at(bar, 0), RIDE, 1.5, 46])

# ------------------------------------------------------------- final chord
end = at(LAST, 0)
root, shell, right, gtr = CHORDS["Eb69"]
piano.append([end, ["Eb2", "Bb2"] + shell + right, 7, 58])
piano.append([end + 1.5, "Bb5", 1, 44])
piano.append([end + 2.5, "Eb6", 4, 40])
pedal += [[end - 0.03, 64, 0], [end + 0.05, 64, 127], [end + 7.5, 64, 0]]
bass.append([end, "Eb2", 7, 84])
for string, note in enumerate(gtr):
    guitar.append([end + string * 0.03, note, 5, 44])
drums += [[end, SPLASH, 4, 46], [end, KICK, 0.2, 40], [end, SLIDE, 3, 50]]
drums.append([end + 7.5, APPLAUSE, 9, 62])  # the room, after the last chord dies


def slow_down(parts: list[list]) -> None:
    """Ease into the last chord: stretch the final bar before it."""
    start = at(LAST - 1, 2)

    def warp(beat: float) -> float:
        if beat <= start:
            return beat
        if beat < end:
            x = beat - start
            return start + x * (1 + 0.16 * x)
        return beat + (end - start) * 0.32

    for events in parts:
        for event in events:
            original = event[0]
            event[0] = round(warp(original), 3)
            if len(event) >= 4:  # note: keep its end in step with the stretch
                event[2] = round(max(warp(original + event[2]) - event[0], 0.1), 3)


# ------------------------------------------------------------ lead options
lead = {"part": 1, "patch_id": "sn-a-preset-0236", "level": 112, "pan": 66,
        "expression": {"style": "breathy_ballad_tenor", "seed": 1947}}
# A wind player sounds one note at a time: mono + legato lets overlapping notes slur.
# A numeric bend range makes pitch bend an ordinary bend, used for the scoops.
lead_fx = {"mono_poly": "mono", "legato": "on", "bend_range": "2"}
if LEAD == "sax":
    # Played the way the listener's keyboard plays this tone, which they found far
    # better than the shaped, slurred version: an octave below the written tune (down
    # in the tenor's low register), every note attacked on its own with a small gap,
    # struck firmly, and with no controller messages at all.
    sax = [[beat, NAMES[n(pitch) % 12] + str(n(pitch) // 12 - 2), round(length * 0.85, 3),
            min(vel + 24, 110)] for beat, pitch, length, vel, _marks in sax]
    del lead["expression"]
elif LEAD == "clarinet":
    lead.update(patch_id="sn-a-preset-0243", level=104)
    lead["expression"] = {"style": "warm_jazz_tenor", "seed": 1947, "subtone": 0, "falls": 0}
elif LEAD in ("vibes", "piano"):
    # Struck instruments: no breath controls. Let every note ring about two beats,
    # damped just before the same bar or key is struck again, with the pedal
    # changing on each chord.
    order = sorted(range(len(sax)), key=lambda i: sax[i][0])
    for position, i in enumerate(order):
        note = sax[i]
        again = [sax[j][0] for j in order[position + 1:] if sax[j][1] == note[1]]
        ring = max(note[2], 2.0)
        note[2] = round(min(ring, again[0] - note[0] - 0.05) if again else ring, 3)
        note[3] = min(note[3] + 8, 110)
    sax = [note[:4] for note in sax]
    sax_cc = [list(c) for c in pedal]
    del lead["expression"]
    lead_fx = {"mono_poly": "tone", "legato": "tone", "bend_range": "tone"}
    if LEAD == "vibes":
        lead.update(patch_id="sn-a-preset-0166", level=108, humanize_ms=10)
    else:
        # The melody moves to a second piano part, an octave up, over guitar and bass.
        for note in sax:
            note[1] = NAMES[n(note[1]) % 12] + str(n(note[1]) // 12)
        lead.update(patch_id="sn-a-preset-0001", level=104, humanize_ms=6)
        drums, trumpet = [], []
        piano = [p for p in piano if p[3] < 70]  # thin the accompaniment a little

slow_down([sax, sax_cc, piano, pedal, bass, guitar, drums, trumpet])

score = {
    "title": "Last Set at the Blue Room",
    "description": "A late-1940s club ballad in Eb: tenor sax, upright piano, bass, rhythm "
                   "guitar, brushes and a distant muted trumpet, heard from across a big room.",
    "tempo_bpm": TEMPO,
    "swing": 0.64,
    "fx": {
        # Motional Surround is the INTEGRA-7's room simulator; each part gets a place on
        # the bandstand. (The unit bypasses its plain reverb and chorus while this is on.)
        "surround": {"switch": "on", "room_type": "hall1", "room_size": "large",
                     "ambience_level": 127, "ambience_time": 88, "ambience_density": 100,
                     "depth": 100},
        # Roll the top off and warm the bottom, like an old recording.
        "master_eq": {"switch": "on", "low_freq": 200, "low_gain": 2, "mid_freq": 2500,
                      "mid_gain": -2, "mid_q": "0.5", "high_freq": 4000, "high_gain": -6},
        # Everyone sits well back in a big room: high ambience sends, and front/back
        # positions pushed away from the listener (sax nearest, trumpet furthest).
        "parts": {
            "1": {"surround_lr": 4, "surround_fb": -30, "surround_width": 6,
                  "ambience_send": 110, **lead_fx},
            "2": {"surround_lr": -30, "surround_fb": -48, "surround_width": 14,
                  "ambience_send": 120},
            "3": {"surround_lr": 12, "surround_fb": -44, "surround_width": 6,
                  "ambience_send": 105},
            "4": {"surround_lr": 28, "surround_fb": -48, "surround_width": 8,
                  "ambience_send": 120},
            "5": {"surround_lr": 20, "surround_fb": -60, "surround_width": 6,
                  "ambience_send": 127, "mono_poly": "mono", "legato": "on"},
            "10": {"surround_lr": -12, "surround_fb": -54, "surround_width": 16,
                   "ambience_send": 124},
        },
    },
    "parts": [
        {**lead, "controls": sorted(sax_cc, key=lambda c: c[0]),
         "notes": sorted(sax, key=lambda x: x[0])},
        {"part": 2, "patch_id": "sn-a-preset-0006", "level": 86, "pan": 44, "humanize_ms": 8,
         "controls": sorted(pedal, key=lambda c: c[0]), "notes": sorted(piano, key=lambda x: x[0])},
        {"part": 3, "patch_id": "sn-a-preset-0135", "level": 108, "pan": 70, "humanize_ms": -6,
         "notes": sorted(bass, key=lambda x: x[0])},
        {"part": 4, "patch_id": "sn-a-preset-0099", "level": 60, "pan": 84, "humanize_ms": 4,
         "notes": sorted(guitar, key=lambda x: x[0])},
        {"part": 5, "patch_id": "sn-a-preset-0221", "level": 62, "pan": 78,
         "expression": {"style": "warm_jazz_tenor", "seed": 5, "intensity": 0.6, "subtone": 0,
                        "scoops": 0, "falls": 0},
         "notes": trumpet},
        {"part": 10, "patch_id": "sn-d-preset-0009", "level": 92, "pan": 58,
         "notes": sorted(drums, key=lambda x: x[0])},
    ],
}

score["parts"] = [p for p in score["parts"] if p["notes"]]
suffix = "" if LEAD == "sax" else f"-{LEAD}"
out = Path(__file__).with_name(f"last-set-at-the-blue-room{suffix}.json")
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
print(f"wrote {out}")
