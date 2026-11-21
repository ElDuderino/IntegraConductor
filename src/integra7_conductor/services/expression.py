"""Expressive performance for SuperNATURAL Acoustic wind tones (saxes first).

Turns a plain note list into a played phrase: slurs and tonguing, a breath-shaped
dynamic line, delayed vibrato, subtone, growl, scoops and falls. Deterministic
for a given seed.

Controller roles are Roland's, from the INTEGRA-7 Parameter Guide's SuperNATURAL
Acoustic controller table (saxes, INT 62-65 and ExSN2 1-4):

    CC1 Dynamics+Vibrato   channel aftertouch Vibrato   CC16 Noise Level
    CC18 Growl Sens        CC19 Bend Mode               CC65 Portamento/Glissando
    CC80 Staccato          CC81 Fall                    CC82 SubTone

Everything else here (curve shapes, delays, probabilities, the style presets) is
this project's own heuristic, not a Roland specification, and is judged by ear.

Notes are ``[beat, pitch, duration_beats, velocity]`` with an optional fifth
element of space-separated marks:

    breath   start a new phrase here (take a breath before it)
    tongue   re-articulate this note instead of slurring into it
    accent   stronger attack          ghost    understated note
    peak     the phrase's high point  straight no vibrato on this note
    stacc    staccato (CC80)          fall     fall-off (CC81)
    scoop    slide up into the note (needs a numeric part bend range, e.g. 2)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any

from .. import errors
from ..errors import usage_error

MARKS = {"breath", "tongue", "accent", "ghost", "peak", "straight", "stacc", "fall", "scoop"}
CC_DYNAMICS, CC_EXPRESSION, CC_NOISE, CC_GROWL, CC_BEND_MODE = 1, 11, 16, 18, 19
CC_PORTAMENTO, CC_STACCATO, CC_FALL, CC_SUBTONE = 65, 80, 81, 82
_CURVE_STEP_MS = 70.0
_PHRASE_GAP_BEATS = 0.2
_BREATH_BEATS = 0.32


@dataclass(frozen=True)
class Style:
    dyn_floor: int  # CC1 at the quiet edges of a phrase
    dyn_peak: int  # CC1 at a full-strength phrase peak
    velocity_scale: float
    velocity_offset: int
    overlap_ms: float  # how far slurred notes overlap
    tongue_gap_ms: float  # silence before a tongued note
    vibrato_min_ms: float  # shorter notes stay straight
    vibrato_delay_ms: tuple[float, float]
    vibrato_depth: tuple[int, int]  # aftertouch range
    straight_chance: float  # long notes sometimes get no vibrato
    subtone_velocity: int  # phrases peaking below this are played subtone (0 = never)
    growl_base: int
    growl_peak: int
    growl_velocity: int  # notes at or above this velocity growl (128 = never)
    noise: int  # CC16, 64 = the tone's own setting
    scoop_chance: float
    scoop_cents: int
    fall_chance: float
    lay_back_ms: float
    drift_ms: float


STYLES: dict[str, Style] = {
    "warm_jazz_tenor": Style(52, 96, 1.0, 0, 30, 45, 800, (250, 450), (35, 70), 0.2, 62,
                             20, 20, 128, 74, 0.12, 35, 0.05, 14, 8),
    "breathy_ballad_tenor": Style(40, 88, 0.92, -4, 38, 60, 900, (300, 520), (28, 58), 0.25,
                                  74, 8, 8, 128, 88, 0.08, 30, 0.0, 22, 10),
    "aggressive_blues_tenor": Style(60, 118, 1.1, 6, 22, 35, 650, (180, 350), (50, 95), 0.1,
                                    0, 30, 100, 100, 70, 0.3, 60, 0.3, 4, 6),
    "lyrical_alto": Style(50, 98, 1.0, 0, 32, 45, 750, (220, 420), (35, 65), 0.15, 0,
                          12, 12, 128, 66, 0.1, 30, 0.03, 8, 6),
    "pop_sax": Style(62, 108, 1.05, 0, 24, 40, 700, (200, 380), (40, 75), 0.1, 0,
                     20, 45, 112, 62, 0.2, 45, 0.15, 0, 4),
}


def _bad(message: str):
    return usage_error(errors.INVALID_ARGUMENT, f"Invalid expression settings: {message}")


def _clamp(value: float, low: int = 0, high: int = 127) -> int:
    return max(low, min(high, int(round(value))))


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class _Note:
    start: float  # beats, after timing feel
    length: float  # written length in beats
    pitch: Any
    velocity: int
    marks: frozenset[str]
    sounding: float = 0.0
    tongued: bool = True


def render(
    notes: list[list[Any]], settings: dict[str, Any], tempo_bpm: float
) -> tuple[list[list[Any]], list[list[Any]]]:
    """Return (notes, controls) for a wind part played with the requested style."""
    name = settings.get("style", "warm_jazz_tenor")
    if name not in STYLES:
        raise _bad(f"unknown style {name!r}; choose from {', '.join(STYLES)}")
    unknown = set(settings) - {
        "instrument", "style", "seed", "intensity", "humanize", "vibrato", "subtone", "growl",
        "scoops", "falls", "bend_range_semitones",
    }
    if unknown:
        raise _bad(f"unknown keys {sorted(unknown)}")

    def amount(key: str, default: float = 1.0) -> float:
        value = settings.get(key, default)
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if not isinstance(value, (int, float)) or not 0 <= value <= 2:
            raise _bad(f"{key} must be a number from 0 to 2 (or true/false)")
        return float(value)

    style = STYLES[name]
    intensity, humanize, vibrato = amount("intensity"), amount("humanize"), amount("vibrato")
    subtone, growl = amount("subtone"), amount("growl")
    style = replace(
        style,
        scoop_chance=style.scoop_chance * amount("scoops"),
        fall_chance=style.fall_chance * amount("falls"),
    )
    bend_range = settings.get("bend_range_semitones", 2)
    if not isinstance(bend_range, (int, float)) or not 1 <= bend_range <= 24:
        raise _bad("bend_range_semitones must be 1-24 and match the part's bend range")
    rng = random.Random(settings.get("seed", 0))
    beat_ms = 60_000.0 / tempo_bpm

    def beats(ms: float) -> float:
        return ms / beat_ms

    # ---- parse, then split into phrases at rests and breath marks
    parsed: list[_Note] = []
    for raw in sorted(notes, key=lambda x: x[0]):
        marks = frozenset(str(raw[4]).split()) if len(raw) > 4 and raw[4] else frozenset()
        if marks - MARKS:
            raise _bad(f"unknown note marks {sorted(marks - MARKS)}")
        if isinstance(raw[1], list):
            raise _bad("a wind part is monophonic; chords are not allowed")
        parsed.append(_Note(float(raw[0]), float(raw[2]), raw[1], int(raw[3]), marks))
    if not parsed:
        return [], []
    phrases: list[list[_Note]] = [[parsed[0]]]
    for prev, note in zip(parsed, parsed[1:], strict=False):
        rest = note.start - (prev.start + prev.length)
        if "breath" in note.marks or rest >= _PHRASE_GAP_BEATS:
            phrases.append([])
        phrases[-1].append(note)

    out_notes: list[list[Any]] = []
    controls: list[list[Any]] = []

    def cc(beat: float, controller: Any, value: float) -> None:
        low, high = (-8192, 8191) if controller == "bend" else (0, 127)
        controls.append([round(max(beat, 0.0), 4), controller, _clamp(value, low, high)])

    for controller, value in (
        (CC_NOISE, 64 + (style.noise - 64) * humanize), (CC_GROWL, style.growl_base * growl),
        (CC_BEND_MODE, 0), (CC_PORTAMENTO, 0), (CC_STACCATO, 0), (CC_FALL, 0), (CC_SUBTONE, 0),
        (CC_EXPRESSION, 112), ("aftertouch", 0), ("bend", 0), (CC_DYNAMICS, style.dyn_floor),
    ):
        cc(0, controller, value)

    drift = 0.0
    last_scoop = -10.0
    previous_end = None
    for index, phrase in enumerate(phrases):
        # ---- timing feel: laid back, with a slow drift shared by neighbouring notes
        for position, note in enumerate(phrase):
            drift = max(-1.0, min(1.0, drift * 0.7 + rng.uniform(-0.5, 0.5)))
            late = style.lay_back_ms + drift * style.drift_ms + (6 if position == 0 else 0)
            note.start += beats(late * humanize)

        # ---- articulation: slur by overlapping, tongue by leaving a gap
        for position, note in enumerate(phrase):
            note.tongued = (
                position == 0 or "tongue" in note.marks or "stacc" in note.marks
                or phrase[position - 1].pitch == note.pitch
                or "stacc" in phrase[position - 1].marks
            )
        for position, note in enumerate(phrase):
            following = phrase[position + 1] if position + 1 < len(phrase) else None
            if "stacc" in note.marks:
                note.sounding = min(note.length * 0.45, beats(160))
            elif following is None:
                note.sounding = note.length * 0.96
                nxt = phrases[index + 1][0] if index + 1 < len(phrases) else None
                if nxt is not None:  # leave room to breathe before the next phrase
                    room = nxt.start - note.start - _BREATH_BEATS
                    note.sounding = max(min(note.sounding, room), note.length * 0.5)
            elif following.tongued:
                gap = beats(style.tongue_gap_ms * rng.uniform(0.85, 1.2))
                note.sounding = max(following.start - note.start - gap, note.length * 0.4)
            else:
                note.sounding = following.start - note.start + beats(style.overlap_ms)

        # ---- the phrase's dynamic arc (CC1): rise to a focal point, then relax
        start = phrase[0].start
        end = phrase[-1].start + phrase[-1].sounding
        focal = next(
            (x for x in phrase if "peak" in x.marks),
            max(phrase, key=lambda x: (x.velocity + (10 if "accent" in x.marks else 0), x.length)),
        )
        focal_at = focal.start + focal.sounding * 0.3
        loud = max(0.0, min(1.0, (focal.velocity - 45) / 55))
        span = (style.dyn_peak - style.dyn_floor) * intensity
        peak = style.dyn_floor + span * (0.5 + 0.5 * loud) * rng.uniform(0.92, 1.05)
        opening = style.dyn_floor + span * rng.uniform(0.18, 0.32)
        closing = style.dyn_floor + span * rng.uniform(0.02, 0.14)

        def level(t: float, phrase=phrase, start=start, end=end, focal_at=focal_at,
                  opening=opening, peak=peak, closing=closing, span=span) -> float:
            if t <= focal_at:
                base = opening + (peak - opening) * _ease((t - start) / max(focal_at - start, 0.01))
            else:
                base = peak + (closing - peak) * _ease((t - focal_at) / max(end - focal_at, 0.01))
            for note in phrase:  # long notes breathe a little on their own
                if note.start <= t <= note.start + note.sounding and note.length >= 1.5:
                    x = (t - note.start) / note.sounding
                    base += span * 0.07 * (4 * x * (1 - x) - 0.5)
            return base

        last_value = None
        steps = max(2, int((end - start) * beat_ms / _CURVE_STEP_MS))
        for step in range(steps + 1):
            t = start + (end - start) * step / steps
            value = _clamp(level(t), 1)
            if value != last_value:
                cc(t - beats(4), CC_DYNAMICS, value)
                last_value = value

        # ---- subtone for quiet phrases; switched just before the phrase is tongued
        use_subtone = bool(subtone) and focal.velocity < style.subtone_velocity * min(subtone, 1.2)
        if use_subtone:
            if previous_end is None or start - previous_end > beats(40):
                cc(start - beats(20), CC_SUBTONE, 127)
            else:
                cc(start - beats(8), CC_SUBTONE, 127)
            cc(end + beats(15), CC_SUBTONE, 0)

        for position, note in enumerate(phrase):
            last_in_phrase = position == len(phrase) - 1
            sounding_ms = note.sounding * beat_ms
            # ---- attack: velocity follows the phrase, not a random spread
            velocity = note.velocity * style.velocity_scale + style.velocity_offset
            velocity += 12 if "accent" in note.marks else 0
            velocity -= 18 if "ghost" in note.marks else 0
            velocity += 5 if note.tongued and position > 0 else 0
            velocity -= 5 if not note.tongued and note.length <= 0.5 else 0
            velocity += drift * 3 * humanize
            out_notes.append(
                [round(note.start, 4), note.pitch, round(note.sounding, 4), _clamp(velocity, 1)]
            )

            # ---- native articulations, switched on for just this note
            wants_fall = "fall" in note.marks or (
                last_in_phrase and index < len(phrases) - 1 and note.length <= 1.0
                and rng.random() < style.fall_chance
            )
            for mark, controller in (("stacc", CC_STACCATO), ("fall", CC_FALL)):
                if mark in note.marks or (mark == "fall" and wants_fall):
                    cc(note.start - beats(10), controller, 127)
                    cc(note.start + note.sounding + beats(20), controller, 0)
            if growl and (note.velocity >= style.growl_velocity):
                cc(note.start - beats(10), CC_GROWL, style.growl_peak * min(growl, 1.27))
                cc(note.start + note.sounding, CC_GROWL, style.growl_base * growl)

            # ---- scoop: a short slide up into selected tongued notes
            wants_scoop = "scoop" in note.marks or (
                note.tongued and note.length >= 0.75 and note.start - last_scoop > 6
                and rng.random() < style.scoop_chance
            )
            if wants_scoop and style.scoop_cents:
                last_scoop = note.start
                depth = -8192 * style.scoop_cents / (bend_range * 100) * rng.uniform(0.8, 1.15)
                rise = beats(rng.uniform(70, 130))
                for step in range(6):
                    at = note.start - beats(6) + rise * step / 5
                    cc(at, "bend", depth * (1 - _ease(step / 5)))

            # ---- vibrato (aftertouch): only on long notes, late, and not always
            straight = "straight" in note.marks or sounding_ms < style.vibrato_min_ms
            chance = style.straight_chance * (0.5 if last_in_phrase else 1.0)
            if not straight and vibrato and rng.random() >= chance:
                delay = min(rng.uniform(*style.vibrato_delay_ms), sounding_ms * 0.45)
                importance = 0.4 + 0.6 * (1.0 if note is focal or last_in_phrase else loud * 0.6)
                low, high = style.vibrato_depth
                depth = (low + (high - low) * importance * rng.uniform(0.8, 1.1)) * vibrato
                ramp = min(rng.uniform(350, 650), sounding_ms * 0.4)
                release = min(160.0, sounding_ms * 0.15)
                hold_until = sounding_ms - release
                for step in range(1, 7):
                    at = delay + ramp * step / 6
                    if at < hold_until:
                        cc(note.start + beats(at), "aftertouch", depth * _ease(step / 6))
                for step in range(1, 4):
                    cc(note.start + beats(hold_until + release * step / 3), "aftertouch",
                       depth * (1 - step / 3))
            cc(note.start + note.sounding + beats(2), "aftertouch", 0)
        previous_end = end

    # ---- leave nothing switched on
    finish = max(n[0] + n[2] for n in out_notes) + beats(60)
    for controller, value in (
        ("aftertouch", 0), ("bend", 0), (CC_STACCATO, 0), (CC_FALL, 0), (CC_SUBTONE, 0),
        (CC_GROWL, style.growl_base * growl), (CC_DYNAMICS, style.dyn_floor),
    ):
        cc(finish, controller, value)
    controls.sort(key=lambda c: c[0])
    return out_notes, controls
