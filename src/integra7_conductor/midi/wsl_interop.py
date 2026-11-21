"""WSL -> Windows process interop: launch the Windows MIDI adapter as a child process.

The adapter is always started with an argument *array* (never a shell string) and
receives its request as JSON on stdin, so patch names, quotes and paths with
spaces cannot be misparsed. Paths are translated with ``wslpath``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .. import errors
from ..errors import Integra7Error
from . import windows_adapter
from .backend import BACKEND_WINDOWS, MidiBackend, hardware_lock, lock_is_held, unwrap

_WINDOWS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_INTEROP_FILES = (
    "/proc/sys/fs/binfmt_misc/WSLInterop",
    "/proc/sys/fs/binfmt_misc/WSLInterop-late",
)
VENV_RELATIVE = ("integra7-conductor", "venv", "Scripts", "python.exe")
_INTEROP_HINT = (
    "Windows executable interop must be enabled in WSL. Check [interop] enabled=true in "
    "/etc/wsl.conf, then run `wsl.exe --shutdown` from Windows and reopen the distro."
)


def interop_status() -> dict[str, Any]:
    """Report whether WSL can launch Windows executables, without launching one."""
    for name in _INTEROP_FILES:
        try:
            first = Path(name).read_text().splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        return {"registered": True, "enabled": first == "enabled", "source": name}
    return {"registered": False, "enabled": False, "source": None}


def is_windows_path(path: str) -> bool:
    return bool(_WINDOWS_PATH_RE.match(path))


def wslpath(flag: str, path: str) -> str:
    """Translate a path with wslpath (-w to Windows, -u to WSL)."""
    try:
        proc = subprocess.run(
            ["wslpath", flag, path], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Integra7Error(
            errors.WINDOWS_INTEROP_UNAVAILABLE,
            f"Cannot run wslpath to translate {path!r}: {exc}",
            hint="This backend only works inside WSL. Use --backend mock or native elsewhere.",
        ) from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        raise Integra7Error(
            errors.WINDOWS_INTEROP_UNAVAILABLE,
            f"wslpath could not translate {path!r}: {proc.stderr.strip() or 'no output'}",
            details={"path": path, "direction": flag},
        )
    return proc.stdout.strip()


def to_wsl_path(path: str) -> str:
    return wslpath("-u", path) if is_windows_path(path) else path


def to_windows_path(path: str) -> str:
    return path if is_windows_path(path) else wslpath("-w", path)


def adapter_script_path() -> Path:
    return Path(windows_adapter.__file__).resolve()


def build_command(python_exe: str, adapter_script_windows: str | None) -> list[str]:
    """Argument array for the adapter. A packaged .exe takes no script argument."""
    if adapter_script_windows is None:
        return [python_exe]
    return [python_exe, "-X", "utf8", adapter_script_windows]


def discover_windows_python() -> str | None:
    """Find the venv created by scripts/setup-windows.ps1 (WSL path), if present."""
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", "echo %LOCALAPPDATA%"],  # fixed string; no user input
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd="/mnt/c" if Path("/mnt/c").is_dir() else None,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    local = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    if not is_windows_path(local):
        return None
    try:
        candidate = Path(wslpath("-u", local)).joinpath(*VENV_RELATIVE)
    except Integra7Error:
        return None
    return str(candidate) if candidate.exists() else None


class WindowsBackend(MidiBackend):
    """Runs each atomic hardware operation as one Windows adapter process."""

    name = BACKEND_WINDOWS

    def __init__(
        self,
        *,
        windows_python: str = "",
        windows_adapter_exe: str = "",
        timeout_s: float = 15.0,
        lock_path: Path | None = None,
        lock_timeout_s: float = 10.0,
    ) -> None:
        self._python = windows_python
        self._adapter_exe = windows_adapter_exe
        self._timeout_s = timeout_s
        self._lock_path = lock_path
        self._lock_timeout_s = lock_timeout_s
        self._command: list[str] | None = None

    def command(self) -> list[str]:
        if self._command is not None:
            return self._command
        if self._adapter_exe:
            exe = to_wsl_path(self._adapter_exe)
            script = None
        else:
            exe = to_wsl_path(self._python) if self._python else (discover_windows_python() or "")
            if not exe:
                raise Integra7Error(
                    errors.ADAPTER_NOT_FOUND,
                    "No Windows Python configured and the default adapter venv was not found",
                    hint="Run scripts/setup-windows.ps1 on Windows, then "
                    "`integra7 doctor --write-config` (or `integra7 config set windows_python "
                    "'C:\\path\\to\\python.exe'`).",
                )
            script = to_windows_path(str(adapter_script_path()))
        if not Path(exe).exists():
            raise Integra7Error(
                errors.ADAPTER_NOT_FOUND,
                f"Windows adapter executable not found: {exe}",
                details={"path": exe},
                hint="Run scripts/setup-windows.ps1, or fix windows_python / windows_adapter.",
            )
        self._command = build_command(exe, script)
        return self._command

    def adapter_path(self, path: Path) -> str:
        return to_windows_path(str(path))

    def is_busy(self) -> bool:
        return self._lock_path is not None and lock_is_held(self._lock_path)

    def _budget_s(self, request: dict[str, Any]) -> float:
        extra_ms = 0
        for step in request.get("steps", []):
            extra_ms += int(step.get("ms", 0)) + int(step.get("timeout_ms", 0))
            extra_ms += int(max((e.get("t_ms", 0) for e in step.get("events", [])), default=0))
        return self._timeout_s + extra_ms / 1000.0

    def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = self.command()
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        try:
            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                timeout=self._budget_s(request),
                check=False,
                # A Windows-visible working directory avoids UNC cwd problems.
                cwd=str(Path(cmd[0]).parent),
            )
        except subprocess.TimeoutExpired as exc:
            raise Integra7Error(
                errors.DEVICE_TIMEOUT,
                f"Windows MIDI adapter did not finish within {exc.timeout:g}s",
                details={"command": cmd},
                hint="The MIDI driver may be hung or the port busy. Whether any bytes were "
                "sent is unknown.",
            ) from exc
        except OSError as exc:
            status = interop_status()
            if not status["enabled"]:
                raise Integra7Error(
                    errors.WINDOWS_INTEROP_UNAVAILABLE,
                    f"Cannot launch Windows executables from WSL: {exc}",
                    details={"interop": status, "command": cmd},
                    hint=_INTEROP_HINT,
                ) from exc
            raise Integra7Error(
                errors.ADAPTER_NOT_FOUND,
                f"Cannot launch the Windows adapter: {exc}",
                details={"command": cmd},
            ) from exc

        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        try:
            response = json.loads(lines[-1]) if lines else None
        except json.JSONDecodeError:
            response = None
        if not isinstance(response, dict):
            raise Integra7Error(
                errors.ADAPTER_FAILED,
                f"Windows adapter returned no JSON (exit status {proc.returncode})",
                details={"command": cmd, "stdout": stdout[-500:], "stderr": stderr[-1000:]},
                hint="Run `integra7 doctor` to check the Windows Python environment.",
            )
        return response

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("op") != "transact" or self._lock_path is None:
            return unwrap(self._run(request))
        with hardware_lock(self._lock_path, self._lock_timeout_s):
            return unwrap(self._run(request))
