"""Studio Set selection. This is NOT a part tone change: it is sent on the Studio Set
Control Channel (bank 85/0) and replaces the settings of all sixteen parts."""

from __future__ import annotations

from typing import Any

from .. import errors
from ..errors import Integra7Error, usage_error
from ..midi import protocol, sysex
from ..midi.backend import send_step, sleep_step
from ..models import KIND_STUDIO_SET, NOT_SENT, VERIFIED, ok_result
from .core import NO_REPLY_HINT, AppContext, block_from_reply


def list_studio_sets(ctx: AppContext) -> dict[str, Any]:
    sets = [p for p in ctx.patches() if p.kind == KIND_STUDIO_SET]
    return ok_result(
        {
            "studio_sets": [
                {"number": p.display_pc, "id": p.id, "factory_name": p.name} for p in sets
            ],
            "note": "Names are factory defaults from the source data. All 64 Studio Sets are "
            "user-writable, so the unit may hold different content.",
            "selectable_numbers": [1, protocol.STUDIO_SET_COUNT],
        }
    )


def select_studio_set(
    ctx: AppContext,
    number: int,
    *,
    dry_run: bool | None = None,
    confirmed: bool = False,
    verify: bool | None = None,
) -> dict[str, Any]:
    number = protocol.validate_studio_set_number(number)
    cfg = ctx.config
    dry_run = cfg.dry_run if dry_run is None else dry_run
    verify = cfg.verify if verify is None else verify

    channel = cfg.studio_set_control_channel
    if channel == 0:
        err = usage_error(
            errors.INVALID_CHANNEL,
            "studio_set_control_channel is configured as OFF (0); nothing was sent",
            hint="Set SYSTEM > Studio Set Control Channel on the unit and the same value in "
            "config: `integra7 config set studio_set_control_channel 16`.",
        )
        err.verification_status = NOT_SENT
        raise err
    program = number - 1
    messages = protocol.bank_program_select(
        channel, protocol.STUDIO_SET_BANK_MSB, protocol.STUDIO_SET_BANK_LSB, program
    )
    factory = next(
        (p.name for p in _safe_patches(ctx) if p.kind == KIND_STUDIO_SET and p.program == program),
        None,
    )
    warnings = [
        "Selecting a Studio Set replaces the tone, level and MIDI settings of all 16 parts; "
        "unsaved edits on the unit are lost."
    ]
    if cfg.origins.get("studio_set_control_channel") == "default":
        warnings.append(
            f"Studio Set Control Channel {channel} is the assumed factory default; the unit "
            "ignores this message if its setting differs (see `integra7 device state`)."
        )
    data: dict[str, Any] = {
        "studio_set_number": number,
        "program": program,
        "factory_name": factory,
        "control_channel": channel,
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
    if not confirmed:
        err = Integra7Error(
            errors.CONFIRMATION_REQUIRED,
            "Studio Set selection changes all 16 parts and needs explicit confirmation; "
            "nothing was sent",
            details=data,
            hint="Re-run with --yes (CLI) or dry_run=false after the user agrees (MCP), or use "
            "--dry-run to preview.",
        )
        err.verification_status = NOT_SENT
        raise err

    steps = [send_step(cfg.performance_port, messages)]
    if verify:
        # A Studio Set load takes longer than a tone change; allow extra settle time.
        steps += [
            sleep_step(max(cfg.settle_ms, 500)),
            ctx.rq1_step(sysex.ADDR_SETUP, sysex.SIZE_SETUP),
        ]
    result = ctx.transact(steps)
    data["sent"] = True
    data["port"] = result["ports"].get(cfg.performance_port, cfg.performance_port)
    status = ctx.sent_status()
    if verify:
        block, info = block_from_reply(ctx, result, 0, sysex.ADDR_SETUP, sysex.SIZE_SETUP)
        data["readback"] = info
        if block is None:
            warnings.append(f"Readback unavailable ({info['status']}). {NO_REPLY_HINT}")
        else:
            observed = {
                "studio_set_bs_msb": block[sysex.SETUP_STUDIO_SET_BS_MSB],
                "studio_set_bs_lsb": block[sysex.SETUP_STUDIO_SET_BS_LSB],
                "studio_set_pc": block[sysex.SETUP_STUDIO_SET_PC],
                "studio_set_number": block[sysex.SETUP_STUDIO_SET_PC] + 1,
            }
            info["observed"] = observed
            matched = observed["studio_set_pc"] == program
            info["status"] = "matched" if matched else "mismatch"
            if not matched:
                err = Integra7Error(
                    errors.MIDI_NOT_VERIFIED,
                    f"Bytes were sent, but the unit reports Studio Set "
                    f"{observed['studio_set_number']}, not {number}",
                    details=data,
                    hint="Check SYSTEM > Studio Set Control Channel on the unit matches "
                    f"studio_set_control_channel ({channel}), and Rx Program Change / "
                    "Rx Bank Select are ON.",
                )
                err.verification_status = status
                raise err
            if not ctx.backend.is_mock:
                status = VERIFIED
    return ok_result(data, backend=ctx.backend_name, verification_status=status, warnings=warnings)


def _safe_patches(ctx: AppContext):
    try:
        return ctx.patches()
    except Integra7Error:
        return []  # selecting by number works without the catalog
