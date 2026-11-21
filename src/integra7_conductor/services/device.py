"""Device-level services: ports, identity, state readback, capabilities, doctor."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .. import __version__, errors
from ..catalog import database
from ..config import is_wsl, update_config_file
from ..errors import Integra7Error
from ..midi import protocol, sysex, windows_adapter, wsl_interop
from ..midi.backend import BACKEND_WINDOWS, request_step
from ..models import ok_result
from . import parts as part_service
from .core import NO_REPLY_HINT, AppContext, read_blocks


def list_ports(ctx: AppContext) -> dict[str, Any]:
    ports = ctx.backend.list_ports()
    cfg = ctx.config
    configured = {}
    for key, name, direction in (
        ("performance_port", cfg.performance_port, "outputs"),
        ("control_port", cfg.control_port, "outputs"),
        ("input_port", cfg.input_port, "inputs"),
    ):
        try:
            resolved = windows_adapter.resolve_port(name, ports[direction], direction[:-1])
            configured[key] = {"configured": name, "resolved": resolved, "found": True}
        except windows_adapter.AdapterError as exc:
            configured[key] = {
                "configured": name,
                "resolved": None,
                "found": False,
                "error": exc.code,
                "candidates": exc.details.get("candidates"),
            }
    warnings = []
    if ctx.backend.is_mock:
        warnings.append("These are simulated ports from the mock backend, not real devices.")
    elif not configured["performance_port"]["found"]:
        warnings.append(
            "The configured performance port was not found. Is the INTEGRA-7 connected, "
            "powered, and using the Roland driver (USB Driver = VENDER)?"
        )
    return ok_result(
        {"inputs": ports["inputs"], "outputs": ports["outputs"], "configured": configured},
        backend=ctx.backend_name,
        warnings=warnings,
    )


def identify(ctx: AppContext) -> dict[str, Any]:
    """Send a Universal Identity Request and report the reply, if any."""
    step = request_step(
        ctx.sysex_out_port(),
        sysex.build_identity_request(sysex.BROADCAST_DEVICE_ID),
        ctx.config.readback_timeout_ms,
    )
    result = ctx.transact([step])
    entry = result["replies"][0]
    if entry.get("skipped"):
        input_error = (result.get("input") or {}).get("error") or {}
        raise Integra7Error(
            input_error.get("code", errors.PORT_NOT_FOUND),
            f"Cannot listen for a reply: {input_error.get('message', entry['skipped'])}",
            details=input_error.get("details"),
            hint=input_error.get("hint"),
        )
    for raw in entry["messages"]:
        reply = sysex.parse_identity_reply(raw)
        if reply is not None:
            return ok_result(
                {
                    "source": "mock_device" if ctx.backend.is_mock else "device_reply",
                    "is_integra7": reply.is_integra7,
                    "device_id": reply.device_id,
                    "device_id_displayed": reply.device_id + 1,
                    "device_id_matches_config": reply.device_id == ctx.config.device_id,
                    "manufacturer_id": reply.manufacturer,
                    "family_code_hex": protocol.hex_str(reply.family_code),
                    "family_number_hex": protocol.hex_str(reply.family_number),
                    "software_revision_hex": protocol.hex_str(reply.software_revision),
                    "raw_hex": protocol.hex_str(raw),
                    "ports": result["ports"],
                    "input_port": result["input"]["resolved"],
                },
                backend=ctx.backend_name,
            )
    raise Integra7Error(
        errors.DEVICE_TIMEOUT, "No Identity Reply received", hint=NO_REPLY_HINT
    )


def device_state(ctx: AppContext, include_parts: bool = True) -> dict[str, Any]:
    """Read Setup, System Common and (optionally) all 16 Studio Set Part blocks."""
    setup, system = read_blocks(
        ctx,
        [
            (sysex.ADDR_SETUP, sysex.SIZE_SETUP),
            (sysex.ADDR_SYSTEM_COMMON, sysex.SIZE_SYSTEM_COMMON),
        ],
    )
    raw_control = system[sysex.SYSTEM_STUDIO_SET_CONTROL_CHANNEL]
    control_channel = raw_control + 1 if raw_control < 16 else None
    data: dict[str, Any] = {
        "source": "mock_device" if ctx.backend.is_mock else "device_readback",
        "sound_mode": sysex.SOUND_MODES.get(setup[sysex.SETUP_SOUND_MODE], "unknown"),
        "studio_set": {
            "number": setup[sysex.SETUP_STUDIO_SET_PC] + 1,
            "bank_msb": setup[sysex.SETUP_STUDIO_SET_BS_MSB],
            "bank_lsb": setup[sysex.SETUP_STUDIO_SET_BS_LSB],
            "program": setup[sysex.SETUP_STUDIO_SET_PC],
        },
        "studio_set_control_channel": control_channel if control_channel else "OFF",
        "studio_set_control_channel_matches_config": (
            (control_channel or 0) == ctx.config.studio_set_control_channel
        ),
        "rx_program_change": bool(system[sysex.SYSTEM_RX_PROGRAM_CHANGE]),
        "rx_bank_select": bool(system[sysex.SYSTEM_RX_BANK_SELECT]),
        "expansions": "unsupported (no documented address; see `integra7 expansions status`)",
    }
    warnings = []
    if not data["studio_set_control_channel_matches_config"]:
        warnings.append(
            "The unit's Studio Set Control Channel differs from config "
            f"({ctx.config.studio_set_control_channel}); studio-set select would be ignored."
        )
    if not (data["rx_program_change"] and data["rx_bank_select"]):
        warnings.append("System Rx Program Change / Rx Bank Select is OFF; selection will fail.")
    if include_parts:
        data["parts"] = part_service.read_parts(ctx)
        mismatched = [
            p["part"]
            for p in data["parts"]
            if p["receive_channel"] != ctx.config.channel_for_part(p["part"])[0]
        ]
        if mismatched:
            warnings.append(
                f"Parts {mismatched} receive on channels that differ from the configured map. "
                "Run `integra7 part channels --from-device --save`."
            )
    return ok_result(data, backend=ctx.backend_name, warnings=warnings)


def capabilities(ctx: AppContext) -> dict[str, Any]:
    cfg = ctx.config
    return ok_result(
        {
            "version": __version__,
            "backend": cfg.backend,
            "supported": {
                "patch_search": True,
                "select_part_patch": True,
                "select_studio_set": True,
                "audition": True,
                "readback_part_state": "documented RQ1 (Studio Set Part block)",
                "readback_device_state": "documented RQ1 (Setup, System Common)",
                "identity_request": True,
                "expansion_readback": False,
                "expansion_switching": False,
                "raw_sysex": False,
                "effects": "named Studio Set effect parameters via documented DT1, "
                "confirmed by readback (reverb, chorus, surround room, master EQ, part mix)",
                "play_score": True,
                "tone_parameter_editing": False,
            },
            "verification_statuses": {
                "verified": "a documented SysEx readback matched the requested state",
                "sent_unverified": "bytes were handed to a real MIDI port; no matching readback",
                "mocked": "mock backend; no hardware involved",
                "not_sent": "dry run, refusal, or failure before transmission",
            },
            "limits": {
                "parts": [1, 16],
                "channels": [1, 16],
                "studio_sets": [1, protocol.STUDIO_SET_COUNT],
                "audition_max_duration_ms": protocol.AUDITION_MAX_DURATION_MS,
            },
            "hardware_verified": False,
            "hardware_note": "No behavior has been verified on a physical INTEGRA-7 by this "
            "project's test suite. See README testing status.",
            "expansions": {
                "state": "assumed" if cfg.expansions_declared else "unknown",
                "policy": cfg.expansion_policy,
            },
        },
        backend=ctx.backend_name,
    )


def _check(name: str, status: str, detail: str, hint: str | None = None, **extra: Any):
    out = {"name": name, "status": status, "detail": detail}
    if hint:
        out["hint"] = hint
    out.update(extra)
    return out


def doctor(ctx: AppContext, write_config: bool = False) -> dict[str, Any]:
    """Diagnose the environment end to end without sending anything to the synth."""
    cfg = ctx.config
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "environment",
            "ok",
            f"python {sys.version.split()[0]} on {sys.platform}"
            + (" (WSL)" if is_wsl() else "")
            + f"; backend={cfg.backend}; config={cfg.path}"
            + ("" if Path(cfg.path).exists() else " (not created yet; defaults in use)"),
        )
    )

    db_path = cfg.resolved_db_path()
    try:
        conn = database.open_catalog(db_path)
        count = conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]
        conn.close()
        checks.append(_check("catalog", "ok", f"{count} patches in {db_path}"))
        catalog_ok = True
    except Integra7Error as exc:
        checks.append(_check("catalog", "fail", exc.message, exc.hint))
        catalog_ok = False

    adapter_ok = True
    discovered = None
    if cfg.backend == BACKEND_WINDOWS:
        interop = wsl_interop.interop_status()
        if not is_wsl():
            checks.append(
                _check("wsl_interop", "fail", "Not running inside WSL",
                       "Use --backend native on Windows, or --backend mock for offline work.")
            )
            adapter_ok = False
        elif not interop["enabled"]:
            checks.append(
                _check("wsl_interop", "fail", "Windows executable interop is disabled",
                       wsl_interop._INTEROP_HINT, code=errors.WINDOWS_INTEROP_UNAVAILABLE)
            )
            adapter_ok = False
        else:
            checks.append(_check("wsl_interop", "ok", f"enabled ({interop['source']})"))
        if adapter_ok and not (cfg.windows_python or cfg.windows_adapter):
            discovered = wsl_interop.discover_windows_python()
            if discovered:
                win = wsl_interop.to_windows_path(discovered)
                saved = False
                if write_config:
                    update_config_file(cfg.path, {"windows_python": win})
                    saved = True
                checks.append(
                    _check(
                        "windows_python",
                        "ok" if saved else "warn",
                        f"discovered {win}" + (" (saved to config)" if saved else ""),
                        None if saved else "Discovery runs on every call. Save it with "
                        "`integra7 doctor --write-config`.",
                    )
                )
    if adapter_ok:
        try:
            info = ctx.backend.call({"op": "ping"})
            checks.append(
                _check(
                    "midi_adapter",
                    "ok",
                    f"python {info.get('python')}, MIDI API: {info.get('midi_api')}"
                    + (
                        f" (mido {info.get('mido')}, python-rtmidi {info.get('python_rtmidi')})"
                        if info.get("mido")
                        else ""
                    ),
                    executable=info.get("executable"),
                )
            )
        except Integra7Error as exc:
            checks.append(_check("midi_adapter", "fail", exc.message, exc.hint, code=exc.code))
            adapter_ok = False

    ports_ok = False
    if adapter_ok:
        try:
            ports = list_ports(ctx)["data"]
            missing = [k for k, v in ports["configured"].items() if not v["found"]]
            required_missing = [k for k in missing if k != "control_port"]
            ports_ok = not required_missing
            checks.append(
                _check(
                    "midi_ports",
                    "ok" if not missing else ("warn" if ports_ok else "fail"),
                    "all configured ports found"
                    if not missing
                    else f"not found: {', '.join(missing)}",
                    None
                    if not missing
                    else "Connect and power the INTEGRA-7, install the Roland USB driver, set "
                    "USB Driver = VENDER on the unit, then compare names with `integra7 ports`.",
                    inputs=ports["inputs"],
                    outputs=ports["outputs"],
                    configured=ports["configured"],
                )
            )
        except Integra7Error as exc:
            checks.append(_check("midi_ports", "fail", exc.message, exc.hint, code=exc.code))

    assumed = [p for p in range(1, 17) if p not in cfg.part_channels]
    checks.append(
        _check(
            "part_channels",
            "warn" if assumed else "ok",
            f"{16 - len(assumed)} parts explicitly mapped; {len(assumed)} assume part N = "
            "channel N",
            part_service.ASSUMPTION_NOTE if assumed else None,
        )
    )
    mock = cfg.backend == "mock"
    return ok_result(
        {
            "checks": checks,
            "ready_for_offline_use": catalog_ok,
            "ready_for_hardware": bool(adapter_ok and ports_ok and not mock),
            "note": "The mock backend never reaches hardware."
            if mock
            else "Doctor sends nothing to the synth; it does not prove the unit responds. "
            "Use `integra7 device identify` for that.",
        },
        backend=cfg.backend,
    )
