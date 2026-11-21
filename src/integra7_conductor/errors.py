"""Structured errors with stable codes shared by the CLI, MCP server and adapter."""

from __future__ import annotations

from typing import Any

# Stable error codes. Agents may branch on these; do not rename casually.
ADAPTER_DEPENDENCY_MISSING = "ADAPTER_DEPENDENCY_MISSING"
ADAPTER_FAILED = "ADAPTER_FAILED"
ADAPTER_NOT_FOUND = "ADAPTER_NOT_FOUND"
AMBIGUOUS_PATCH = "AMBIGUOUS_PATCH"
CATALOG_NOT_FOUND = "CATALOG_NOT_FOUND"
CONFIG_INVALID = "CONFIG_INVALID"
CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
DEVICE_BUSY = "DEVICE_BUSY"
DEVICE_TIMEOUT = "DEVICE_TIMEOUT"
EXPANSION_NOT_LOADED = "EXPANSION_NOT_LOADED"
FEATURE_DISABLED = "FEATURE_DISABLED"
INTERNAL_ERROR = "INTERNAL_ERROR"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
INVALID_BANK = "INVALID_BANK"
INVALID_CHANNEL = "INVALID_CHANNEL"
INVALID_NOTE = "INVALID_NOTE"
INVALID_PART = "INVALID_PART"
INVALID_PROGRAM = "INVALID_PROGRAM"
INVALID_SYSEX = "INVALID_SYSEX"
MIDI_NOT_VERIFIED = "MIDI_NOT_VERIFIED"
MIDI_SEND_FAILED = "MIDI_SEND_FAILED"
PATCH_NOT_FOUND = "PATCH_NOT_FOUND"
PORT_AMBIGUOUS = "PORT_AMBIGUOUS"
PORT_NOT_FOUND = "PORT_NOT_FOUND"
PORT_OPEN_FAILED = "PORT_OPEN_FAILED"
SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
UNSUPPORTED = "UNSUPPORTED"
WINDOWS_INTEROP_UNAVAILABLE = "WINDOWS_INTEROP_UNAVAILABLE"
WRONG_PATCH_KIND = "WRONG_PATCH_KIND"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


class Integra7Error(Exception):
    """An expected, reportable failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        hint: str | None = None,
        exit_code: int = EXIT_FAILURE,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.hint = hint
        self.exit_code = exit_code
        # Set by services when a hardware action was attempted (see models.py).
        self.verification_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        if self.hint:
            out["hint"] = self.hint
        return out


def usage_error(code: str, message: str, **kwargs: Any) -> Integra7Error:
    return Integra7Error(code, message, exit_code=EXIT_USAGE, **kwargs)
