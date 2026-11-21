"""Studio Set effects: reverb, chorus, Motional Surround room, master EQ, per-part mix.

Only named parameters from Roland's published address map (Temporary Studio Set,
18 00 00 00) can be written, each range-checked. There is no raw SysEx path.
Changes edit the *temporary* Studio Set: they are lost when another Studio Set
is loaded unless saved on the unit.

Settings are addressed by dotted paths, the same in the CLI, score files and MCP:

    reverb.type=room2  reverb.level=70  surround.switch=on  surround.room_size=small
    master_eq.high_gain=-6  part.1.reverb_send=40  part.3.surround_lr=-20
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import errors
from ..errors import Integra7Error, usage_error
from ..midi import protocol, sysex
from ..midi.backend import send_step, sleep_step
from ..models import NOT_SENT, VERIFIED, ok_result
from .core import NO_REPLY_HINT, AppContext, block_from_reply, read_blocks

_ON_OFF = ("off", "on")
_MID_FREQS = (200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
              5000, 6300, 8000)


@dataclass(frozen=True)
class Param:
    block: str  # key into BLOCKS
    offset: int
    low: int = 0  # range of the human-facing value
    high: int = 127
    bias: int = 0  # wire value = human value + bias
    choices: tuple[Any, ...] | None = None  # wire value = index into choices
    note: str = ""

    def encode(self, value: Any, path: str) -> int:
        if self.choices is not None:
            wanted = str(value).strip().lower()
            if isinstance(value, bool):
                wanted = "on" if value else "off"
            for index, choice in enumerate(self.choices):
                if wanted in (str(choice).lower(), str(index) if self.choices is _ON_OFF else ""):
                    return index
            raise usage_error(
                errors.INVALID_ARGUMENT,
                f"{path}: {value!r} is not one of {', '.join(str(c) for c in self.choices)}",
            )
        try:
            number = int(str(value).strip())
        except ValueError:
            raise usage_error(
                errors.INVALID_ARGUMENT, f"{path}: expected an integer, got {value!r}"
            ) from None
        if isinstance(value, bool) or not self.low <= number <= self.high:
            raise usage_error(
                errors.INVALID_ARGUMENT, f"{path}: must be {self.low} to {self.high}, got {value!r}"
            )
        return number + self.bias

    def decode(self, wire: int) -> Any:
        if self.choices is not None:
            return self.choices[wire] if wire < len(self.choices) else f"unknown({wire})"
        return wire - self.bias


# Block name -> (third/fourth address bytes relative to 18 00 xx 00, total size).
BLOCKS: dict[str, tuple[int, int]] = {
    "common": (0x00, 0x54),
    "chorus": (0x04, 0x54),
    "reverb": (0x06, 0x63),
    "surround": (0x08, 0x10),
    "master_eq": (0x09, 0x07),
}

GLOBAL_PARAMS: dict[str, Param] = {
    "reverb.switch": Param("common", 0x40, choices=_ON_OFF, note="ignored while surround is on"),
    "reverb.type": Param(
        "reverb", 0x00, choices=("off", "room1", "room2", "hall1", "hall2", "plate", "gm2")
    ),
    "reverb.level": Param("reverb", 0x01),
    "chorus.switch": Param("common", 0x41, choices=_ON_OFF, note="ignored while surround is on"),
    "chorus.type": Param("chorus", 0x00, choices=("off", "chorus", "delay", "gm2")),
    "chorus.level": Param("chorus", 0x01),
    "surround.switch": Param("surround", 0x00, choices=_ON_OFF, note="Motional Surround"),
    "surround.room_type": Param("surround", 0x01, choices=("room1", "room2", "hall1", "hall2")),
    "surround.ambience_level": Param("surround", 0x02),
    "surround.room_size": Param("surround", 0x03, choices=("small", "medium", "large")),
    "surround.ambience_time": Param("surround", 0x04, high=100),
    "surround.ambience_density": Param("surround", 0x05, high=100),
    "surround.ambience_hf_damp": Param("surround", 0x06, high=100),
    "surround.depth": Param("surround", 0x0C, high=100),
    "master_eq.switch": Param("common", 0x42, choices=_ON_OFF),
    "master_eq.low_freq": Param("master_eq", 0x00, choices=(200, 400)),
    "master_eq.low_gain": Param("master_eq", 0x01, low=-15, high=15, bias=15, note="dB"),
    "master_eq.mid_freq": Param("master_eq", 0x02, choices=_MID_FREQS),
    "master_eq.mid_gain": Param("master_eq", 0x03, low=-15, high=15, bias=15, note="dB"),
    "master_eq.mid_q": Param("master_eq", 0x04, choices=("0.5", "1.0", "2.0", "4.0", "8.0")),
    "master_eq.high_freq": Param("master_eq", 0x05, choices=(2000, 4000, 8000)),
    "master_eq.high_gain": Param("master_eq", 0x06, low=-15, high=15, bias=15, note="dB"),
}

# Per-part parameters live in the Studio Set Part block; path is part.<n>.<name>.
PART_PARAMS: dict[str, Param] = {
    "level": Param("part", 0x09),
    "pan": Param("part", 0x0A, low=-64, high=63, bias=64, note="-64 left to +63 right"),
    "mono_poly": Param("part", 0x0D, choices=("mono", "poly", "tone"),
                       note="tone = use the tone's own setting"),
    "legato": Param("part", 0x0E, choices=("off", "on", "tone")),
    "bend_range": Param("part", 0x0F, choices=(*(str(i) for i in range(25)), "tone"),
                        note="semitones; 'tone' gives wind tones their gliss/fall bend"),
    "portamento": Param("part", 0x10, choices=("off", "on", "tone")),
    "attack_offset": Param("part", 0x15, low=-64, high=63, bias=64),
    "decay_offset": Param("part", 0x16, low=-64, high=63, bias=64),
    "release_offset": Param("part", 0x17, low=-64, high=63, bias=64),
    "chorus_send": Param("part", 0x27),
    "reverb_send": Param("part", 0x28),
    "surround_lr": Param("part", 0x44, low=-64, high=63, bias=64, note="left/right position"),
    "surround_fb": Param("part", 0x46, low=-64, high=63, bias=64, note="front/back position"),
    "surround_width": Param("part", 0x48, high=32),
    "ambience_send": Param("part", 0x49, note="send to the surround room ambience"),
}


def _block_address(block: str, part: int | None = None) -> tuple[tuple[int, int, int, int], int]:
    if block == "part":
        assert part is not None
        return sysex.studio_set_part_address(part), sysex.SIZE_STUDIO_SET_PART
    third, size = BLOCKS[block]
    base = sysex.ADDR_TEMP_STUDIO_SET
    return (base[0], base[1], third, 0x00), size


def flatten(settings: Any, prefix: str = "") -> dict[str, Any]:
    """Turn nested {"reverb": {"type": "room1"}} into {"reverb.type": "room1"}."""
    if not isinstance(settings, dict):
        raise usage_error(errors.INVALID_ARGUMENT, "effect settings must be an object")
    flat: dict[str, Any] = {}
    for key, value in settings.items():
        path = f"{prefix}{key}".replace("parts.", "part.")
        if isinstance(value, dict):
            flat.update(flatten(value, path + "."))
        else:
            flat[path] = value
    return flat


def _resolve(path: str) -> tuple[Param, int | None]:
    pieces = path.split(".")
    if len(pieces) == 3 and pieces[0] == "part" and pieces[2] in PART_PARAMS:
        try:
            part = int(pieces[1])
        except ValueError:
            part = 0
        return PART_PARAMS[pieces[2]], protocol.validate_part(part)
    if path in GLOBAL_PARAMS:
        return GLOBAL_PARAMS[path], None
    raise usage_error(
        errors.INVALID_ARGUMENT,
        f"Unknown effect parameter {path!r}",
        details={
            "global": sorted(GLOBAL_PARAMS),
            "per_part": [f"part.<1-16>.{name}" for name in PART_PARAMS],
        },
    )


def describe() -> dict[str, Any]:
    def info(p: Param) -> dict[str, Any]:
        out: dict[str, Any] = (
            {"values": list(p.choices)} if p.choices is not None else {"range": [p.low, p.high]}
        )
        if p.note:
            out["note"] = p.note
        return out

    return ok_result(
        {
            "global": {path: info(p) for path, p in GLOBAL_PARAMS.items()},
            "per_part": {f"part.<1-16>.{name}": info(p) for name, p in PART_PARAMS.items()},
            "note": "Edits the temporary Studio Set only. Reverb and chorus are bypassed by "
            "the unit while surround.switch is on.",
        }
    )


def show(ctx: AppContext, parts: list[int] | None = None) -> dict[str, Any]:
    """Read the current effect settings from the unit."""
    wanted = [protocol.validate_part(p) for p in (parts or range(1, 17))]
    requests = [_block_address(name) for name in BLOCKS]
    requests += [_block_address("part", p) for p in wanted]
    blocks = read_blocks(ctx, requests)
    by_block = dict(zip(BLOCKS, blocks, strict=False))
    data: dict[str, Any] = {"source": "mock_device" if ctx.backend.is_mock else "device_readback"}
    for path, param in GLOBAL_PARAMS.items():
        group, name = path.split(".")
        data.setdefault(group, {})[name] = param.decode(by_block[param.block][param.offset])
    data["parts"] = [
        {"part": part, **{n: p.decode(block[p.offset]) for n, p in PART_PARAMS.items()}}
        for part, block in zip(wanted, blocks[len(BLOCKS):], strict=True)
    ]
    return ok_result(data, backend=ctx.backend_name)


def apply(
    ctx: AppContext, settings: dict[str, Any], *, dry_run: bool | None = None
) -> dict[str, Any]:
    """Write named effect parameters with DT1 and confirm each one by readback."""
    cfg = ctx.config
    dry_run = cfg.dry_run if dry_run is None else dry_run
    flat = flatten(settings)
    if not flat:
        raise usage_error(errors.INVALID_ARGUMENT, "No effect settings given")

    writes = []  # (path, block key, block address, size, offset, wire value)
    try:
        for path, value in flat.items():
            param, part = _resolve(path)
            address, size = _block_address(param.block, part)
            writes.append((path, address, size, param, param.encode(value, path)))
    except Integra7Error as exc:
        exc.verification_status = NOT_SENT
        raise

    messages = [
        sysex.build_dt1(cfg.device_id, sysex.address_add(address, param.offset), [wire])
        for _, address, _, param, wire in writes
    ]
    data: dict[str, Any] = {
        "settings": {path: param.decode(wire) for path, _, _, param, wire in writes},
        "port": ctx.sysex_out_port(),
        "sysex_hex": [protocol.hex_str(m) for m in messages],
        "sent": False,
        "dry_run": dry_run,
        "readback": {"status": "not_attempted"},
    }
    warnings = []
    surround_on = flat.get("surround.switch")
    if any(p.startswith(("reverb.", "chorus.")) for p in flat) and str(surround_on).lower() in (
        "on", "true", "1",
    ):
        warnings.append("The unit bypasses reverb and chorus while Motional Surround is on.")
    if dry_run:
        return ok_result(
            data, backend=ctx.backend_name, verification_status=NOT_SENT, warnings=warnings
        )

    if ctx.live_inject(messages):
        data["sent"] = True
        data["readback"] = {"status": "skipped", "reason": "playback in progress"}
        warnings.append(
            "Queued into the running playback; it takes effect within a moment and is not "
            "read back."
        )
        return ok_result(
            data, backend=ctx.backend_name, verification_status=ctx.sent_status(),
            warnings=warnings,
        )

    blocks = list(dict.fromkeys((address, size) for _, address, size, _, _ in writes))
    steps = [send_step(ctx.sysex_out_port(), messages), sleep_step(cfg.settle_ms)]
    steps += [ctx.rq1_step(address, size) for address, size in blocks]
    result = ctx.transact(steps)
    data["sent"] = True
    status = ctx.sent_status()

    observed: dict[tuple[int, ...], bytes | None] = {}
    for index, (address, size) in enumerate(blocks):
        observed[address], info = block_from_reply(ctx, result, index, address, size)
        if observed[address] is None:
            data["readback"] = info
    mismatches = {}
    if all(v is not None for v in observed.values()):
        for path, address, _, param, wire in writes:
            got = observed[address][param.offset]  # type: ignore[index]
            if got != wire:
                mismatches[path] = {"requested": param.decode(wire), "device": param.decode(got)}
        data["readback"] = {"status": "mismatch" if mismatches else "matched"}
        if mismatches:
            data["readback"]["mismatches"] = mismatches
            err = Integra7Error(
                errors.MIDI_NOT_VERIFIED,
                "Effect settings were sent, but the unit reports different values for: "
                + ", ".join(mismatches),
                details=data,
                hint="Check SYSTEM > MIDI > Rx Exclusive and the device ID.",
            )
            err.verification_status = status
            raise err
        if not ctx.backend.is_mock:
            status = VERIFIED
    else:
        warnings.append(f"Readback unavailable. {NO_REPLY_HINT}")
    return ok_result(data, backend=ctx.backend_name, verification_status=status, warnings=warnings)


def parse_assignments(pairs: list[str]) -> dict[str, Any]:
    """Parse CLI arguments of the form path=value."""
    out: dict[str, Any] = {}
    for pair in pairs:
        path, sep, value = pair.partition("=")
        if not sep or not path.strip() or not value.strip():
            raise usage_error(
                errors.INVALID_ARGUMENT,
                f"Expected path=value, got {pair!r} (try `integra7 fx list`)",
            )
        out[path.strip()] = value.strip()
    return out
