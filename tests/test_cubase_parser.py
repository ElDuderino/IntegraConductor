from __future__ import annotations

import json

from conftest import FIXTURES, SOURCES
from integra7_conductor.catalog import audit, banks, database, parser


def _parsed():
    return parser.parse_file(FIXTURES / "sample-cubase.txt")


def test_header_and_record_fields():
    p = _parsed()
    assert p.header["device manufacturer"] == "Roland"
    assert p.sha256 and p.encoding == "utf-8"
    first = p.records[0]
    assert (first.level, first.program, first.msb, first.lsb) == (3, 0, 89, 64)
    assert first.name == "Full Grand 1"
    assert first.mode == "Tones"
    assert first.groups == ("Acoustic Piano", "Supernatural Acoustic")
    assert first.line_no == 13


def test_whitespace_special_characters_and_p2():
    by_name = {r.name: r for r in _parsed().records}
    assert by_name["Full Grand 3"].program == 2  # odd spacing inside brackets, trailing spaces
    assert "Comp' \"Steel\"" in by_name  # apostrophes and quotes preserved
    assert "Sawﬂutter" in by_name  # non-ASCII ligature preserved verbatim
    kit = by_name["Session Kit"]
    assert (kit.level, kit.mode, kit.groups) == (2, "Drums", ("Supernatural Drum Kits",))


def test_group_levels_reset_and_repeated_headers():
    records = _parsed().records
    unknown = next(r for r in records if r.name == "Unknown Bank Tone")
    assert unknown.groups == ("Mystery",)  # the earlier [g2] no longer applies
    jazz = [r for r in records if r.name == "Jazz Kit"]
    assert [r.groups[0] for r in jazz] == ["EX PCM Drum Kits", "Supernatural Drum Kits"]
    preview = next(r for r in records if r.name == "Integra Preview")
    assert preview.mode == "Studio Sets"


def test_malformed_records_are_kept_not_dropped():
    p = _parsed()
    bad = [r for r in p.records if not r.valid]
    assert {r.problem for r in bad} == {"program 200 outside 0-127", "malformed patch record"}
    assert [raw for _, raw in p.unrecognized] == ["this line is noise"]
    assert all(r.name != "After End Ignored" for r in p.records)  # [end] stops parsing


def test_cp1252_fallback():
    p = parser.parse_text(*parser._decode(b"[mode] Tones\n[p3, 0, 89, 64] Caf\xe9\n")[:1])
    assert p.records[0].name == "Café"


def test_catalog_duplicates_conflicts_and_provenance(fixture_db):
    conn = database.open_catalog(fixture_db)
    report = audit.audit(conn)
    counts = report["issue_counts"]
    # "Full Grand 3" then "Concert Grand" at the same address: both kept, conflict reported.
    assert counts["conflicting_label"] == 1
    assert counts["malformed_record"] == 2
    assert counts["unknown_bank"] == 1
    assert counts["outside_documented_range"] == 1  # SRX-01 has 41 tones; PC 61 is past the end
    assert counts["cross_source_name_mismatch"] == 1
    assert counts["missing_from_primary"] == 1
    assert counts["unrecognized_line"] == 1
    # The comparison file abbreviates the category; that is normalized, not a disagreement.
    assert "category_disagreement" not in counts

    patch = database.get_patch(conn, "sn-a-preset-0003")
    assert patch.name == "Full Grand 3"  # first label wins; nothing is overwritten
    assert database.aliases_by_patch(conn)["sn-a-preset-0003"] == ["Concert Grand"]
    prov = database.provenance(conn, "sn-a-preset-0003")
    assert [(p["line"], p["original_name"]) for p in prov] == [
        (15, "Full Grand 3"),
        (16, "Concert Grand"),
    ]
    assert prov[0]["source_file"] == "sample-cubase.txt"

    # Every source line survives, valid or not.
    total = conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
    assert total == 18 + 3
    assert report["unresolved_kinds"] == 1
    assert report["unknown_expansion_requirement"] == 1


def test_kind_engine_and_expansion_come_from_bank_table(fixture_db):
    conn = database.open_catalog(fixture_db)
    get = lambda pid: database.get_patch(conn, pid)  # noqa: E731
    assert (get("sn-a-preset-0001").kind, get("sn-a-preset-0001").engine) == ("tone", "SN-A")
    assert get("sn-a-preset-0001").category == "Acoustic Piano"
    strings = get("srx06-tone-0001")
    assert (strings.expansion_required, strings.category) == ("SRX-06", "Strings")
    assert get("expcm-drum-0005").expansion_required == "ExPCM"
    assert get("sn-d-preset-0007").kind == "drum_kit"
    assert get("studio-set-01").kind == "studio_set"
    unknown = get("unk-010-020-005")
    assert (unknown.kind, unknown.expansion_required) == ("unknown", "unknown")
    assert get("gm2-tone-001-v1").name == "Piano 1w"
    assert not get("srx01-tone-0061").in_documented_range


def test_real_source_reference_patches(full_db):
    conn = database.open_catalog(full_db)
    grand = database.get_patch(conn, "sn-a-preset-0001")
    assert (grand.name, grand.kind) == ("Full Grand 1", "tone")
    assert (grand.bank_msb, grand.bank_lsb, grand.program, grand.display_pc) == (89, 64, 0, 1)
    preview = database.get_patch(conn, "studio-set-01")
    assert (preview.name, preview.kind) == ("Integra Preview", "studio_set")
    assert (preview.bank_msb, preview.bank_lsb, preview.program, preview.display_pc) == (
        85, 0, 0, 1,
    )


def test_real_source_counts_are_derived_not_assumed(full_db):
    primary = parser.parse_file(SOURCES / "roland-integra-7-full.txt")
    conn = database.open_catalog(full_db)
    report = audit.audit(conn)
    assert report["sources"][0]["records"] == len(primary.records)
    addresses = {(r.msb, r.lsb, r.program) for r in primary.records if r.valid}
    extra = report["issue_counts"].get("missing_from_primary", 0)
    assert report["patch_count"] == len(addresses) + extra
    assert sum(report["by_kind"].values()) == report["patch_count"]
    json.dumps(report)  # must be JSON-serializable
    # Unique, stable IDs: one per address.
    ids = [r[0] for r in conn.execute("SELECT id FROM patches")]
    assert len(ids) == len(set(ids))


def test_bank_table_ids_and_ranges():
    assert banks.patch_id(89, 64, 0) == "sn-a-preset-0001"
    assert banks.patch_id(89, 65, 127) == "sn-a-preset-0256"
    assert banks.patch_id(95, 72, 84) == "sn-s-preset-1109"
    assert banks.classify(95, 72, 85).in_range is False
    assert banks.patch_id(93, 7, 0) == "srx06-tone-0001"
    assert banks.patch_id(85, 0, 11) == "studio-set-12"
    assert banks.patch_id(1, 2, 3) == "unk-001-002-003"
    assert banks.find_bank(88, 101).expansion == "ExSN6"
    assert banks.normalize_expansion_name("srx6") == "SRX-06"
    assert banks.normalize_expansion_name("ex pcm") == "ExPCM"
    assert banks.normalize_expansion_name("nope") is None
