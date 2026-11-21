"""SQLite catalog: schema, import (build) and row access.

One ``patches`` row exists per distinct MIDI address. Every source line is kept in
``source_records``; differing labels for the same address become ``aliases`` and
``issues`` rather than overwriting anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import errors
from ..errors import Integra7Error
from ..models import EXPANSION_UNKNOWN, KIND_DRUM_KIT, KIND_UNKNOWN, Patch
from . import banks
from .parser import ParsedSource, SourceRecord

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,              -- 'primary' or 'comparison'
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    encoding TEXT NOT NULL,
    header_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE patches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    kind TEXT NOT NULL,
    engine TEXT,
    bank TEXT,
    category TEXT,
    alt_categories TEXT NOT NULL DEFAULT '[]',  -- JSON list from disagreeing sources
    bank_msb INTEGER NOT NULL,
    bank_lsb INTEGER NOT NULL,
    program INTEGER NOT NULL,        -- zero-based MIDI program
    display_pc INTEGER NOT NULL,     -- 1-based, as printed by Roland
    number INTEGER,
    expansion_required TEXT,         -- NULL, canonical expansion name, or 'unknown'
    in_documented_range INTEGER NOT NULL,
    source TEXT NOT NULL,
    UNIQUE (bank_msb, bank_lsb, program)
);
CREATE INDEX idx_patches_name_norm ON patches (name_norm);
CREATE INDEX idx_patches_kind ON patches (kind);
CREATE TABLE source_records (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources (id),
    line_no INTEGER NOT NULL,
    raw TEXT NOT NULL,
    level INTEGER,
    mode TEXT,
    groups_json TEXT NOT NULL,
    name TEXT NOT NULL,
    program INTEGER,
    bank_msb INTEGER,
    bank_lsb INTEGER,
    valid INTEGER NOT NULL,
    problem TEXT,
    patch_id TEXT REFERENCES patches (id)
);
CREATE INDEX idx_source_records_patch ON source_records (patch_id);
CREATE TABLE aliases (
    patch_id TEXT NOT NULL REFERENCES patches (id),
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    source_record_id INTEGER NOT NULL REFERENCES source_records (id)
);
CREATE INDEX idx_aliases_patch ON aliases (patch_id);
CREATE TABLE issues (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    patch_id TEXT,
    detail_json TEXT NOT NULL
);
CREATE INDEX idx_issues_type ON issues (type);
"""

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Casefolded ASCII-ish form: ligatures expanded, accents and punctuation dropped."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM_RE.sub(" ", stripped.casefold()).strip()


def tokens(text: str) -> list[str]:
    """Normalized tokens, also splitting CamelCase ('BrightGrand' -> bright, grand)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return normalize(_CAMEL_RE.sub(" ", decomposed)).split()


_FAMILY_RE = re.compile(
    r"^(srx|exsn|ex ?pcm|hq gm2|gm2|pcm |supernatural|studio set|template)|drum kit",
    re.IGNORECASE,
)
# Spelling fixes and Roland's abbreviated category names, mapped to one vocabulary.
_CATEGORY_FIXES = {
    "acousic piano": "Acoustic Piano",
    "beat groove": "Beat & Groove",
    "drum": "Drums",
    "ac piano": "Acoustic Piano",
    "e piano": "Electric Piano",
    "ac guitar": "Acoustic Guitar",
    "e guitar": "Electric Guitar",
    "dist guitar": "Distorted Guitar",
    "ac bass": "Acoustic Bass",
    "e bass": "Electric Bass",
    "plucked stroke": "Plucked/Stroked",
    "synth polykey": "Synth PolyKey",
    "fx": "Sound FX",
}


def derive_category(groups: Iterable[str], kind: str) -> str | None:
    """Pick the group that names a sound category rather than a bank/engine family."""
    for group in groups:
        if group and not _FAMILY_RE.search(group):
            return _CATEGORY_FIXES.get(normalize(group), group)
    return "Drums" if kind == KIND_DRUM_KIT else None


def _source_note(role: str, filename: str, in_bank: bool, in_range: bool) -> str:
    origin = f"odashi/integra7-cubase {filename}"
    if role != "primary":
        origin += " (comparison source only; absent from primary)"
    if not in_bank:
        return f"{origin}; bank not in {banks.MI_SOURCE}; unverified"
    if not in_range:
        return f"{origin}; program outside the range documented in {banks.MI_SOURCE}; unverified"
    return (
        f"{origin}; address range checked against {banks.MI_SOURCE}; "
        "name not verified against Roland Sound List"
    )


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def open_catalog(path: str | Path) -> sqlite3.Connection:
    """Open an existing catalog read-only-ish, with clear errors when it is missing."""
    p = Path(path)
    if not p.exists():
        raise Integra7Error(
            errors.CATALOG_NOT_FOUND,
            f"Patch catalog not found at {p}",
            hint="Run `integra7 patches import` once to build it from the bundled source data.",
        )
    conn = connect(p)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise Integra7Error(
            errors.CATALOG_NOT_FOUND,
            f"{p} is not a valid patch catalog ({exc})",
            hint="Rebuild it with `integra7 patches import`.",
        ) from exc
    if row is None or int(row["value"]) != SCHEMA_VERSION:
        conn.close()
        raise Integra7Error(
            errors.CATALOG_NOT_FOUND,
            f"Patch catalog at {p} has an incompatible schema version",
            hint="Rebuild it with `integra7 patches import`.",
        )
    return conn


def _issue(conn: sqlite3.Connection, type_: str, patch_id: str | None, **detail: Any) -> None:
    conn.execute(
        "INSERT INTO issues (type, patch_id, detail_json) VALUES (?, ?, ?)",
        (type_, patch_id, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
    )


def _mode_kind(mode: str | None) -> str | None:
    m = (mode or "").casefold()
    if "drum" in m:
        return KIND_DRUM_KIT
    if "studio" in m:
        return "studio_set"
    if "tone" in m:
        return "tone"
    return None


def _import_source(conn: sqlite3.Connection, parsed: ParsedSource, role: str) -> dict[str, int]:
    filename = Path(parsed.path).name
    cur = conn.execute(
        "INSERT INTO sources (role, path, filename, sha256, encoding, header_json, imported_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            role,
            parsed.path,
            filename,
            parsed.sha256,
            parsed.encoding,
            json.dumps(parsed.header, ensure_ascii=False, sort_keys=True),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    source_id = cur.lastrowid
    stats = {"records": 0, "invalid": 0, "new_patches": 0}

    for line_no, raw in parsed.unrecognized:
        _issue(conn, "unrecognized_line", None, source=filename, line=line_no, raw=raw)

    for rec in parsed.records:
        stats["records"] += 1
        pid = _import_record(conn, rec, role, filename, stats) if rec.valid else None
        if not rec.valid:
            stats["invalid"] += 1
        rec_id = conn.execute(
            "INSERT INTO source_records (source_id, line_no, raw, level, mode, groups_json, name,"
            " program, bank_msb, bank_lsb, valid, problem, patch_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                rec.line_no,
                rec.raw,
                rec.level,
                rec.mode,
                json.dumps(list(rec.groups), ensure_ascii=False),
                rec.name,
                rec.program,
                rec.msb,
                rec.lsb,
                int(rec.valid),
                rec.problem,
                pid,
            ),
        ).lastrowid
        if not rec.valid:
            _issue(
                conn,
                "malformed_record",
                None,
                source=filename,
                line=rec.line_no,
                raw=rec.raw,
                problem=rec.problem,
            )
        elif pid is not None:
            # Record every label that differs from the patch's display name as an alias.
            row = conn.execute("SELECT name FROM patches WHERE id=?", (pid,)).fetchone()
            if row["name"] != rec.name:
                conn.execute(
                    "INSERT INTO aliases (patch_id, name, name_norm, source_record_id)"
                    " VALUES (?, ?, ?, ?)",
                    (pid, rec.name, normalize(rec.name), rec_id),
                )
    return stats


def _import_record(
    conn: sqlite3.Connection, rec: SourceRecord, role: str, filename: str, stats: dict[str, int]
) -> str:
    assert rec.msb is not None and rec.lsb is not None and rec.program is not None
    msb, lsb, program = rec.msb, rec.lsb, rec.program
    pid = banks.patch_id(msb, lsb, program)
    c = banks.classify(msb, lsb, program)
    where = {"source": filename, "line": rec.line_no, "name": rec.name}

    existing = conn.execute(
        "SELECT name, name_norm, kind, category, alt_categories FROM patches WHERE id=?", (pid,)
    ).fetchone()
    if existing is not None:
        same = existing["name_norm"] == normalize(rec.name)
        category = derive_category(rec.groups, "")
        alts = json.loads(existing["alt_categories"])
        if category and existing["category"] is None:
            conn.execute("UPDATE patches SET category=? WHERE id=?", (category, pid))
        elif category and category != existing["category"] and category not in alts:
            conn.execute(
                "UPDATE patches SET alt_categories=? WHERE id=?",
                (json.dumps([*alts, category], ensure_ascii=False), pid),
            )
            _issue(
                conn,
                "category_disagreement",
                pid,
                catalog_category=existing["category"],
                other_category=category,
                **where,
            )
        if role == "primary":
            _issue(
                conn,
                "duplicate_address" if same else "conflicting_label",
                pid,
                catalog_name=existing["name"],
                **where,
            )
        elif not same:
            _issue(conn, "cross_source_name_mismatch", pid, catalog_name=existing["name"], **where)
        return pid

    kind = c.bank.kind if c.bank else KIND_UNKNOWN
    if c.bank is None:
        expansion: str | None = EXPANSION_UNKNOWN
        _issue(conn, "unknown_bank", pid, bank_msb=msb, bank_lsb=lsb, program=program, **where)
    else:
        expansion = c.bank.expansion
        if not c.in_range:
            _issue(
                conn,
                "outside_documented_range",
                pid,
                bank=c.bank.label,
                number=c.number,
                documented_total=c.bank.total,
                **where,
            )
        if c.bank.user:
            _issue(conn, "user_bank_entry", pid, bank=c.bank.label, **where)
    mode_kind = _mode_kind(rec.mode)
    if c.bank is not None and mode_kind is not None and mode_kind != kind:
        _issue(conn, "source_mode_mismatch", pid, source_mode=rec.mode, bank_kind=kind, **where)
    if role != "primary":
        _issue(conn, "missing_from_primary", pid, **where)

    conn.execute(
        "INSERT INTO patches (id, name, name_norm, kind, engine, bank, category, bank_msb,"
        " bank_lsb, program, display_pc, number, expansion_required, in_documented_range, source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pid,
            rec.name,
            normalize(rec.name),
            kind,
            c.bank.engine if c.bank else None,
            c.bank.label if c.bank else None,
            derive_category(rec.groups, kind),
            msb,
            lsb,
            program,
            program + 1,
            c.number,
            expansion,
            int(c.in_range),
            _source_note(role, filename, c.bank is not None, c.in_range),
        ),
    )
    stats["new_patches"] += 1
    return pid


def build_catalog(
    db_path: str | Path, primary: ParsedSource, comparisons: Iterable[ParsedSource] = ()
) -> dict[str, Any]:
    """(Re)build the catalog atomically: write a temp file, then replace."""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = connect(tmp)
    try:
        conn.executescript(_SCHEMA)
        conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        summary: dict[str, Any] = {"db_path": str(target), "sources": []}
        for role, parsed in [("primary", primary), *(("comparison", c) for c in comparisons)]:
            stats = _import_source(conn, parsed, role)
            summary["sources"].append(
                {"role": role, "path": parsed.path, "sha256": parsed.sha256, **stats}
            )
        summary["patch_count"] = conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]
        summary["issue_count"] = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    tmp.replace(target)
    return summary


_PATCH_COLUMNS = (
    "id, name, kind, engine, bank, category, bank_msb, bank_lsb, program, display_pc, number,"
    " expansion_required, in_documented_range, source, alt_categories"
)


def row_to_patch(row: sqlite3.Row) -> Patch:
    return Patch(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        engine=row["engine"],
        bank=row["bank"],
        category=row["category"],
        bank_msb=row["bank_msb"],
        bank_lsb=row["bank_lsb"],
        program=row["program"],
        display_pc=row["display_pc"],
        number=row["number"],
        expansion_required=row["expansion_required"],
        in_documented_range=bool(row["in_documented_range"]),
        source=row["source"],
        alt_categories=tuple(json.loads(row["alt_categories"])),
    )


def all_patches(conn: sqlite3.Connection) -> list[Patch]:
    rows = conn.execute(
        f"SELECT {_PATCH_COLUMNS} FROM patches ORDER BY bank_msb, bank_lsb, program"
    ).fetchall()
    return [row_to_patch(r) for r in rows]


def get_patch(conn: sqlite3.Connection, patch_id: str) -> Patch | None:
    row = conn.execute(
        f"SELECT {_PATCH_COLUMNS} FROM patches WHERE id = ?", (patch_id.strip().lower(),)
    ).fetchone()
    return row_to_patch(row) if row else None


def get_patch_by_address(conn: sqlite3.Connection, msb: int, lsb: int, program: int):
    row = conn.execute(
        f"SELECT {_PATCH_COLUMNS} FROM patches WHERE bank_msb=? AND bank_lsb=? AND program=?",
        (msb, lsb, program),
    ).fetchone()
    return row_to_patch(row) if row else None


def aliases_by_patch(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in conn.execute("SELECT DISTINCT patch_id, name FROM aliases ORDER BY patch_id, name"):
        out.setdefault(row["patch_id"], []).append(row["name"])
    return out


def provenance(conn: sqlite3.Connection, patch_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT s.filename, s.role, r.line_no, r.raw, r.name, r.mode, r.groups_json"
        " FROM source_records r JOIN sources s ON s.id = r.source_id"
        " WHERE r.patch_id = ? ORDER BY s.id, r.line_no",
        (patch_id,),
    ).fetchall()
    return [
        {
            "source_file": r["filename"],
            "role": r["role"],
            "line": r["line_no"],
            "original_name": r["name"],
            "mode": r["mode"],
            "groups": json.loads(r["groups_json"]),
            "raw": r["raw"],
        }
        for r in rows
    ]
