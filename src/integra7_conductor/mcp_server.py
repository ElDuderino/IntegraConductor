"""stdio MCP server exposing the same service layer as the `integra7` CLI.

Start with `integra7-mcp`. Configuration comes from the usual config file and
INTEGRA7_* environment variables (for example INTEGRA7_BACKEND=mock). Every tool
returns the same envelope as the CLI's --json output: {"ok", "data" | "error",
"backend", "verification_status", "warnings"}.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from typing import Any

from . import errors
from .config import load_config
from .errors import Integra7Error
from .midi.backend import MidiBackend
from .models import error_result
from .services import device, expansions, fx, parts, patches, studio_sets
from .services.core import AppContext

INSTRUCTIONS = """Controls a Roland INTEGRA-7 sound module over MIDI.

Workflow: search_patches -> pick a patch by its `id` -> select_patch(part, patch_id).
- A patch ID (e.g. "sn-a-preset-0001") is the only accepted patch identifier. A patch
  NAME is not an ID; several patches can share one name. Always search first.
- Parts are 1-16. A part's MIDI channel comes from the configured map and may be an
  unconfirmed assumption (see get_configured_part_channels).
- Studio Sets are not part tones. select_studio_set replaces all 16 parts' settings;
  it defaults to dry_run=true. Only pass dry_run=false after the user agrees.
- verification_status: "verified" (readback matched), "sent_unverified" (bytes sent,
  not confirmed), "mocked" (no hardware), "not_sent". Never tell the user a change
  succeeded on the instrument unless the status is "verified" or they confirm by ear.
- Patches with expansion_required need that expansion loaded on the unit; this server
  cannot read or change expansion slots.
"""


def _call(fn: Callable[[AppContext], dict[str, Any]], backend: MidiBackend | None = None):
    """Run one service call with a fresh context; convert failures to error envelopes."""
    ctx: AppContext | None = None
    try:
        ctx = AppContext(load_config(), backend)
        return fn(ctx)
    except Integra7Error as exc:
        return error_result(
            exc.to_dict(),
            backend=ctx.backend_name if ctx and exc.verification_status else None,
            verification_status=exc.verification_status,
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return error_result(
            {"code": errors.INTERNAL_ERROR, "message": f"{type(exc).__name__}: {exc}"}
        )
    finally:
        if ctx is not None:
            ctx.close()


def build_server(backend: MidiBackend | None = None):
    """Create the MCP server. `backend` is injectable for tests."""
    # MCP Python SDK 2.x renamed FastMCP to MCPServer; support both major versions.
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:
        try:  # SDK 1.x
            from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef,attr-defined]
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise SystemExit(
                "The MCP server needs the optional 'mcp' dependency: "
                "pip install 'integra7-conductor[mcp]'"
            ) from exc

    server = FastMCP("integra7", instructions=INSTRUCTIONS)

    @server.tool()
    def search_patches(
        query: str = "",
        kind: str | None = None,
        engine: str | None = None,
        category: str | None = None,
        expansion: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the offline INTEGRA-7 patch catalog (no hardware needed).

        query: words from the patch name and/or category, e.g. "fretless bass".
        kind: "tone", "drum_kit" or "studio_set". engine: "SN-A", "SN-S", "SN-D",
        "PCM-S" or "PCM-D". category: substring such as "Electric Piano".
        expansion: "none" for sounds that need no expansion, "any", or a name such as
        "SRX-06", "ExSN1", "ExPCM". Results carry the patch `id` to pass to
        select_patch, plus bank_msb/bank_lsb, zero-based `program` and 1-based
        `display_pc`.
        """
        return _call(
            lambda ctx: patches.search_patches(
                ctx, query, kind=kind, engine=engine, category=category,
                expansion=expansion, limit=limit,
            ),
            backend,
        )

    @server.tool()
    def get_patch(patch_id: str) -> dict[str, Any]:
        """Get one patch by its catalog ID (e.g. "sn-a-preset-0001"), with aliases and
        source provenance. A patch name is not accepted here; use search_patches."""
        return _call(lambda ctx: patches.show_patch(ctx, patch_id), backend)

    @server.tool()
    def list_midi_ports() -> dict[str, Any]:
        """List MIDI input/output ports visible to the backend (Windows ports when
        running from WSL) and whether the configured port names resolve."""
        return _call(device.list_ports, backend)

    @server.tool()
    def get_configured_part_channels() -> dict[str, Any]:
        """Show the part -> MIDI channel map from local configuration. Entries with
        source "default_assumption" have not been confirmed against the device."""
        return _call(parts.channel_map, backend)

    @server.tool()
    def select_patch(part: int, patch_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Select a tone or drum kit on a part (1-16) by patch ID.

        Sends Bank Select MSB, LSB and Program Change on the part's channel, then tries
        a documented SysEx readback. With dry_run=true nothing is sent and the exact
        bytes are returned. Studio Set IDs are refused; use select_studio_set.
        """
        return _call(
            lambda ctx: parts.select_patch(ctx, part, patch_id=patch_id, dry_run=dry_run), backend
        )

    @server.tool()
    def select_studio_set(number: int, dry_run: bool = True) -> dict[str, Any]:
        """Recall Studio Set `number` (1-64) on the Studio Set Control Channel.

        This replaces the tone and settings of ALL 16 parts. It defaults to a dry run;
        pass dry_run=false only after the user has explicitly agreed.
        """
        return _call(
            lambda ctx: studio_sets.select_studio_set(
                ctx, number, dry_run=dry_run, confirmed=not dry_run
            ),
            backend,
        )

    @server.tool()
    def audition_patch(
        part: int,
        patch_id: str | None = None,
        note: int = 60,
        velocity: int = 90,
        duration_ms: int = 800,
    ) -> dict[str, Any]:
        """Play one short note on a part, optionally selecting patch_id first.

        note 0-127 (60 = middle C), velocity 1-127, duration_ms 1-5000. A note-off is
        always sent. Whether sound was audible cannot be verified over MIDI.
        """
        return _call(
            lambda ctx: parts.audition(
                ctx, part, patch_id=patch_id, note=note, velocity=velocity,
                duration_ms=duration_ms, dry_run=False,
            ),
            backend,
        )

    @server.tool()
    def get_device_capabilities() -> dict[str, Any]:
        """Describe what this server can and cannot do, and what each
        verification_status means."""
        return _call(device.capabilities, backend)

    @server.tool()
    def get_device_state() -> dict[str, Any]:
        """Read sound mode, current Studio Set, Studio Set Control Channel and each
        part's receive channel and tone from the unit using documented SysEx requests.
        Fails with DEVICE_TIMEOUT if the unit does not answer."""
        return _call(device.device_state, backend)

    @server.tool()
    def get_current_part_patch(part: int) -> dict[str, Any]:
        """Read one part's receive channel and current bank/program from the unit and
        map it to a catalog patch when known."""
        return _call(lambda ctx: parts.show_part(ctx, part), backend)

    @server.tool()
    def get_expansion_slots() -> dict[str, Any]:
        """Report expansion state. Device readback is unsupported, so the state is
        either "assumed" (declared by the user in config) or "unknown"; never verified."""
        return _call(expansions.status, backend)

    @server.tool()
    def list_effect_parameters() -> dict[str, Any]:
        """List the Studio Set effect parameters that can be set, with ranges and choices:
        reverb, chorus, Motional Surround room, master EQ, and per-part level, pan, sends
        and stage position."""
        return _call(lambda ctx: fx.describe(), backend)

    @server.tool()
    def get_effects(parts: list[int] | None = None) -> dict[str, Any]:
        """Read the current effect settings from the unit (optionally only some parts)."""
        return _call(lambda ctx: fx.show(ctx, parts), backend)

    @server.tool()
    def set_effects(settings: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        """Set named effect parameters and confirm them by readback.

        settings maps dotted paths to values, e.g. {"reverb.type": "room2",
        "reverb.level": 70, "part.1.reverb_send": 40, "master_eq.high_gain": -6}. Call
        list_effect_parameters for valid paths. This edits the temporary Studio Set
        (not saved on the unit). Reverb and chorus are bypassed while surround is on.
        """
        return _call(lambda ctx: fx.apply(ctx, settings, dry_run=dry_run), backend)

    return server


def main() -> None:
    build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
