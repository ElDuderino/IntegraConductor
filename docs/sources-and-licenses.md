# Sources and licenses

## What each source is used for

| Source | Used for | Status |
|---|---|---|
| Roland *INTEGRA-7 MIDI Implementation* (<https://static.roland.com/assets/media/pdf/INTEGRA-7_MI.pdf>) | Bank Select map, SysEx format, checksum, address map | Read on 2026-11-20; facts transcribed by hand into `catalog/banks.py` and `midi/sysex.py`. The PDF is not redistributed. |
| `roland-integra-7-full.txt` from [odashi/integra7-cubase](https://github.com/odashi/integra7-cubase) (Apache-2.0) | Patch names, source categories | Bundled unmodified in `data/sources/`; primary import source |
| `roland-integra-7.txt` from the same repository | Cross-check of names and categories | Bundled unmodified; marked incomplete by its maintainer |
| Roland *INTEGRA-7 Sound List* (<https://cdn.roland.com/assets/media/pdf/INTEGRA-7_Sound_List_je01_W.pdf>) | Would be the authority for names | **Not yet used.** Names are unverified against it. |
| Roland Owner's Manual, Parameter Guide, support articles | Setup guidance (USB Driver = VENDER, Studio Set control channel) | Referenced in docs only |
| [shimpe/Integra7AuralAlchemist](https://github.com/shimpe/Integra7AuralAlchemist) (GPL-3.0) | Named in the original spec (`PRD.md`) as a reference | **Not consulted and no code copied.** |
| Roland Clan forum threads on expansion loading | Undocumented `0F 00 ...` SysEx | **Not used.** See `experimental-expansions.md`. |

## How records are classified

A record's kind (`tone`, `drum_kit`, `studio_set`), engine and
`expansion_required` come only from its bank MSB/LSB in Roland's table, never
from its name or the Cubase file's `[mode]`. A bank that is not in the table
gives `kind: "unknown"` and `expansion_required: "unknown"`.

Each patch's `source` field states exactly what was checked, for example:

> odashi/integra7-cubase roland-integra-7-full.txt; address range checked
> against Roland INTEGRA-7 MIDI Implementation (Bank Select table); name not
> verified against Roland Sound List

## Findings from the import (2026-11-20)

Computed by `integra7 patches audit`; rerun it after any source update.

| Finding | Count | Handling |
|---|---|---|
| Primary records / distinct addresses | 6,037 / 6,036 | One catalog row per address |
| Comparison records | 2,851 | 8 addresses exist only there and are added, flagged |
| Conflicting label in primary | 1 | GM2 121/0 program 115 is both "Castanets" and "Woodblock"; first kept, second is an alias |
| Name differs between files | 86 | Other name stored as an alias (for example "Felt Tine" / "Flet Tine") |
| Category differs between files | 64 | Stored in `alt_categories`, searchable |
| Source lists a tone bank under `[mode] Drums` | 41 | SRX-01 bank 93/0 is a tone bank per Roland; classified as tones |
| Bank not in Roland's table | 7 | Comparison file puts ExSN6 at 89/101; Roland documents 88/101. Kept as `unknown` |
| Documented addresses missing from both files | 2 | SRX-03 tone 60 and SRX-05 drum kit 3 |
| User banks | 0 | User memory is not cataloged |

Only the 16 factory Studio Set names are listed. All 64 Studio Sets are
user-writable, so names can differ on a given unit; selection is by number.

## Licenses

- **This project:** no license has been chosen yet.
- **Bundled Cubase scripts:** Apache License 2.0, text in
  `data/sources/LICENSE-integra7-cubase.txt`, attribution in
  `data/sources/README.md` and in every JSON export.
- **Roland documentation:** copyright Roland Corporation. Only facts (numeric
  ranges, addresses, message formats) are used; no text or tables are copied
  wholesale and the PDFs are git-ignored.
- **Runtime dependencies:** none on the WSL side beyond the standard library.
  Optional: `mcp` (MIT). Windows side: `mido` (MIT), `python-rtmidi` (MIT).
