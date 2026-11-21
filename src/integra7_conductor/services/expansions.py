"""Expansion state and policy.

The published MIDI Implementation documents no address for reading or loading
the four virtual expansion slots, so the loaded set is never device-verified
here: it is either declared by the user in config (reported as ``assumed``) or
``unknown``. Slot switching over SysEx is intentionally not implemented; see
docs/experimental-expansions.md.
"""

from __future__ import annotations

from typing import Any

from .. import errors
from ..catalog import banks
from ..errors import Integra7Error, usage_error
from ..models import EXPANSION_UNKNOWN, NOT_SENT, Patch, ok_result
from .core import AppContext


def status(ctx: AppContext) -> dict[str, Any]:
    cfg = ctx.config
    return ok_result(
        {
            "state": "assumed" if cfg.expansions_declared else "unknown",
            "loaded_expansions": list(cfg.loaded_expansions) if cfg.expansions_declared else None,
            "source": "user configuration (not read from the device)"
            if cfg.expansions_declared
            else None,
            "device_readback": "unsupported",
            "reason": "Roland's published MIDI Implementation defines no address for the "
            "expansion slots, so they cannot be read back with documented SysEx.",
            "slot_count": banks.SLOT_COUNT,
            "expansion_policy": cfg.expansion_policy,
            "switching": "not_implemented (undocumented SysEx; see "
            "docs/experimental-expansions.md)",
        }
    )


def plan(names: list[str]) -> dict[str, Any]:
    """Check whether a set of expansions can be loaded together (4 slots; ExPCM uses all)."""
    canonical: list[str] = []
    for name in names:
        c = banks.normalize_expansion_name(name)
        if c is None:
            raise usage_error(
                errors.INVALID_ARGUMENT,
                f"Unknown expansion {name!r}",
                details={"valid": list(banks.EXPANSION_NAMES)},
            )
        if c not in canonical:
            canonical.append(c)
    problems = []
    if banks.ALL_SLOT_EXPANSION in canonical and len(canonical) > 1:
        problems.append("ExPCM occupies all four slots and cannot be combined with others")
    singles = [c for c in canonical if c != banks.ALL_SLOT_EXPANSION]
    if len(singles) > banks.SLOT_COUNT:
        problems.append(
            f"{len(singles)} single-slot expansions exceed the {banks.SLOT_COUNT} slots"
        )
    return {"expansions": canonical, "compatible": not problems, "problems": problems}


def declare(ctx: AppContext, names: list[str], unknown: bool = False) -> dict[str, Any]:
    """Record what the user says is loaded. This is an assumption, never a verification."""
    from ..config import update_config_file

    if unknown:
        update_config_file(ctx.config.path, {"expansions_declared": False, "loaded_expansions": []})
        return ok_result({"state": "unknown", "loaded_expansions": None})
    p = plan(names)
    if not p["compatible"]:
        raise usage_error(
            errors.INVALID_ARGUMENT,
            "That combination cannot be loaded at once: " + "; ".join(p["problems"]),
        )
    update_config_file(
        ctx.config.path, {"expansions_declared": True, "loaded_expansions": p["expansions"]}
    )
    return ok_result({"state": "assumed", "loaded_expansions": p["expansions"]})


def check_patch(ctx: AppContext, patch: Patch) -> list[str]:
    """Apply the expansion policy. Returns warnings, or raises under policy 'refuse'."""
    required = patch.expansion_required
    cfg = ctx.config
    if required is None or cfg.expansion_policy == "ignore":
        return []
    if required == EXPANSION_UNKNOWN:
        problem = (
            f"{patch.id} is in a bank not found in Roland's bank table; its expansion "
            "requirement is unknown"
        )
    elif cfg.expansions_declared and required in cfg.loaded_expansions:
        return [
            f"{patch.name} requires {required}. Config declares it loaded (an assumption, "
            "not read from the device)."
        ]
    elif cfg.expansions_declared:
        problem = f"{patch.name} requires {required}, which is not in the declared loaded set"
    else:
        problem = (
            f"{patch.name} requires {required}; whether it is loaded is unknown "
            "(expansion slots cannot be read back)"
        )
    if cfg.expansion_policy == "refuse":
        err = Integra7Error(
            errors.EXPANSION_NOT_LOADED,
            problem + "; nothing was sent",
            details={
                "expansion_required": required,
                "declared_loaded": cfg.loaded_expansions if cfg.expansions_declared else None,
            },
            hint="Load the expansion on the unit, then record it with `integra7 expansions "
            "declare ...`, or set expansion_policy to 'warn'.",
        )
        err.verification_status = NOT_SENT
        raise err
    return [problem + ". The unit will not sound this tone unless the expansion is loaded."]
