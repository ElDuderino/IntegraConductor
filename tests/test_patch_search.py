from __future__ import annotations

import pytest

from integra7_conductor.catalog import search
from integra7_conductor.catalog.database import normalize, tokens
from integra7_conductor.errors import Integra7Error
from integra7_conductor.services import patches


def test_normalize_and_tokens():
    assert normalize("Sawﬂutter") == "sawflutter"
    assert normalize("  Comp' \"Steel\" ") == "comp steel"
    assert tokens("BrightGrand") == ["bright", "grand"]


def test_exact_name_ranks_first(ctx):
    hits = search.search(ctx.patches(), "Full Grand 1", limit=5)
    assert hits[0].patch.id == "sn-a-preset-0001"
    assert hits[0].match == "exact"


def test_search_is_deterministic(ctx):
    a = [h.patch.id for h in search.search(ctx.patches(), "warm pad", limit=25)]
    b = [h.patch.id for h in search.search(ctx.patches(), "warm pad", limit=25)]
    assert a == b and len(a) == 25


def test_tokens_match_name_and_category(ctx):
    hits = search.search(ctx.patches(), "fretless bass", limit=10)
    assert hits and all("fretl" in normalize(h.patch.name).replace(" ", "") for h in hits[:3])


def test_unicode_ligature_is_searchable(ctx):
    hits = search.search(ctx.patches(), "sawflutter", limit=3)
    assert hits[0].patch.name == "Sawﬂutter"


def test_filters(ctx):
    kits = search.search(ctx.patches(), "jazz", kind="drum_kit", limit=0)
    assert kits and all(h.patch.kind == "drum_kit" for h in kits)
    srx = search.search(ctx.patches(), "", expansion="srx6", limit=0)
    assert srx and all(h.patch.expansion_required == "SRX-06" for h in srx)
    builtin = search.search(ctx.patches(), "piano", expansion="none", limit=0)
    assert builtin and all(h.patch.expansion_required is None for h in builtin)
    sna = search.search(ctx.patches(), "", engine="sn-a", category="piano", limit=0)
    assert sna and all(h.patch.engine == "SN-A" for h in sna)
    # A category the comparison source assigns is searchable as an alternate category.
    other = search.search(ctx.patches(), "", category="other keyboards", limit=0)
    assert other and all("Other Keyboards" in h.patch.alt_categories for h in other)


def test_fuzzy_typo_and_opt_out(ctx):
    assert search.search(ctx.patches(), "fretles", limit=3)
    typo = search.search(ctx.patches(), "harpsicord", limit=3)
    assert typo and typo[0].match == "fuzzy"
    assert not search.search(ctx.patches(), "harpsicord", limit=3, fuzzy=False)


def test_service_search_needs_no_midi(ctx, backend):
    result = patches.search_patches(ctx, "rhodes", kind="tone", limit=5)
    assert result["ok"] and result["data"]["returned"] == 5
    assert set(result["data"]["results"][0]) >= {"id", "bank_msb", "bank_lsb", "program"}
    assert backend.requests == [] and backend.sent == []


def test_resolve_exact_unique_name(ctx):
    assert patches.resolve_patch(ctx, name="full grand 1").id == "sn-a-preset-0001"


def test_resolve_ambiguous_name_lists_candidates(ctx):
    with pytest.raises(Integra7Error) as info:
        patches.resolve_patch(ctx, name="Jazz Kit")
    assert info.value.code == "AMBIGUOUS_PATCH"
    ids = {c["id"] for c in info.value.details["candidates"]}
    assert {"sn-d-preset-0007", "expcm-drum-0005"} <= ids


def test_resolve_unknown_name_and_id(ctx):
    with pytest.raises(Integra7Error) as info:
        patches.resolve_patch(ctx, name="zzzqqqxxx")
    assert info.value.code == "PATCH_NOT_FOUND"
    with pytest.raises(Integra7Error) as info:
        patches.resolve_patch(ctx, patch_id="Full Grand 1")  # a name is not an ID
    assert info.value.code == "PATCH_NOT_FOUND"


def test_show_includes_provenance(ctx):
    data = patches.show_patch(ctx, "sn-a-preset-0001")["data"]
    assert data["provenance"][0]["source_file"] == "roland-integra-7-full.txt"
    assert "name not verified" in data["source"]


def test_export_json(ctx, tmp_path):
    out = tmp_path / "out" / "patches.json"
    result = patches.export_catalog(ctx, str(out))
    import json

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert result["data"]["patch_count"] == len(doc["patches"]) == len(ctx.patches())
    assert "Apache-2.0" in doc["attribution"]
    assert any(p["name"] == "Sawﬂutter" for p in doc["patches"])
