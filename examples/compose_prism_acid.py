#!/usr/bin/env python3
"""Generates prism-acid.json: the "Prism" promo soundtrack on INTEGRA-7 dance sounds.

    python3 examples/compose_prism_acid.py              # 707 drums -> prism-acid.json
    python3 examples/compose_prism_acid.py --kit 808    # -> prism-acid-808.json
    python3 examples/compose_prism_acid.py --kit 909    # -> prism-acid-909.json
    python3 examples/compose_prism_acid.py --reverb plate --no-acid-echo --out /tmp/take.json
    integra7 play examples/prism-acid.json

The notes and the timeline are not written here. They are read from
prism_score.py in the Aretas3DAssets repository (lightshow-connected/), the file
the Prism video's lasers and titles also follow, so this stays in step with the
picture: 128 bpm acid house in A minor, twelve bars and a last hit (24 s).

What each thing in the original became:

  drum machine      SRX-05 "All TR Menu" on three parts (kick, hats, clap/snare/
                    crash) so each has its own level and reverb. Keys were read
                    from the unit: 36-50 are TR-707, 51-78 TR-808, 79-103 TR-909.
  303 acid line     SuperNATURAL synth "TB Bass 2": one saw through a resonant
                    low-pass, mono, legato. Slides are overlapping notes with
                    portamento switched on (CC65) only for the note slid into.
                    The tone ignores velocity, so an accent is a louder note
                    (CC11) with the filter a little further open (CC74).
  filter automation The score's cutoff and resonance curves, sent as CC74 and
                    CC71. On the INTEGRA-7 these are offsets around the tone's
                    own setting (64 = unchanged).
  "the door"        Bar 1 heard through a wall: CC74 held low on the kick, hats
                    and acid parts, opening through bar 2.
  side-chain pump   CC11 dips on every kick: pad most, acid less, lead least.
  pad swell         CC11 rising through the build (bars 7-8).
  ping-pong delay   Written out as notes, because the unit's own delays do not
                    follow the tempo. The acid line repeats a dotted eighth
                    later on a part panned left and again on one panned right,
                    with the same filter moves; the lead's echoes are an eighth
                    apart. The low end cannot be filtered out of the echoes,
                    so the acid echoes play an octave up, quietly.
  reverb            Studio Set reverb (hall2) with the original's send amounts.

Part 1 is not used: the KeyStep plays it.

Heard by the owner on the unit (2026-11-21): the acid line "pretty good"; with
the long 808 kick and these levels "everything else is great". Not yet heard:
the 808 and 909 kits with the later changes. Of the three kits the 707 was preferred
("the un tss un tss in that 707 is pretty sick"), so it is the default.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCORE_DIR = HERE.parents[1] / "Aretas3DAssets" / "lightshow-connected"

# General MIDI drum note (what prism_score.py uses) -> key in "All TR Menu".
# The 808 has no ride cymbal, so that kit borrows the 707's.
KITS = {
    "808": {36: 54, 38: 56, 39: 68, 42: 74, 46: 76, 49: 70, 51: 50},
    "707": {36: 54, 38: 38, 39: 45, 42: 47, 46: 48, 49: 49, 51: 50},
    "909": {36: 81, 38: 82, 39: 92, 42: 93, 46: 96, 49: 98, 51: 101},
}
# Kicks, measured from a recording of the unit (time to fall 20 dB; share of energy at 30-80 Hz):
#   707 kick 1/2 (36, 37)  48 ms, 63%       909 kick 3 (79)  36 ms, 35%
#   808 kick 1-3 (51-53)   about 40 ms      909 kick 2 (80) 157 ms, 57%
#   808 kick 4 (54)       437 ms, 93%       909 kick 1 (81) 203 ms, 60%
#   808 kick 5 (55)       over 1 s, 98%  (longer than a beat at 128 bpm)
# The short ones alone sounded "poppy" to the listener (808 kick 1), so every kit's kick
# is a long one at full velocity with a short one layered on top for the click:
# kit -> [(key, share of the kick's velocity)].
# The 707 kick (66 Hz) partly cancels the long 808 kick (50 Hz). Measured at 30-70 Hz:
# 808 kick 4 alone at velocity 127, 14.2 dB; with the 707 kick at 127, 12.4; with the 707
# at 90, 13.0; and at velocity 114 under the 707 at 127 (the first 707 version, where the
# listener found "the deep thump is basically gone"), 10.5. So the 707 kick is the quiet layer.
KICK_LAYERS = {
    "808": [(51, 0.55)],
    "707": [(36, 0.7)],
    "909": [],
}
DRUM_KIT = "srx05-drum-0034"      # All TR Menu (needs SRX-05 loaded)
ACID_TONE = "sn-s-preset-0687"    # TB Bass 2
# Lead: SEQ 10, a saw pluck whose own effect is an equalizer. Most preset leads (Stn MG
# Lead, Reso Juno, Saw Lead n, Tekno Sqr ...) carry a delay effect (MFX type 35 or 36 read
# back from the unit) that does not follow the tempo; the listener heard it as off-beat.
LEAD_TONE = "sn-s-preset-0556"
PAD_TONE = "sn-s-preset-0021"     # JUNO Str 1

# name -> part, level (CC7), pan (CC10, 64 = centre), reverb send
PARTS = {
    "acid_echo": dict(part=3, level=46, pan=30, reverb=90),     # first echo, left
    "acid_echo_r": dict(part=11, level=34, pan=98, reverb=100),  # second echo, right
    "acid":   dict(part=2, level=90, pan=64, reverb=42),
    "lead":   dict(part=4, level=76, pan=48, reverb=120),
    "echo_l": dict(part=5, level=62, pan=18, reverb=100),
    "echo_r": dict(part=6, level=62, pan=110, reverb=100),
    "pad":    dict(part=7, level=80, pan=77, reverb=100),
    "perc":   dict(part=8, level=112, pan=64, reverb=95),
    "hats":   dict(part=9, level=122, pan=73, reverb=28),
    "kick":   dict(part=10, level=127, pan=64, reverb=0),
}

# Acid filter: the original's cutoff 0..1 and resonance 0..1 as offsets around 64.
CUTOFF_CENTRE, CUTOFF_SPAN = 0.47, 160    # 0.33 -> 42, 0.47 -> 64, 0.60 -> 85, 0.87 -> 127
RESONANCE_CENTRE, RESONANCE_SPAN = 0.80, 167   # 0.80 -> 64, 0.86 -> 74, 0.92 -> 84
ACCENT_CUTOFF = 12                # extra CC74 on an accented step
PLAIN_LEVEL = 0.78                # CC11 of an unaccented step, as a share of an accent
SLIDE_STEPS = 1.3                 # length of a note that slides into the next one
DOOR_HATS = 0.2                   # hat velocity scale while the door is shut
DOOR_ACID, DOOR_DRUMS = 6, 0      # CC74 while the door is shut (bar 1)
PUMP = {"acid_echo": 0.85, "acid_echo_r": 0.85, "pad": 0.80, "acid": 0.45, "lead": 0.30, "echo_l": 0.30, "echo_r": 0.30}
PUMP_RELEASE = 0.22               # seconds for a ducked part to come back
PAD_BUILD = (0.15, 0.90)          # pad CC11 share at the start and end of the build
ECHO_STEPS = 2                    # an eighth, so every echo lands on the grid (3 = the original's dotted eighth)
ECHO_VELOCITIES = (62, 40)        # first echo left, second right
ACID_ECHO_STEPS = 3               # the acid echo: a dotted eighth late
# The echoes play an octave up and duck hard on every kick. At the line's own pitch (A1 is
# 55 Hz) and ducking a dotted eighth late, with the acid reverb send at 60, the listener
# found the kick's low end "scooped out ... quite hard to hear".
ACID_ECHO_TRANSPOSE = 12
SURROUND_HALL = {"switch": "on", "room_type": "hall1", "room_size": "large", "ambience_level": 100,
                 "ambience_time": 70, "ambience_density": 100, "depth": 100}
ECHO_CUTOFF = 50                  # CC74 on the echo parts: duller than the dry lead
# The ride on every beat after the drop. The original's is nearly as loud as the open hats
# (the highs on the beat rise 8.5 dB at the drop); at the score's velocity 60 the 707 ride
# barely registered (2.5 dB) and the listener missed "a crash cymbal on every kick".
RIDE_VELOCITY = 122
CLOSED_HAT = 0.8                  # closed-hat velocity scale; the hats part level is set for the open hats


def load_prism_score(folder: Path):
    path = folder / "prism_score.py"
    if not path.exists():
        raise SystemExit(f"prism_score.py not found in {folder}; pass --score-dir")
    spec = importlib.util.spec_from_file_location("prism_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose(ps, kit: str, lead: str = LEAD_TONE, reverb: str = "hall2", acid_echo: bool = True) -> dict:
    beat = ps.BEAT
    step = 0.25                                   # a sixteenth, in beats
    end = round(ps.DURATION / beat, 3)

    def b(seconds: float) -> float:
        return round(seconds / beat, 4)

    def door(seconds: float) -> float:
        """0 while the door is shut, 1 once it is open."""
        u = (seconds - ps.T_DOOR) / (ps.T_OPEN - ps.T_DOOR)
        return min(max(u, 0.0), 1.0) ** 1.5

    def pump(seconds: float) -> float:
        """1 on a kick, falling back to 0."""
        before = [k for k in ps.KICKS if k <= seconds + 1e-6]
        return math.exp(-3 * (seconds - before[-1]) / PUMP_RELEASE) if before else 0.0

    grid = [i * step / 2 * beat for i in range(int(end / (step / 2)))]   # every 32nd, seconds
    notes: dict[str, list] = {name: [] for name in PARTS}
    controls: dict[str, list] = {name: [] for name in PARTS}

    def control(name: str, seconds: float, controller: int, value: float) -> None:
        value = min(max(int(round(value)), 0), 127)
        stream = controls[name]
        for entry in reversed(stream):            # skip a value that is already set
            if entry[1] == controller:
                if entry[2] == value:
                    return
                break
        stream.append([b(seconds), controller, value])

    # Drums: one kit on three parts.
    for name in ("kick", "hats", "perc"):
        for when, _length, pitch, velocity in ps.PARTS[name]:
            long = pitch in (46, 49, 51)          # open hat, crash, ride
            if pitch == 42:
                velocity = round(velocity * CLOSED_HAT)
            if pitch == 51:
                velocity = RIDE_VELOCITY
            if name == "hats":                    # the 707 hats ignore CC74, so the door also turns them down
                velocity = max(1, round(velocity * (DOOR_HATS + (1 - DOOR_HATS) * door(when))))
            notes[name].append([b(when), KITS[kit][pitch], 0.9 if long else 0.2, velocity])
            if pitch == 36:
                for key, share in KICK_LAYERS[kit]:
                    notes[name].append([b(when), key, 0.2, round(velocity * share)])
    for name in ("kick", "hats"):
        for t in grid:
            if t > ps.T_OPEN:
                break
            control(name, t, 74, DOOR_DRUMS + (64 - DOOR_DRUMS) * door(t))
    control("perc", 0, 74, 64)

    # Acid line.
    acid = sorted(ps.PARTS["acid"])
    accents = {b(when) for when, _l, _p, velocity in acid if velocity >= 100}
    for i, (when, length, pitch, _velocity) in enumerate(acid):
        slides = i + 1 < len(acid) and when + length > acid[i + 1][0]
        slid_into = i > 0 and acid[i - 1][0] + acid[i - 1][1] > when
        steps = SLIDE_STEPS * step if slides else length / beat
        notes["acid"].append([b(when), pitch, round(steps, 4), 110])
        control("acid", when, 65, 127 if slid_into else 0)
    resonance = dict(ps.ACID_RESONANCE)
    for when, cut in ps.ACID_CUTOFF:
        value = 64 + (cut - CUTOFF_CENTRE) * CUTOFF_SPAN
        if b(when) in accents:
            value += ACCENT_CUTOFF
        w = door(when)
        control("acid", when, 74, DOOR_ACID + (value - DOOR_ACID) * w)
        if when in resonance:
            control("acid", when, 71, 64 + (resonance[when] - RESONANCE_CENTRE) * RESONANCE_SPAN)
    accent_now = 1.0
    for t in grid:
        if b(t) % step == 0:
            accent_now = 1.0 if b(t) in accents else PLAIN_LEVEL
        control("acid", t, 11, 127 * accent_now * (1 - PUMP["acid"] * pump(t)))

    # Optional: the acid line again a dotted eighth later, quiet and to the left, with the
    # same filter moves. The low end cannot be kept out of it, so it stays far down.
    for k, name in enumerate(("acid_echo", "acid_echo_r"), start=1):
        if not acid_echo:
            del notes[name], controls[name]
            continue
        late = k * ACID_ECHO_STEPS * step
        notes[name] = [[round(n[0] + late, 4), n[1] + ACID_ECHO_TRANSPOSE, *n[2:]]
                       for n in notes["acid"] if n[0] + late < end - 1]
        controls[name] = [[round(c[0] + late, 4), c[1], c[2]] for c in controls["acid"]
                          if c[1] != 11 and c[0] + late < end]
        for t in grid:                            # ducked on the kick itself, not a dotted eighth late
            control(name, t, 11, 127 * (1 - PUMP[name] * pump(t)))

    # Lead and its echoes.
    for when, length, pitch, velocity in ps.PARTS["lead"]:
        notes["lead"].append([b(when), pitch, b(length), velocity])
        for k, echo_velocity in enumerate(ECHO_VELOCITIES, start=1):
            start = b(when) + k * ECHO_STEPS * step
            if start < end - 0.5:
                side = "echo_l" if k % 2 else "echo_r"
                notes[side].append([round(start, 4), pitch, b(length), echo_velocity])
    for name in ("echo_l", "echo_r"):
        control(name, 0, 74, ECHO_CUTOFF)
        notes[name].sort()

    # Pad: swells in through the build, pumps with the kick.
    for when, length, pitch, velocity in ps.PARTS["pad"]:
        notes["pad"].append([b(when), pitch, b(length), velocity])
    for t in grid:
        u = min(max((t - ps.T_BUILD) / (ps.T_DROP - ps.T_BUILD), 0.0), 1.0)
        swell = 1.0 if t >= ps.T_DROP else PAD_BUILD[0] + (PAD_BUILD[1] - PAD_BUILD[0]) * u
        control("pad", t, 11, 127 * swell * (1 - PUMP["pad"] * pump(t)))
        for name in ("lead", "echo_l", "echo_r"):
            control(name, t, 11, 127 * (1 - PUMP[name] * pump(t)))

    # Leave every part as it was found: filter offsets neutral, full expression, no glide.
    for name in notes:
        for controller, value in ((74, 64), (71, 64), (11, 127), (65, 0)):
            if any(entry[1] == controller for entry in controls[name]):
                controls[name].append([end, controller, value])

    tones = {"acid_echo": ACID_TONE, "acid_echo_r": ACID_TONE, "acid": ACID_TONE, "lead": lead, "echo_l": lead, "echo_r": lead,
             "pad": PAD_TONE, "kick": DRUM_KIT, "hats": DRUM_KIT, "perc": DRUM_KIT}
    neutral = {"attack_offset": 0, "decay_offset": 0, "release_offset": 0, "chorus_send": 0}
    voice = {
        "acid": {"mono_poly": "mono", "legato": "on", "portamento": "off"},
        "acid_echo": {"mono_poly": "mono", "legato": "on", "portamento": "off"},
        "acid_echo_r": {"mono_poly": "mono", "legato": "on", "portamento": "off"},
        "lead": {"mono_poly": "tone", "legato": "tone", "portamento": "tone"},
        "echo_l": {"mono_poly": "poly", "legato": "off", "portamento": "off"},
        "echo_r": {"mono_poly": "poly", "legato": "off", "portamento": "off"},
    }
    fx_parts = {}
    for name, spec in PARTS.items():
        if name not in notes:
            continue
        settings = {"reverb_send": spec["reverb"], "ambience_send": spec["reverb"],
                    "surround_lr": round((spec["pan"] - 64) * 0.6), "surround_fb": 0, **neutral, "bend_range": "tone",
                    **voice.get(name, {"mono_poly": "tone", "legato": "tone", "portamento": "tone"})}
        fx_parts[str(spec["part"])] = settings
    return {
        "title": f"Prism (acid, TR-{kit})",
        "description": "The Prism promo soundtrack from Aretas3DAssets/lightshow-connected/"
                       f"prism_score.py: TR-{kit} drums, a TB-303 style acid line, a plucked "
                       "synth lead and a Juno pad. Twelve bars of acid house in A minor and a last hit.",
        "tempo_bpm": ps.BPM,
        "fx": {"surround": SURROUND_HALL if reverb == "surround" else {"switch": "off"},
               "reverb": {"switch": "on", "type": "hall2" if reverb == "surround" else reverb, "level": 127},
               "master_eq": {"switch": "off"},
               "parts": fx_parts},
        "parts": [
            {"part": spec["part"], "patch_id": tones[name], "level": spec["level"],
             "pan": spec["pan"], "controls": controls[name], "notes": notes[name]}
            for name, spec in PARTS.items() if name in notes
        ],
    }


def write(score: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write("{\n")
        for key in ("title", "description", "tempo_bpm", "fx"):
            fh.write(f"  {json.dumps(key)}: {json.dumps(score[key])},\n")
        fh.write('  "parts": [\n')
        for i, part in enumerate(score["parts"]):
            head = {k: v for k, v in part.items() if k not in ("notes", "controls")}
            fh.write("    " + json.dumps(head)[:-1])
            if part["controls"]:
                fh.write(', "controls": ' + json.dumps(part["controls"]))
            fh.write(', "notes": [\n')
            fh.write(",\n".join("      " + json.dumps(note) for note in part["notes"]))
            fh.write("\n    ]}" + ("," if i + 1 < len(score["parts"]) else "") + "\n")
        fh.write("  ]\n}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--kit", choices=sorted(KITS), default="707")
    parser.add_argument("--reverb", choices=("hall1", "hall2", "plate", "room1", "room2", "surround"),
                        default="hall2", help="Studio Set reverb type, or the Motional Surround hall")
    parser.add_argument("--no-acid-echo", action="store_true", help="leave out the acid line's echoes")
    parser.add_argument("--score-dir", type=Path, default=SCORE_DIR,
                        help="folder holding prism_score.py")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--lead", default=LEAD_TONE, help="patch id of the lead tone")
    args = parser.parse_args()
    out = args.out or HERE / ("prism-acid.json" if args.kit == "707" else f"prism-acid-{args.kit}.json")
    score = compose(load_prism_score(args.score_dir), args.kit, args.lead, args.reverb, not args.no_acid_echo)
    write(score, out)
    count = sum(len(p["notes"]) for p in score["parts"])
    print(f"wrote {out} ({count} notes, {sum(len(p['controls']) for p in score['parts'])} controls)")


if __name__ == "__main__":
    main()
