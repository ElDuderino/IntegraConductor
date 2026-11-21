"""Catalog audit: counts, duplicates, unresolved kinds and coverage versus Roland's bank table.

All totals are computed from the imported sources and the documented bank ranges;
nothing here asserts an expected overall patch count.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import banks

_MAX_LISTED = 25


def _grouped(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT COALESCE({column}, '(none)') AS k, COUNT(*) AS n FROM patches GROUP BY k"
        " ORDER BY n DESC, k"
    ).fetchall()
    return {r["k"]: r["n"] for r in rows}


def _coverage(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for bank in banks.BANKS:
        rows = conn.execute(
            "SELECT number, bank_lsb, program FROM patches"
            " WHERE bank_msb=? AND bank_lsb BETWEEN ? AND ?",
            (bank.msb, bank.lsb_first, bank.lsb_last),
        ).fetchall()
        if bank.user and not rows:
            continue  # user banks hold the owner's own data; absence is expected
        entry: dict[str, Any] = {
            "bank": bank.label,
            "bank_msb": bank.msb,
            "bank_lsb": [bank.lsb_first, bank.lsb_last],
            "documented_total": bank.total,
            "cataloged": len(rows),
            "expansion": bank.expansion,
        }
        if bank.sequential and not bank.user and bank.kind != "studio_set":
            present = {r["number"] for r in rows}
            missing = [n for n in range(1, bank.total + 1) if n not in present]
            entry["missing_numbers"] = missing[:_MAX_LISTED]
            entry["missing_count"] = len(missing)
            entry["extra_count"] = sum(1 for n in present if n is None or n > bank.total)
        entry["complete"] = (
            entry.get("missing_count", bank.total - len(rows)) == 0
            and entry.get("extra_count", 0) == 0
            if bank.kind != "studio_set"
            else None  # only factory names are listed; all 64 slots are user-writable
        )
        out.append(entry)
    return out


def audit(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = [
        {
            "role": r["role"],
            "filename": r["filename"],
            "sha256": r["sha256"],
            "encoding": r["encoding"],
            "header": json.loads(r["header_json"]),
            "imported_at": r["imported_at"],
            "records": conn.execute(
                "SELECT COUNT(*) FROM source_records WHERE source_id=?", (r["id"],)
            ).fetchone()[0],
            "invalid_records": conn.execute(
                "SELECT COUNT(*) FROM source_records WHERE source_id=? AND valid=0", (r["id"],)
            ).fetchone()[0],
        }
        for r in conn.execute("SELECT * FROM sources ORDER BY id")
    ]

    issue_counts: dict[str, int] = {}
    issue_examples: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT type, patch_id, detail_json FROM issues ORDER BY id"):
        issue_counts[row["type"]] = issue_counts.get(row["type"], 0) + 1
        examples = issue_examples.setdefault(row["type"], [])
        if len(examples) < _MAX_LISTED:
            examples.append({"patch_id": row["patch_id"], **json.loads(row["detail_json"])})

    def count(where: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM patches WHERE {where}").fetchone()[0]

    coverage = _coverage(conn)
    return {
        "sources": sources,
        "patch_count": count("1=1"),
        "by_kind": _grouped(conn, "kind"),
        "by_engine": _grouped(conn, "engine"),
        "by_expansion": _grouped(conn, "expansion_required"),
        "by_bank": _grouped(conn, "bank"),
        "unresolved_kinds": count("kind='unknown'"),
        "unknown_expansion_requirement": count("expansion_required='unknown'"),
        "missing_fields": {
            "category": count("category IS NULL"),
            "engine": count("engine IS NULL AND kind != 'studio_set'"),
            "bank": count("bank IS NULL"),
        },
        "outside_documented_range": count("in_documented_range=0"),
        "alias_count": conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0],
        "issue_counts": issue_counts,
        "issue_examples": issue_examples,
        "coverage_vs_roland_bank_table": coverage,
        "incomplete_banks": [c["bank"] for c in coverage if c["complete"] is False],
        "name_verification": (
            "Names come from the community Cubase scripts and have NOT been checked "
            "against Roland's Sound List PDF. Addresses were range-checked against the "
            "MIDI Implementation bank table."
        ),
    }
