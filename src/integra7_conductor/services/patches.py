"""Patch catalog services: import, search, show, audit, export, resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import errors
from ..catalog import audit as audit_mod
from ..catalog import database, parser, search
from ..errors import Integra7Error, usage_error
from ..models import KINDS, Patch, ok_result
from .core import AppContext

PRIMARY_SOURCE = "roland-integra-7-full.txt"
COMPARISON_SOURCE = "roland-integra-7.txt"


def bundled_sources_dir() -> Path | None:
    package = Path(__file__).resolve().parents[1]
    for candidate in (package / "_bundled_sources", package.parents[1] / "data" / "sources"):
        if (candidate / PRIMARY_SOURCE).exists():
            return candidate
    return None


def import_catalog(
    ctx: AppContext, source: str | None = None, compare: list[str] | None = None
) -> dict[str, Any]:
    """Build the SQLite catalog. With no arguments the bundled source files are used."""
    if source:
        primary_path = Path(source)
        compare_paths = [Path(c) for c in (compare or [])]
    else:
        bundled = bundled_sources_dir()
        if bundled is None:
            raise Integra7Error(
                errors.SOURCE_NOT_FOUND,
                "Bundled source data not found",
                hint="Pass the path to roland-integra-7-full.txt explicitly.",
            )
        primary_path = bundled / PRIMARY_SOURCE
        compare_paths = [Path(c) for c in compare] if compare else [bundled / COMPARISON_SOURCE]
    for p in (primary_path, *compare_paths):
        if not p.is_file():
            raise Integra7Error(errors.SOURCE_NOT_FOUND, f"Source file not found: {p}")
    ctx.close()
    summary = database.build_catalog(
        ctx.config.resolved_db_path(),
        parser.parse_file(primary_path),
        [parser.parse_file(p) for p in compare_paths if p.exists()],
    )
    summary["note"] = "Run `integra7 patches audit` for duplicates, conflicts and coverage."
    return ok_result(summary)


def _check_kind(kind: str | None) -> None:
    if kind and kind not in KINDS:
        raise usage_error(
            errors.INVALID_ARGUMENT, f"kind must be one of {', '.join(KINDS)}; got {kind!r}"
        )


def search_patches(
    ctx: AppContext,
    query: str = "",
    *,
    kind: str | None = None,
    engine: str | None = None,
    category: str | None = None,
    expansion: str | None = None,
    bank: str | None = None,
    limit: int = 20,
    fuzzy: bool = True,
) -> dict[str, Any]:
    _check_kind(kind)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise usage_error(errors.INVALID_ARGUMENT, f"limit must be 1-500, got {limit!r}")
    hits = search.search(
        ctx.patches(),
        query,
        kind=kind,
        engine=engine,
        category=category,
        expansion=expansion,
        bank=bank,
        limit=0,
        fuzzy=fuzzy,
        aliases=ctx.aliases(),
    )
    return ok_result(
        {
            "query": query,
            "filters": {
                k: v
                for k, v in dict(
                    kind=kind, engine=engine, category=category, expansion=expansion, bank=bank
                ).items()
                if v
            },
            "total_matches": len(hits),
            "returned": min(len(hits), limit),
            "results": [h.to_dict() for h in hits[:limit]],
        }
    )


def get_patch(ctx: AppContext, patch_id: str) -> Patch:
    patch = database.get_patch(ctx.conn(), patch_id)
    if patch is None:
        raise Integra7Error(
            errors.PATCH_NOT_FOUND,
            f"No patch with ID {patch_id!r}",
            hint="IDs look like 'sn-a-preset-0001'. Use `integra7 patches search` to find one; "
            "a patch NAME is not an ID.",
        )
    return patch


def show_patch(ctx: AppContext, patch_id: str) -> dict[str, Any]:
    patch = get_patch(ctx, patch_id)
    data = patch.to_dict()
    data["aliases"] = ctx.aliases().get(patch.id, [])
    data["provenance"] = database.provenance(ctx.conn(), patch.id)
    data["select_with"] = (
        f"integra7 studio-set select {patch.display_pc}"
        if patch.kind == "studio_set"
        else f"integra7 part select --part <1-16> --patch-id {patch.id}"
    )
    return ok_result(data)


def resolve_patch(ctx: AppContext, patch_id: str | None = None, name: str | None = None) -> Patch:
    """Resolve by ID, or by name only when the name identifies exactly one patch."""
    if bool(patch_id) == bool(name):
        raise usage_error(errors.INVALID_ARGUMENT, "Give exactly one of patch ID or patch name")
    if patch_id:
        return get_patch(ctx, patch_id)
    assert name is not None
    patch, candidates = search.resolve_name(ctx.patches(), name, ctx.aliases())
    if patch is not None:
        return patch
    listed = [
        {k: h.to_dict()[k] for k in ("id", "name", "kind", "bank", "category", "match")}
        for h in candidates
    ]
    if not listed:
        raise Integra7Error(
            errors.PATCH_NOT_FOUND,
            f"No patch matches the name {name!r}",
            hint="Try `integra7 patches search` with fewer or different words.",
        )
    raise Integra7Error(
        errors.AMBIGUOUS_PATCH,
        f"The name {name!r} does not identify exactly one patch; nothing was sent",
        details={"candidates": listed},
        hint="Choose one candidate and pass its ID with --patch-id.",
    )


def audit_catalog(ctx: AppContext) -> dict[str, Any]:
    return ok_result(audit_mod.audit(ctx.conn()))


def export_catalog(ctx: AppContext, output: str | None = None) -> dict[str, Any]:
    aliases = ctx.aliases()
    sources = [
        {"role": r["role"], "filename": r["filename"], "sha256": r["sha256"]}
        for r in ctx.conn().execute("SELECT role, filename, sha256 FROM sources ORDER BY id")
    ]
    patch_rows = [{**p.to_dict(), "aliases": aliases.get(p.id, [])} for p in ctx.patches()]
    document = {
        "schema_version": database.SCHEMA_VERSION,
        "attribution": "Patch names from https://github.com/odashi/integra7-cubase "
        "(Apache-2.0). Bank mapping from Roland's INTEGRA-7 MIDI Implementation.",
        "sources": sources,
        "patches": patch_rows,
    }
    if not output:
        return ok_result(document)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ok_result({"output": str(path), "patch_count": len(patch_rows)})
