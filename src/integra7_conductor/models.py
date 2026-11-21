"""Core data models and the JSON result envelope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Verification semantics (docs/PRD.md section 4, Phase 2). Never upgrade a status
# without evidence: a successful port.send() is only ever SENT_UNVERIFIED.
VERIFIED = "verified"  # a documented SysEx readback matched the desired state
SENT_UNVERIFIED = "sent_unverified"  # bytes handed to a real MIDI port; no matching readback
MOCKED = "mocked"  # mock backend only; no hardware involved
NOT_SENT = "not_sent"  # dry run, refusal, or failure before transmission

KIND_TONE = "tone"
KIND_DRUM_KIT = "drum_kit"
KIND_STUDIO_SET = "studio_set"
KIND_UNKNOWN = "unknown"
KINDS = (KIND_TONE, KIND_DRUM_KIT, KIND_STUDIO_SET, KIND_UNKNOWN)

EXPANSION_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Patch:
    """A normalized catalog entry addressed by bank select + program change."""

    id: str
    name: str
    kind: str
    engine: str | None
    bank: str | None
    category: str | None
    bank_msb: int
    bank_lsb: int
    program: int  # zero-based, as sent in a MIDI Program Change
    display_pc: int  # 1-based, as printed by Roland
    number: int | None  # Roland's sequential number within the bank group
    expansion_required: str | None  # None, "SRX-06", "ExSN1", "ExPCM" or "unknown"
    in_documented_range: bool
    source: str
    # Categories other source records assign to the same address (sources disagree).
    alt_categories: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["alt_categories"] = list(self.alt_categories)
        return out

    def address(self) -> tuple[int, int, int]:
        return (self.bank_msb, self.bank_lsb, self.program)


def ok_result(
    data: Any,
    *,
    backend: str | None = None,
    verification_status: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True}
    if backend is not None:
        out["backend"] = backend
    if verification_status is not None:
        out["verification_status"] = verification_status
    out["data"] = data
    if warnings:
        out["warnings"] = warnings
    return out


def error_result(
    error: dict[str, Any],
    *,
    backend: str | None = None,
    verification_status: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False}
    if backend is not None:
        out["backend"] = backend
    if verification_status is not None:
        out["verification_status"] = verification_status
    out["error"] = error
    return out
