"""Play a short multi-part score: select each part's patch, then send timed notes.

A convenience for auditioning arrangements, not a sequencer: one score, played
once, as a single hardware transaction. Score format (JSON):

    {"title": "...", "tempo_bpm": 132, "swing": 0.64,
     "parts": [{"part": 1, "patch_id": "sn-a-preset-0166", "level": 100, "pan": 64,
                "notes": [[beat, pitch, duration_beats, velocity], ...],
                "controls": [[beat, controller, value], ...]}]}

``controls`` is optional: timed Control Changes, e.g. [0, 64, 127] presses the
sustain pedal at beat 0 and [3.9, 64, 0] releases it. Use "bend" as the
controller for pitch bend (-8192..8191). ``humanize_ms`` on a part shifts all of
its events (negative = ahead of the beat). Use "aftertouch" as the controller
for channel pressure. A part's ``expression`` object (see services/expression.py)
plays a wind part with phrasing: {"style": "breathy_ballad_tenor", "seed": 7};
such parts may add a fifth note element with marks like "breath" or "accent".
A top-level ``fx`` object (see
services/fx.py) is applied and read back before playback starts.

``beat`` counts quarter notes from 0. ``pitch`` is a MIDI number, a name such as
"Bb3" (C4 = 60), or a list of either for a chord. ``swing`` (0.5 straight to
0.75) moves the off-beat eighth: 0.667 is triplet swing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import errors
from ..errors import Integra7Error, usage_error
from ..midi import protocol
from ..midi.backend import send_step, sequence_step, sleep_step
from ..models import KIND_STUDIO_SET, NOT_SENT, ok_result
from . import expansions, expression, fx
from . import patches as patch_service
from .core import AppContext

MAX_DURATION_MS = 280_000
MAX_NOTES = 20_000
PATCH_LOAD_MS = 500
CC_LEVEL, CC_PAN = 7, 10

_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
_SEMITONES = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def _bad(message: str) -> Integra7Error:
    err = usage_error(errors.INVALID_ARGUMENT, f"Invalid score: {message}")
    err.verification_status = NOT_SENT
    return err


def parse_pitch(value: Any) -> int:
    if isinstance(value, str):
        m = _NOTE_RE.match(value.strip())
        if not m:
            raise _bad(f"unrecognized note name {value!r}")
        accidental = {"#": 1, "b": -1, "": 0}[m.group(2)]
        value = (int(m.group(3)) + 1) * 12 + _SEMITONES[m.group(1).lower()] + accidental
    return protocol.validate_note(value)


def swing_beat(beat: float, swing: float) -> float:
    """Map a straight beat position to its swung position (piecewise linear per beat)."""
    whole, frac = divmod(beat, 1.0)
    if frac < 0.5:
        return whole + frac * (swing / 0.5)
    return whole + swing + (frac - 0.5) * ((1.0 - swing) / 0.5)


def load_score(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise Integra7Error(errors.SOURCE_NOT_FOUND, f"Score file not found: {p}")
    try:
        score = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _bad(f"{p} is not valid JSON ({exc})") from exc
    if not isinstance(score, dict):
        raise _bad("the top level must be an object")
    return score


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise _bad(f"{name} must be a number from {low:g} to {high:g}, got {value!r}")
    return float(value)


def play_score(
    ctx: AppContext,
    score: dict[str, Any],
    *,
    dry_run: bool | None = None,
    tempo_bpm: float | None = None,
    only_parts: list[int] | None = None,
    loops: int = 1,
    keep_patch: list[int] | None = None,
    dump_events: str | None = None,
    keep_fx: bool = False,
) -> dict[str, Any]:
    cfg = ctx.config
    dry_run = cfg.dry_run if dry_run is None else dry_run
    tempo = _number(tempo_bpm if tempo_bpm is not None else score.get("tempo_bpm", 120),
                    "tempo_bpm", 30, 300)
    swing = _number(score.get("swing", 0.5), "swing", 0.5, 0.75)
    ms_per_beat = 60_000.0 / tempo
    if keep_fx:  # leave the unit's current effect settings alone
        score = {k: v for k, v in score.items() if k != "fx"}
    parts = score.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 16:
        raise _bad("'parts' must be a list of 1-16 entries")

    if only_parts:
        wanted = {protocol.validate_part(p) for p in only_parts}
        parts = [e for e in parts if isinstance(e, dict) and e.get("part") in wanted]
        if not parts:
            raise _bad(f"the score has none of the requested parts {sorted(wanted)}")

    setup: list[bytes] = []
    # (time, order at equal times: 0 note-off, 1 control change, 2 note-on, message)
    events: list[tuple[float, int, bytes]] = []
    summary: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[int] = set()
    for entry in parts:
        if not isinstance(entry, dict):
            raise _bad("each part must be an object")
        part = protocol.validate_part(entry.get("part"))
        if part in seen:
            raise _bad(f"part {part} appears twice")
        seen.add(part)
        channel, channel_source = cfg.channel_for_part(part)
        if channel_source == "default_assumption":
            warnings.append(f"Part {part} -> channel {channel} is an unconfirmed assumption.")
        patch = None
        if entry.get("patch_id") and part not in (keep_patch or []):
            try:
                patch = patch_service.resolve_patch(ctx, patch_id=entry["patch_id"])
            except Integra7Error as exc:
                exc.verification_status = NOT_SENT
                raise
            if patch.kind == KIND_STUDIO_SET:
                raise _bad(f"{patch.id} is a Studio Set, not a part tone")
            warnings += expansions.check_patch(ctx, patch)
            setup += protocol.bank_program_select(
                channel, patch.bank_msb, patch.bank_lsb, patch.program
            )
        for key, controller in (("level", CC_LEVEL), ("pan", CC_PAN)):
            if entry.get(key) is not None:
                value = int(_number(entry[key], f"part {part} {key}", 0, 127))
                setup.append(protocol.control_change(channel, controller, value))

        shift_ms = _number(entry.get("humanize_ms", 0), f"part {part} humanize_ms", -100, 100)
        notes = entry.get("notes")
        if not isinstance(notes, list) or not notes:
            raise _bad(f"part {part} has no notes")
        controls = entry.get("controls") or []
        if not isinstance(controls, list):
            raise _bad(f"part {part}: 'controls' must be a list")
        if entry.get("expression"):
            if not isinstance(entry["expression"], dict):
                raise _bad(f"part {part}: 'expression' must be an object")
            for note in notes:
                if not isinstance(note, list) or len(note) not in (4, 5):
                    raise _bad(f"part {part}: each note is [beat, pitch, duration, velocity]")
                _number(note[0], "beat", 0, 100_000)
                _number(note[2], "duration_beats", 0.01, 64)
                protocol.validate_velocity(note[3])
            try:
                notes, generated = expression.render(notes, entry["expression"], tempo)
            except Integra7Error as exc:
                exc.verification_status = NOT_SENT
                raise
            controls = [*controls, *generated]
        count = 0
        for note in notes:
            if not isinstance(note, list) or len(note) != 4:
                raise _bad(f"part {part}: each note is [beat, pitch, duration_beats, velocity]")
            beat = _number(note[0], "beat", 0, 100_000)
            duration = _number(note[2], "duration_beats", 0.01, 64)
            velocity = protocol.validate_velocity(note[3])
            start = max(0.0, swing_beat(beat, swing) * ms_per_beat + shift_ms)
            end = swing_beat(beat + duration, swing) * ms_per_beat + shift_ms - 5
            end = max(end, start + 20)
            pitches = note[1] if isinstance(note[1], list) else [note[1]]
            for pitch in map(parse_pitch, pitches):
                events.append((start, 2, protocol.note_on(channel, pitch, velocity)))
                events.append((end, 0, protocol.note_off(channel, pitch)))
                count += 1
        for control in controls:
            if not isinstance(control, list) or len(control) != 3:
                raise _bad(f"part {part}: each control is [beat, controller, value]")
            when = swing_beat(_number(control[0], "beat", 0, 100_000), swing) * ms_per_beat
            when = max(0.0, when + shift_ms)
            if control[1] == "bend":
                bend = int(_number(control[2], "pitch bend", -8192, 8191))
                events.append((when, 1, protocol.pitch_bend(channel, bend)))
                continue
            if control[1] == "aftertouch":
                pressure = int(_number(control[2], "aftertouch", 0, 127))
                events.append((when, 1, protocol.channel_pressure(channel, pressure)))
                continue
            controller = int(_number(control[1], "controller", 1, 119))
            value = int(_number(control[2], "control value", 0, 127))
            events.append((when, 1, protocol.control_change(channel, controller, value)))
        summary.append(
            {
                "part": part,
                "channel": channel,
                "patch_id": patch.id if patch else None,
                "patch_name": patch.name if patch else None,
                "notes": count,
            }
        )

    events.sort(key=lambda e: (e[0], e[1]))
    if isinstance(loops, bool) or not isinstance(loops, int) or not 1 <= loops <= 20:
        raise _bad(f"loops must be 1-20, got {loops!r}")
    if loops > 1:
        length = events[-1][0] + ms_per_beat  # one beat of air between passes
        events = [(t + i * length, order, m) for i in range(loops) for t, order, m in events]
    duration_ms = events[-1][0]
    note_count = sum(1 for e in events if e[1] == 2)
    if note_count > MAX_NOTES or duration_ms > MAX_DURATION_MS:
        raise _bad(
            f"too long: {note_count} notes, {duration_ms / 1000:.0f}s "
            f"(limits {MAX_NOTES} notes, {MAX_DURATION_MS // 1000}s)"
        )
    data: dict[str, Any] = {
        "title": score.get("title"),
        "tempo_bpm": tempo,
        "swing": swing,
        "duration_ms": round(duration_ms),
        "parts": summary,
        "note_count": note_count,
        "setup_messages_hex": [protocol.hex_str(m) for m in setup],
        "port": cfg.performance_port,
        "sent": False,
        "dry_run": dry_run,
    }
    if dump_events:
        # Diagnostic record of exactly what will be sent, in order.
        lines = [{"t_ms": 0, "hex": protocol.hex_str(m), "stage": "setup"} for m in setup]
        lines += [{"t_ms": round(t, 1), "hex": protocol.hex_str(m)} for t, _, m in events]
        Path(dump_events).write_text(json.dumps(lines, indent=0) + "\n", encoding="utf-8")
        data["events_file"] = dump_events
    if dry_run:
        if score.get("fx"):
            data["fx"] = fx.apply(ctx, score["fx"], dry_run=True)["data"]["settings"]
        return ok_result(
            data, backend=ctx.backend_name, verification_status=NOT_SENT, warnings=warnings
        )
    if score.get("fx"):
        applied = fx.apply(ctx, score["fx"], dry_run=False)
        data["fx"] = {
            "verification_status": applied["verification_status"],
            "settings": applied["data"]["settings"],
        }
        warnings += applied.get("warnings") or []
    steps = []
    if setup:
        steps += [send_step(cfg.performance_port, setup), sleep_step(PATCH_LOAD_MS)]
    live = cfg.live_path()
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("", encoding="utf-8")
    steps.append(
        sequence_step(
            cfg.performance_port, [(t, m) for t, _, m in events], ctx.backend.adapter_path(live)
        )
    )
    try:
        result = ctx.transact(steps)
    finally:
        live.unlink(missing_ok=True)
    data["live_messages_sent"] = sum(
        s.get("live_messages_sent", 0) for s in result.get("sequences", [])
    )
    data["sent"] = True
    data["port"] = result["ports"].get(cfg.performance_port, cfg.performance_port)
    warnings.append("Playback is never verified: sound cannot be observed over MIDI.")
    return ok_result(
        data, backend=ctx.backend_name, verification_status=ctx.sent_status(), warnings=warnings
    )
