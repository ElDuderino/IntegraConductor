"""Bank Select map transcribed from Roland's INTEGRA-7 MIDI Implementation, section 1
("Bank Select (Controller number 0, 32)"), https://static.roland.com/assets/media/pdf/INTEGRA-7_MI.pdf

This table is the authority for a record's kind, engine and expansion requirement.
Sound *names* are not in that document, so names are never treated as verified here.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import KIND_DRUM_KIT, KIND_STUDIO_SET, KIND_TONE

MI_SOURCE = "Roland INTEGRA-7 MIDI Implementation (Bank Select table)"


@dataclass(frozen=True)
class Bank:
    slug: str  # stable prefix for patch IDs
    label: str  # Roland's group name
    kind: str
    engine: str | None
    msb: int
    lsb_first: int
    lsb_last: int
    total: int  # number of entries Roland documents for the group
    expansion: str | None = None
    user: bool = False
    # Sequential banks number entries as (lsb - lsb_first) * 128 + program + 1.
    # GM2 banks are sparse (LSB is a variation; drum kits use scattered programs).
    sequential: bool = True

    def contains(self, msb: int, lsb: int) -> bool:
        return msb == self.msb and self.lsb_first <= lsb <= self.lsb_last


def _b(slug, label, kind, engine, msb, lsb, total, expansion=None, user=False, sequential=True):
    first, last = (lsb, lsb) if isinstance(lsb, int) else lsb
    return Bank(slug, label, kind, engine, msb, first, last, total, expansion, user, sequential)


_T, _D = KIND_TONE, KIND_DRUM_KIT

BANKS: tuple[Bank, ...] = (
    _b("studio-set", "Studio Set", KIND_STUDIO_SET, None, 85, 0, 64),
    _b("sn-a-user", "User SN Acoustic Tone", _T, "SN-A", 89, (0, 1), 256, user=True),
    _b("sn-a-preset", "Preset SN Acoustic Tone", _T, "SN-A", 89, (64, 65), 256),
    _b("sn-s-user", "User SN Synth Tone", _T, "SN-S", 95, (0, 3), 512, user=True),
    _b("sn-s-preset", "Preset SN Synth Tone", _T, "SN-S", 95, (64, 72), 1109),
    _b("sn-d-user", "User SN Drum Kit", _D, "SN-D", 88, 0, 64, user=True),
    _b("sn-d-preset", "Preset SN Drum Kit", _D, "SN-D", 88, 64, 26),
    _b("pcm-s-user", "User PCM Synth Tone", _T, "PCM-S", 87, (0, 1), 256, user=True),
    _b("pcm-s-preset", "Preset PCM Synth Tone", _T, "PCM-S", 87, (64, 70), 896),
    _b("gm2-tone", "GM2 Tone", _T, "PCM-S", 121, (0, 127), 256, sequential=False),
    _b("pcm-d-user", "User PCM Drum Kit", _D, "PCM-D", 86, 0, 32, user=True),
    _b("pcm-d-preset", "Preset PCM Drum Kit", _D, "PCM-D", 86, 64, 14),
    _b("gm2-drum", "GM2 Drum Kit", _D, "PCM-D", 120, 0, 9, sequential=False),
    _b("srx01-tone", "Expansion PCM Tone (SRX01)", _T, "PCM-S", 93, 0, 41, "SRX-01"),
    _b("srx01-drum", "Expansion PCM Drum (SRX01)", _D, "PCM-D", 92, 0, 79, "SRX-01"),
    _b("srx02-tone", "Expansion PCM Tone (SRX02)", _T, "PCM-S", 93, 1, 50, "SRX-02"),
    _b("srx03-tone", "Expansion PCM Tone (SRX03)", _T, "PCM-S", 93, 2, 128, "SRX-03"),
    _b("srx03-drum", "Expansion PCM Drum (SRX03)", _D, "PCM-D", 92, 2, 12, "SRX-03"),
    _b("srx04-tone", "Expansion PCM Tone (SRX04)", _T, "PCM-S", 93, 3, 128, "SRX-04"),
    _b("srx05-tone", "Expansion PCM Tone (SRX05)", _T, "PCM-S", 93, (4, 6), 312, "SRX-05"),
    _b("srx05-drum", "Expansion PCM Drum (SRX05)", _D, "PCM-D", 92, 4, 34, "SRX-05"),
    _b("srx06-tone", "Expansion PCM Tone (SRX06)", _T, "PCM-S", 93, (7, 10), 449, "SRX-06"),
    _b("srx06-drum", "Expansion PCM Drum (SRX06)", _D, "PCM-D", 92, 7, 5, "SRX-06"),
    _b("srx07-tone", "Expansion PCM Tone (SRX07)", _T, "PCM-S", 93, (11, 14), 475, "SRX-07"),
    _b("srx07-drum", "Expansion PCM Drum (SRX07)", _D, "PCM-D", 92, 11, 11, "SRX-07"),
    _b("srx08-tone", "Expansion PCM Tone (SRX08)", _T, "PCM-S", 93, (15, 18), 448, "SRX-08"),
    _b("srx08-drum", "Expansion PCM Drum (SRX08)", _D, "PCM-D", 92, 15, 21, "SRX-08"),
    _b("srx09-tone", "Expansion PCM Tone (SRX09)", _T, "PCM-S", 93, (19, 22), 414, "SRX-09"),
    _b("srx09-drum", "Expansion PCM Drum (SRX09)", _D, "PCM-D", 92, 19, 12, "SRX-09"),
    _b("srx10-tone", "Expansion PCM Tone (SRX10)", _T, "PCM-S", 93, 23, 100, "SRX-10"),
    _b("srx11-tone", "Expansion PCM Tone (SRX11)", _T, "PCM-S", 93, 24, 42, "SRX-11"),
    _b("srx12-tone", "Expansion PCM Tone (SRX12)", _T, "PCM-S", 93, 26, 50, "SRX-12"),
    _b("exsn1", "Expansion SN Tone (ExSN1)", _T, "SN-A", 89, 96, 17, "ExSN1"),
    _b("exsn2", "Expansion SN Tone (ExSN2)", _T, "SN-A", 89, 97, 17, "ExSN2"),
    _b("exsn3", "Expansion SN Tone (ExSN3)", _T, "SN-A", 89, 98, 50, "ExSN3"),
    _b("exsn4", "Expansion SN Tone (ExSN4)", _T, "SN-A", 89, 99, 12, "ExSN4"),
    _b("exsn5", "Expansion SN Tone (ExSN5)", _T, "SN-A", 89, 100, 12, "ExSN5"),
    _b("exsn6-drum", "Expansion SN Drum (ExSN6)", _D, "SN-D", 88, 101, 7, "ExSN6"),
    _b("expcm-tone", "Expansion PCM Tone (ExPCM)", _T, "PCM-S", 97, (0, 3), 512, "ExPCM"),
    _b("expcm-drum", "Expansion PCM Drum (ExPCM)", _D, "PCM-D", 96, 0, 19, "ExPCM"),
)

# Expansions that occupy one of the four virtual slots each; ExPCM takes all four.
SINGLE_SLOT_EXPANSIONS: tuple[str, ...] = tuple(
    [f"SRX-{n:02d}" for n in range(1, 13)] + [f"ExSN{n}" for n in range(1, 7)]
)
ALL_SLOT_EXPANSION = "ExPCM"
EXPANSION_NAMES: tuple[str, ...] = (*SINGLE_SLOT_EXPANSIONS, ALL_SLOT_EXPANSION)
SLOT_COUNT = 4


@dataclass(frozen=True)
class Classification:
    bank: Bank | None
    number: int | None  # Roland sequential number within the group, when defined
    in_range: bool  # address lies inside the documented program range


def find_bank(msb: int, lsb: int) -> Bank | None:
    for bank in BANKS:
        if bank.contains(msb, lsb):
            return bank
    return None


def classify(msb: int, lsb: int, program: int) -> Classification:
    bank = find_bank(msb, lsb)
    if bank is None:
        return Classification(None, None, False)
    if not bank.sequential:
        return Classification(bank, None, True)
    number = (lsb - bank.lsb_first) * 128 + program + 1
    return Classification(bank, number, number <= bank.total)


def patch_id(msb: int, lsb: int, program: int) -> str:
    """Stable ID derived only from the MIDI address, so it never depends on names."""
    c = classify(msb, lsb, program)
    if c.bank is None:
        return f"unk-{msb:03d}-{lsb:03d}-{program:03d}"
    if c.bank.slug == "gm2-tone":
        return f"gm2-tone-{program + 1:03d}-v{lsb}"
    if c.bank.slug == "gm2-drum":
        return f"gm2-drum-{program + 1:03d}"
    if c.bank.slug == "studio-set":
        return f"studio-set-{program + 1:02d}"
    return f"{c.bank.slug}-{c.number:04d}"


def normalize_expansion_name(name: str) -> str | None:
    """Map user spellings like 'srx6', 'SRX-06', 'exsn 1', 'expcm' to canonical names."""
    compact = "".join(ch for ch in name.casefold() if ch.isalnum())
    for canonical in EXPANSION_NAMES:
        c = "".join(ch for ch in canonical.casefold() if ch.isalnum())
        if compact == c:
            return canonical
    if compact.startswith("srx") and compact[3:].isdigit():
        n = int(compact[3:])
        if 1 <= n <= 12:
            return f"SRX-{n:02d}"
    return None
