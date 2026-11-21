"""Configuration: defaults < config file (TOML) < INTEGRA7_* environment < CLI flags."""

from __future__ import annotations

import os
import platform
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import errors
from .errors import Integra7Error, usage_error

APP_NAME = "integra7-conductor"
ENV_PREFIX = "INTEGRA7_"

EXPANSION_POLICIES = ("warn", "refuse", "ignore")
SYSEX_PORTS = ("performance", "control")


def is_wsl() -> bool:
    return sys.platform.startswith("linux") and (
        "microsoft" in platform.release().lower() or bool(os.environ.get("WSL_DISTRO_NAME"))
    )


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def default_config_path() -> Path:
    return Path(os.environ.get(ENV_PREFIX + "CONFIG") or config_dir() / "config.toml")


def default_backend() -> str:
    if is_wsl():
        return "windows"
    return "native"


@dataclass
class Config:
    # Which MIDI backend to use: "windows" (WSL -> Windows adapter), "native", or "mock".
    backend: str = field(default_factory=default_backend)
    # Port names as shown by `integra7 ports`. A trailing RtMidi index is optional.
    performance_port: str = "INTEGRA-7"
    control_port: str = "INTEGRA-7 CTRL"
    input_port: str = "INTEGRA-7"
    # Which output carries RQ1 SysEx: "performance" or "control". Unverified on hardware.
    sysex_port: str = "performance"
    # Roland SysEx device ID as sent on the wire (0x10 = 16 is shown as 17 on the unit).
    device_id: int = 0x10
    # Roland's factory default is 16; set 0 if the unit has it OFF.
    studio_set_control_channel: int = 16
    # Explicit part -> MIDI receive channel overrides. Unlisted parts ASSUME part N = channel N.
    part_channels: dict[int, int] = field(default_factory=dict)
    # Windows Python interpreter (Windows or /mnt path) that has mido + python-rtmidi.
    windows_python: str = ""
    # Optional packaged adapter .exe; when set it is run instead of windows_python + script.
    windows_adapter: str = ""
    adapter_timeout_s: float = 15.0
    lock_timeout_s: float = 10.0
    readback_timeout_ms: int = 800
    settle_ms: int = 150
    # Attempt documented SysEx readback after a change.
    verify: bool = True
    dry_run: bool = False
    # What to do when a patch needs an expansion not known to be loaded.
    expansion_policy: str = "warn"
    # Whether loaded_expansions reflects what the user says is loaded (an assumption,
    # never device-verified). False means the expansion state is unknown.
    expansions_declared: bool = False
    loaded_expansions: list[str] = field(default_factory=list)
    db_path: str = ""

    # Not persisted: where each value came from, for `integra7 config show`.
    origins: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    path: str = field(default="", repr=False, compare=False)

    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser() if self.db_path else data_dir() / "patches.db"

    def lock_path(self) -> Path:
        return data_dir() / "hardware.lock"

    def live_path(self) -> Path:
        """File through which other commands reach a running `integra7 play`."""
        return data_dir() / "live-playback.jsonl"

    def channel_for_part(self, part: int) -> tuple[int, str]:
        """Return (channel, source) where source is 'configured' or 'default_assumption'."""
        if part in self.part_channels:
            return self.part_channels[part], "configured"
        return part, "default_assumption"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            if f.name in ("origins", "path"):
                continue
            value = getattr(self, f.name)
            if f.name == "part_channels":
                value = {str(k): v for k, v in sorted(value.items())}
            out[f.name] = value
        return out


_FIELD_TYPES = {f.name: f.type for f in fields(Config) if f.name not in ("origins", "path")}
SETTABLE_KEYS = tuple(k for k in _FIELD_TYPES if k != "part_channels")


def _coerce(key: str, value: Any) -> Any:
    kind = _FIELD_TYPES[key]
    try:
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if str(value).strip().lower() in ("1", "true", "yes", "on"):
                return True
            if str(value).strip().lower() in ("0", "false", "no", "off"):
                return False
            raise ValueError("expected a boolean")
        if kind == "int":
            if isinstance(value, bool):
                raise ValueError("expected an integer")
            return value if isinstance(value, int) else int(str(value).strip(), 0)
        if kind == "float":
            return float(value)
        if kind == "list[str]":
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return [str(v) for v in value]
        if kind == "dict[int, int]":
            return {int(k): int(v) for k, v in dict(value).items()}
        return str(value)
    except (TypeError, ValueError) as exc:
        raise usage_error(
            errors.CONFIG_INVALID, f"Invalid value for {key}: {value!r} ({exc})"
        ) from exc


def validate(cfg: Config) -> None:
    from .catalog.banks import normalize_expansion_name
    from .midi import backend as midi_backend
    from .midi import protocol, sysex

    def bad(message: str) -> Integra7Error:
        return usage_error(errors.CONFIG_INVALID, message)

    if cfg.backend not in midi_backend.BACKENDS:
        raise bad(f"backend must be one of {', '.join(midi_backend.BACKENDS)}; got {cfg.backend!r}")
    if cfg.sysex_port not in SYSEX_PORTS:
        raise bad(f"sysex_port must be one of {', '.join(SYSEX_PORTS)}")
    if cfg.expansion_policy not in EXPANSION_POLICIES:
        raise bad(f"expansion_policy must be one of {', '.join(EXPANSION_POLICIES)}")
    sysex.validate_device_id(cfg.device_id)
    if not 0 <= cfg.studio_set_control_channel <= 16:
        raise bad("studio_set_control_channel must be 1-16, or 0 for OFF")
    for part, channel in cfg.part_channels.items():
        protocol.validate_part(part)
        protocol.validate_channel(channel)
    canonical = []
    for name in cfg.loaded_expansions:
        c = normalize_expansion_name(name)
        if c is None:
            raise bad(f"Unknown expansion name in loaded_expansions: {name!r}")
        canonical.append(c)
    cfg.loaded_expansions = canonical
    if cfg.adapter_timeout_s <= 0 or cfg.lock_timeout_s < 0:
        raise bad("timeouts must be positive")
    if not 50 <= cfg.readback_timeout_ms <= 5000 or not 0 <= cfg.settle_ms <= 2000:
        raise bad("readback_timeout_ms must be 50-5000 and settle_ms 0-2000")


def load_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise usage_error(errors.CONFIG_INVALID, f"Cannot read config {path}: {exc}") from exc


def load_config(
    path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    env = os.environ if env is None else env
    cfg_path = Path(path) if path else Path(
        env.get(ENV_PREFIX + "CONFIG") or config_dir() / "config.toml"
    )
    cfg = Config()
    cfg.path = str(cfg_path)
    cfg.origins = {k: "default" for k in _FIELD_TYPES}

    for key, value in load_file(cfg_path).items():
        if key not in _FIELD_TYPES:
            raise usage_error(errors.CONFIG_INVALID, f"Unknown key {key!r} in {cfg_path}")
        setattr(cfg, key, _coerce(key, value))
        cfg.origins[key] = "config_file"
    for key in SETTABLE_KEYS:
        raw = env.get(ENV_PREFIX + key.upper())
        if raw is not None and raw != "":
            setattr(cfg, key, _coerce(key, raw))
            cfg.origins[key] = "environment"
    for key, value in (overrides or {}).items():
        if value is not None:
            setattr(cfg, key, _coerce(key, value))
            cfg.origins[key] = "cli"
    validate(cfg)
    return cfg


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_toml(values: dict[str, Any]) -> str:
    lines = ["# integra7-conductor configuration. See README.md for every key."]
    tables = {k: v for k, v in values.items() if isinstance(v, dict)}
    for key, value in values.items():
        if key not in tables:
            lines.append(f"{key} = {_toml_value(value)}")
    for key, table in tables.items():
        lines += ["", f"[{key}]"]
        rows = sorted(table.items(), key=lambda item: int(item[0]))
        lines += [f"{k} = {_toml_value(v)}" for k, v in rows]
    return "\n".join(lines) + "\n"


def update_config_file(path: str | Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Merge changes into the config file (only explicitly set keys are persisted)."""
    p = Path(path)
    current = load_file(p)
    for key, value in changes.items():
        if key not in _FIELD_TYPES:
            raise usage_error(
                errors.CONFIG_INVALID,
                f"Unknown config key {key!r}",
                details={"valid_keys": list(_FIELD_TYPES)},
            )
        coerced = _coerce(key, value)
        if key == "part_channels":
            coerced = {str(k): v for k, v in coerced.items()}
        current[key] = coerced
    # Validate the merged result before writing anything.
    probe = Config()
    for key, value in current.items():
        setattr(probe, key, _coerce(key, value))
    validate(probe)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(dump_toml(current), encoding="utf-8")
    tmp.replace(p)
    return current
