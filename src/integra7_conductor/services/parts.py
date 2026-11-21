"""Part services: channel map, tone selection, audition, part readback."""

from __future__ import annotations

from typing import Any

from .. import errors
from ..catalog import database
from ..config import update_config_file
from ..errors import Integra7Error
from ..midi import protocol, sysex
from ..midi.backend import send_step, sleep_step
from ..models import KIND_STUDIO_SET, NOT_SENT, VERIFIED, Patch, ok_result
from . import expansions
from . import patches as patch_service
from .core import NO_REPLY_HINT, AppContext, block_from_reply, read_blocks

LIVE_NOTE = (
    "Queued into the running playback; it takes effect within a moment and is not read back."
)
ASSUMPTION_NOTE = (
    "Parts without an explicit mapping ASSUME part N receives on MIDI channel N. "
    "Confirm with `integra7 part channels --from-device` or set them explicitly."
)


def _patch_summary(patch: Patch) -> dict[str, Any]:
    return {
        "id": patch.id,
        "name": patch.name,
        "kind": patch.kind,
        "bank": patch.bank,
        "bank_msb": patch.bank_msb,
        "bank_lsb": patch.bank_lsb,
        "program": patch.program,
        "display_pc": patch.display_pc,
        "expansion_required": patch.expansion_required,
    }


def _decode_part_block(data: bytes) -> dict[str, Any]:
    return {
        "receive_channel": data[sysex.PART_RX_CHANNEL] + 1,
        "receive_switch": bool(data[sysex.PART_RX_SWITCH]),
        "bank_msb": data[sysex.PART_BANK_MSB],
        "bank_lsb": data[sysex.PART_BANK_LSB],
        "program": data[sysex.PART_PROGRAM],
        "display_pc": data[sysex.PART_PROGRAM] + 1,
    }


def channel_map(ctx: AppContext) -> dict[str, Any]:
    rows = []
    for part in range(1, 17):
        channel, source = ctx.config.channel_for_part(part)
        rows.append({"part": part, "channel": channel, "source": source})
    assumed = [r["part"] for r in rows if r["source"] == "default_assumption"]
    return ok_result(
        {"source": "configuration", "parts": rows, "assumed_parts": assumed},
        warnings=[ASSUMPTION_NOTE] if assumed else None,
    )


def set_channel(ctx: AppContext, part: int, channel: int) -> dict[str, Any]:
    part = protocol.validate_part(part)
    channel = protocol.validate_channel(channel)
    merged = dict(ctx.config.part_channels)
    merged[part] = channel
    update_config_file(ctx.config.path, {"part_channels": merged})
    ctx.config.part_channels = merged
    return ok_result(
        {
            "part": part,
            "channel": channel,
            "config_path": ctx.config.path,
            "note": "This updates the local mapping only; nothing was sent to the device.",
        }
    )


def read_parts(ctx: AppContext, parts: list[int] | None = None) -> list[dict[str, Any]]:
    wanted = [protocol.validate_part(p) for p in (parts or range(1, 17))]
    blocks = read_blocks(
        ctx, [(sysex.studio_set_part_address(p), sysex.SIZE_STUDIO_SET_PART) for p in wanted]
    )
    out = []
    for part, data in zip(wanted, blocks, strict=True):
        state = {"part": part, **_decode_part_block(data)}
        try:
            patch = database.get_patch_by_address(
                ctx.conn(), state["bank_msb"], state["bank_lsb"], state["program"]
            )
        except Integra7Error:
            patch = None  # catalog not built; the raw address is still reported
        state["patch_id"] = patch.id if patch else None
        state["patch_name"] = patch.name if patch else None
        out.append(state)
    return out


def channel_map_from_device(ctx: AppContext, save: bool = False) -> dict[str, Any]:
    """Read each part's receive channel with documented RQ1 requests."""
    states = read_parts(ctx)
    observed = {s["part"]: s["receive_channel"] for s in states}
    differences = [
        {"part": p, "configured": ctx.config.channel_for_part(p)[0], "device": ch}
        for p, ch in observed.items()
        if ctx.config.channel_for_part(p)[0] != ch
    ]
    data: dict[str, Any] = {
        "source": "mock_device" if ctx.backend.is_mock else "device_readback",
        "parts": [
            {
                "part": s["part"],
                "channel": s["receive_channel"],
                "receive_switch": s["receive_switch"],
            }
            for s in states
        ],
        "differences_from_config": differences,
        "saved": False,
    }
    if save and not ctx.backend.is_mock:
        update_config_file(ctx.config.path, {"part_channels": observed})
        ctx.config.part_channels = observed
        data["saved"] = True
        data["config_path"] = ctx.config.path
    return ok_result(data, backend=ctx.backend_name)


def show_part(ctx: AppContext, part: int) -> dict[str, Any]:
    state = read_parts(ctx, [part])[0]
    state["source"] = "mock_device" if ctx.backend.is_mock else "device_readback"
    return ok_result(state, backend=ctx.backend_name)


def select_patch(
    ctx: AppContext,
    part: int,
    *,
    patch_id: str | None = None,
    name: str | None = None,
    dry_run: bool | None = None,
    verify: bool | None = None,
) -> dict[str, Any]:
    """Select a tone or drum kit on a part: CC#0, CC#32, Program Change on its channel."""
    part = protocol.validate_part(part)
    cfg = ctx.config
    dry_run = cfg.dry_run if dry_run is None else dry_run
    verify = cfg.verify if verify is None else verify

    try:
        patch = patch_service.resolve_patch(ctx, patch_id=patch_id, name=name)
    except Integra7Error as exc:
        exc.verification_status = NOT_SENT  # unresolved or ambiguous: no MIDI was sent
        raise
    if patch.kind == KIND_STUDIO_SET:
        err = Integra7Error(
            errors.WRONG_PATCH_KIND,
            f"{patch.name} ({patch.id}) is a Studio Set, not a part tone; nothing was sent",
            hint=f"Use `integra7 studio-set select {patch.display_pc}`. It is sent on the Studio "
            "Set Control Channel and replaces all part settings.",
        )
        err.verification_status = NOT_SENT
        raise err

    channel, channel_source = cfg.channel_for_part(part)
    messages = protocol.bank_program_select(
        channel, patch.bank_msb, patch.bank_lsb, patch.program
    )
    warnings = expansions.check_patch(ctx, patch)
    if channel_source == "default_assumption":
        warnings.append(
            f"Part {part} -> channel {channel} is an unconfirmed default assumption."
        )
    if not patch.in_documented_range:
        warnings.append(f"{patch.id} lies outside the address ranges Roland documents.")

    data: dict[str, Any] = {
        "part": part,
        "channel": channel,
        "channel_source": channel_source,
        "patch_name": patch.name,
        "patch": _patch_summary(patch),
        "port": cfg.performance_port,
        "midi_messages_hex": [protocol.hex_str(m) for m in messages],
        "sent": False,
        "dry_run": dry_run,
        "readback": {"status": "not_attempted"},
    }
    if dry_run:
        return ok_result(
            data, backend=ctx.backend_name, verification_status=NOT_SENT, warnings=warnings
        )

    if ctx.live_inject(messages):
        data["sent"] = True
        data["readback"] = {"status": "skipped", "reason": "playback in progress"}
        warnings.append(LIVE_NOTE)
        return ok_result(
            data, backend=ctx.backend_name, verification_status=ctx.sent_status(),
            warnings=warnings,
        )

    address = sysex.studio_set_part_address(part)
    steps = [send_step(cfg.performance_port, messages)]
    if verify:
        steps += [sleep_step(cfg.settle_ms), ctx.rq1_step(address, sysex.SIZE_STUDIO_SET_PART)]
    result = ctx.transact(steps)
    data["sent"] = True
    data["port"] = result["ports"].get(cfg.performance_port, cfg.performance_port)
    status = ctx.sent_status()

    if verify:
        block, info = block_from_reply(ctx, result, 0, address, sysex.SIZE_STUDIO_SET_PART)
        data["readback"] = info
        if block is None:
            warnings.append(f"Readback unavailable ({info['status']}). {NO_REPLY_HINT}")
        else:
            observed = _decode_part_block(block)
            info["observed"] = observed
            matched = (observed["bank_msb"], observed["bank_lsb"], observed["program"]) == (
                patch.address()
            )
            info["status"] = "matched" if matched else "mismatch"
            if not matched:
                hints = []
                if observed["receive_channel"] != channel:
                    hints.append(
                        f"The device reports part {part} receives on channel "
                        f"{observed['receive_channel']}, but channel {channel} was used. Run "
                        "`integra7 part channels --from-device --save`."
                    )
                if not observed["receive_switch"]:
                    hints.append(f"Part {part} has Rx Switch OFF.")
                hints.append(
                    "Also check SYSTEM > MIDI Rx Program Change / Rx Bank Select and the "
                    "part's Rx Program Change / Rx Bank Select filters."
                )
                err = Integra7Error(
                    errors.MIDI_NOT_VERIFIED,
                    f"Bytes were sent, but part {part} did not change to {patch.name}",
                    details=data,
                    hint=" ".join(hints),
                )
                err.verification_status = status
                raise err
            if ctx.backend.is_mock:
                pass  # mocked stays mocked
            elif patch.expansion_required is None:
                status = VERIFIED
            else:
                warnings.append(
                    "The part's bank/program readback matched, but expansion presence cannot "
                    "be read back, so this is not reported as verified."
                )
    return ok_result(data, backend=ctx.backend_name, verification_status=status, warnings=warnings)


def audition(
    ctx: AppContext,
    part: int,
    *,
    patch_id: str | None = None,
    note: int = protocol.AUDITION_DEFAULT_NOTE,
    velocity: int = protocol.AUDITION_DEFAULT_VELOCITY,
    duration_ms: int = protocol.AUDITION_DEFAULT_DURATION_MS,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Play one short note on a part, optionally selecting a patch first.

    The note-off is part of the same transaction and the adapter also sends it from
    a cleanup path if anything fails after the note-on.
    """
    part = protocol.validate_part(part)
    note = protocol.validate_note(note)
    velocity = protocol.validate_velocity(velocity)
    duration_ms = protocol.validate_duration_ms(duration_ms)
    cfg = ctx.config
    dry_run = cfg.dry_run if dry_run is None else dry_run
    channel, channel_source = cfg.channel_for_part(part)

    warnings: list[str] = []
    messages: list[bytes] = []
    patch = None
    if patch_id:
        patch = patch_service.resolve_patch(ctx, patch_id=patch_id)
        if patch.kind == KIND_STUDIO_SET:
            err = Integra7Error(
                errors.WRONG_PATCH_KIND, "A Studio Set cannot be auditioned on a part"
            )
            err.verification_status = NOT_SENT
            raise err
        warnings += expansions.check_patch(ctx, patch)
        messages = protocol.bank_program_select(
            channel, patch.bank_msb, patch.bank_lsb, patch.program
        )
    on, off = protocol.note_on(channel, note, velocity), protocol.note_off(channel, note)
    if channel_source == "default_assumption":
        warnings.append(f"Part {part} -> channel {channel} is an unconfirmed default assumption.")

    data: dict[str, Any] = {
        "part": part,
        "channel": channel,
        "channel_source": channel_source,
        "patch": _patch_summary(patch) if patch else None,
        "note": note,
        "velocity": velocity,
        "duration_ms": duration_ms,
        "port": cfg.performance_port,
        "midi_messages_hex": [protocol.hex_str(m) for m in (*messages, on, off)],
        "sent": False,
        "dry_run": dry_run,
    }
    if dry_run:
        return ok_result(
            data, backend=ctx.backend_name, verification_status=NOT_SENT, warnings=warnings
        )
    steps = []
    if messages:
        steps += [send_step(cfg.performance_port, messages), sleep_step(cfg.settle_ms)]
    steps += [
        send_step(cfg.performance_port, [on]),
        sleep_step(duration_ms),
        send_step(cfg.performance_port, [off]),
    ]
    result = ctx.transact(steps)
    data["sent"] = True
    data["port"] = result["ports"].get(cfg.performance_port, cfg.performance_port)
    warnings.append("Whether the note was audible cannot be verified over MIDI.")
    return ok_result(
        data, backend=ctx.backend_name, verification_status=ctx.sent_status(), warnings=warnings
    )
