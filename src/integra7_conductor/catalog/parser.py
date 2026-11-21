"""Parser for Cubase patch-name scripts (the odashi/integra7-cubase files).

Record format: ``[pN, program, bank_msb, bank_lsb] Name`` where ``program`` is the
ZERO-BASED MIDI program number. ``[mode]``, ``[g1]``, ``[g2]`` lines set the
hierarchy that applies to the following records. Nothing is dropped silently:
every patch-like line becomes a SourceRecord, valid or not.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

_PATCH_RE = re.compile(
    r"^\[\s*p(?P<level>\d+)\s*,\s*(?P<program>-?\d+)\s*,\s*(?P<msb>-?\d+)\s*,"
    r"\s*(?P<lsb>-?\d+)\s*\]\s?(?P<name>.*)$",
    re.IGNORECASE,
)
_GROUP_RE = re.compile(r"^\[\s*g(?P<level>\d+)\s*\]\s*(?P<name>.*)$", re.IGNORECASE)
_MODE_RE = re.compile(r"^\[\s*mode\s*\]\s*(?P<name>.*)$", re.IGNORECASE)
_HEADER_RE = re.compile(r"^\[(?P<key>[^\]]+)\]\s*(?P<value>.*)$")
_PATCHLIKE_RE = re.compile(r"^\[\s*p\d*\s*[,\]]", re.IGNORECASE)


@dataclass(frozen=True)
class SourceRecord:
    line_no: int
    raw: str
    level: int | None
    mode: str | None
    groups: tuple[str, ...]  # (g1, g2, ...) in effect for this record
    name: str
    program: int | None  # zero-based
    msb: int | None
    lsb: int | None
    valid: bool
    problem: str | None = None


@dataclass
class ParsedSource:
    path: str
    sha256: str
    encoding: str
    header: dict[str, str] = field(default_factory=dict)
    records: list[SourceRecord] = field(default_factory=list)
    # Lines that are neither blank, header, group, mode nor patch records.
    unrecognized: list[tuple[int, str]] = field(default_factory=list)


def _decode(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252 (fallback)"


def parse_text(text: str, *, path: str = "<memory>", sha256: str = "", encoding: str = "utf-8"):
    parsed = ParsedSource(path=path, sha256=sha256, encoding=encoding)
    mode: str | None = None
    groups: dict[int, str] = {}
    in_patches = False

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        raw = raw_line.rstrip("\r\n")
        line = raw.strip()
        if not line:
            continue

        m = _PATCH_RE.match(line)
        if m:
            name = m.group("name").strip()
            program, msb, lsb = (int(m.group(k)) for k in ("program", "msb", "lsb"))
            problems = []
            if not 0 <= program <= 127:
                problems.append(f"program {program} outside 0-127")
            if not 0 <= msb <= 127:
                problems.append(f"bank MSB {msb} outside 0-127")
            if not 0 <= lsb <= 127:
                problems.append(f"bank LSB {lsb} outside 0-127")
            if not name:
                problems.append("empty name")
            parsed.records.append(
                SourceRecord(
                    line_no=line_no,
                    raw=raw,
                    level=int(m.group("level")),
                    mode=mode,
                    groups=tuple(groups[k] for k in sorted(groups)),
                    name=name,
                    program=program,
                    msb=msb,
                    lsb=lsb,
                    valid=not problems,
                    problem="; ".join(problems) or None,
                )
            )
            continue

        if _PATCHLIKE_RE.match(line):
            parsed.records.append(
                SourceRecord(
                    line_no=line_no,
                    raw=raw,
                    level=None,
                    mode=mode,
                    groups=tuple(groups[k] for k in sorted(groups)),
                    name="",
                    program=None,
                    msb=None,
                    lsb=None,
                    valid=False,
                    problem="malformed patch record",
                )
            )
            continue

        m = _MODE_RE.match(line)
        if m:
            mode = m.group("name").strip() or None
            groups = {}
            continue

        m = _GROUP_RE.match(line)
        if m:
            level = int(m.group("level"))
            groups = {k: v for k, v in groups.items() if k < level}
            groups[level] = m.group("name").strip()
            continue

        m = _HEADER_RE.match(line)
        if m:
            key = m.group("key").strip().lower()
            if key == "end":
                break
            if key == "define patchnames":
                in_patches = True
            elif not in_patches:
                parsed.header[key] = m.group("value").strip()
            else:
                parsed.unrecognized.append((line_no, raw))
            continue

        parsed.unrecognized.append((line_no, raw))

    return parsed


def parse_file(path: str | Path) -> ParsedSource:
    p = Path(path)
    data = p.read_bytes()
    text, encoding = _decode(data)
    return parse_text(
        text, path=str(p), sha256=hashlib.sha256(data).hexdigest(), encoding=encoding
    )
