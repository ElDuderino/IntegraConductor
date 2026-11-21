# Integra7 Conductor

An agent-friendly command line (`integra7`) and stdio MCP server (`integra7-mcp`)
for the Roland INTEGRA-7. It searches an offline patch catalog and sends
validated, correctly routed MIDI to the synth. It is deterministic: no model,
cloud service or DAW is involved. Claude Code or Codex supplies the language
understanding and calls these tools.

```text
Claude Code / Codex (WSL2)
        │
   integra7 CLI / integra7-mcp        ← Linux Python: catalog, validation, JSON
        │  one JSON request on stdin, argument array (no shell)
   WSL → Windows process interop
        │
   windows_adapter.py                 ← Windows Python: mido + python-rtmidi
        │
   Roland USB driver → INTEGRA-7
```

The Roland USB driver lives on Windows, so MIDI I/O runs there. Nothing needs
USB passthrough into WSL. Searching, dry runs and the test suite need no
Windows process and no hardware.

## Testing status

| Area | Status | Date | Observed result |
|---|---|---|---|
| Catalog import, search, audit, export | `tested_offline` | 2026-11-20 | 211 pytest tests pass in WSL (Python 3.12) |
| MIDI byte encoding, SysEx checksum/parsing | `tested_offline` | 2026-11-20 | Matches Roland's documented checksum example |
| Part select, Studio Set select, audition, readback logic | `tested_offline` | 2026-11-20 | Mock backend with a simulated device only |
| CLI JSON contract, exit codes, config precedence | `tested_offline` | 2026-11-20 | Pass |
| MCP server tools | `tested_offline` | 2026-11-20 | In-process tests, plus a real stdio session listing and calling tools (mock backend) |
| Effects control (`integra7 fx`) | `tested_on_hardware` | 2026-11-20 | 33 parameters (surround room, master EQ, part placement) written and read back as `verified` through a UR22mkII; audible result judged by the owner |
| WSL → Windows adapter launch | `tested_windows_without_device` | 2026-11-20 | Adapter started under Windows Python 3.13 from a `/mnt/c` checkout and returned structured JSON (`ADAPTER_DEPENDENCY_MISSING`) |
| Windows MIDI port enumeration | `tested_windows_without_device` | 2026-11-20 | Built-in WinMM fallback under Windows Python 3.13 listed `Microsoft GS Wavetable Synth` and `Steinberg UR22mkII` |
| mido/RtMidi adapter path on Windows | `not_tested` | – | `python-rtmidi` has no wheel for Windows Python 3.13; needs 3.10–3.12 |
| Sending MIDI to an INTEGRA-7 | `tested_on_hardware` (send only) | 2026-11-20 | `integra7 play examples/blue-conductor.json` sent through a UR22mkII 5-pin MIDI output to the unit; result `sent_unverified`. Outcome judged by ear by the owner, not by this tool |
| WinMM SysEx input (readback) | `tested_on_hardware` | 2026-11-20 | Identity Reply, Setup, System Common and all 16 Studio Set Part blocks read through a UR22mkII MIDI IN |
| SysEx readback from a real unit | `tested_on_hardware` | 2026-11-20 | `device identify`, `device state`, `part channels --from-device --save`; `part select` returned `verified` (readback matched) |
| `INTEGRA-7` vs `INTEGRA-7 CTRL` port behavior | `not_tested` | – | Routing is configurable; defaults are assumptions |
| Checkout on the WSL-native filesystem | `not_tested` | – | Path translation is unit-tested with a stubbed `wslpath` |

Mock results never count as hardware results. See
[docs/hardware-test-plan.md](docs/hardware-test-plan.md) for the steps to run
on a real unit.

## Quickstart

### 1. WSL side

```bash
git clone <this repo> && cd IntegraConductor
bash scripts/setup-wsl.sh
```

This creates a virtual environment in `~/.local/share/integra7-conductor/venv`,
links `integra7` and `integra7-mcp` into `~/.local/bin`, and builds the patch
catalog from the bundled source files. To do it by hand:

```bash
python3 -m venv ~/.local/share/integra7-conductor/venv
~/.local/share/integra7-conductor/venv/bin/pip install -e '.[dev,mcp]'
integra7 patches import
```

### 2. Windows side

Any Windows Python 3.9+ works. With Python 3.10–3.12 the adapter uses `mido` +
`python-rtmidi`; on other versions (no `python-rtmidi` wheel) it falls back
automatically to Windows' built-in MIDI API through `ctypes`, with no extra
packages. `integra7 doctor` shows which is in use.

The INTEGRA-7 can be reached over USB (Roland driver, ports named `INTEGRA-7`)
or through any MIDI interface's 5-pin output: set `performance_port` to that
interface, e.g. `integra7 config set performance_port "Steinberg UR22mkII"`.
Without a cable back from the unit's MIDI OUT there is no readback, so results
stay `sent_unverified`.

```powershell
winget install --id Python.Python.3.12 -e      # only if you lack 3.10-3.12
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
```

or from WSL:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/setup-windows.ps1)"
```

The script creates `%LOCALAPPDATA%\integra7-conductor\venv`, installs `mido` and
`python-rtmidi`, and lists the MIDI ports Windows sees. On the INTEGRA-7 set
**MENU → SYSTEM → USB Driver = VENDER** (Roland's spelling) and restart the unit.

### 3. Check, search, dry-run, send

```bash
integra7 doctor --write-config        # interop, adapter, ports, catalog; saves the Python path
python -m pytest                      # offline tests (use the venv's python)
integra7 patches search "fretless bass" --kind tone --limit 5
integra7 part select --part 1 --patch "Full Grand 1" --dry-run --json
integra7 ports --json                 # with the synth connected
integra7 device identify --json       # does the unit answer?
integra7 part channels --from-device --save
integra7 part select --part 1 --patch-id sn-a-preset-0001 --json
```

From Windows `cmd` or PowerShell, run `integra7 ...` inside the repository folder:
`integra7.cmd` there forwards to the WSL command (Windows-style paths are accepted).

Native Windows use (no WSL; this path is untested): install the package into the Windows venv with
`pip install -e ".[midi]"` and run `integra7 --backend native ...`, or list ports
with `python src\integra7_conductor\midi\windows_adapter.py --ports`.

## Commands

| Command | Purpose |
|---|---|
| `integra7 doctor [--write-config] [--strict]` | Diagnose interop, adapter, ports, catalog. Sends nothing to the synth. |
| `integra7 ports` | List MIDI ports and how configured names resolve. |
| `integra7 capabilities` | What is supported and what each status means. |
| `integra7 patches import [FILE] [--compare FILE]` | Build the SQLite catalog (bundled sources by default). |
| `integra7 patches search QUERY [--kind --engine --category --expansion --bank --limit --no-fuzzy]` | Deterministic search. |
| `integra7 patches show ID` | One patch with aliases and source provenance. |
| `integra7 patches audit` | Counts, conflicts, cross-source discrepancies, coverage vs Roland's bank table. |
| `integra7 patches export --format json [--output PATH]` | Portable JSON export. |
| `integra7 part channels [--from-device [--save]]` | Show the part → channel map, or read it from the unit. |
| `integra7 part channels set --part N --channel C` | Set the local mapping (sends nothing). |
| `integra7 part select --part N (--patch-id ID \| --patch NAME) [--dry-run] [--no-verify]` | Select a tone or drum kit. |
| `integra7 part audition --part N [--patch-id ID] [--note --velocity --duration-ms] [--dry-run]` | Play one short note. |
| `integra7 part show --part N` | Read a part's channel and current tone from the unit. |
| `integra7 play SCORE.json [--tempo BPM] [--loop N] [--parts N,N] [--keep-patch N,N] [--keep-fx] [--dry-run]` | Apply a score's effects, select its patches and play it (see `examples/`). While it plays, `part select` and `fx set` run from another terminal are fed into the playback. |
| `integra7 fx list` / `fx show [--part N]` / `fx set PATH=VALUE…` | Read or set Studio Set effects: reverb, chorus, Motional Surround room, master EQ, per-part level, pan, sends and stage position. Writes are confirmed by readback. |
| `integra7 studio-set list` / `select N (--dry-run \| --yes)` | Recall a Studio Set (changes all 16 parts). |
| `integra7 device identify` / `device state [--no-parts]` | Read-only queries over documented SysEx. |
| `integra7 expansions status` / `declare NAMES…` / `plan NAMES…` | Declared expansion state and slot planning. |
| `integra7 config show` / `path` / `set KEY VALUE` | Configuration. |

Global options (before or after the subcommand): `--json`, `--config PATH`,
`--backend {windows,native,mock}`, `--db PATH`, `--performance-port`,
`--control-port`, `--input-port`, `--device-id`.

## Output contract

`--json` writes exactly one JSON object to stdout, including on errors. Human
diagnostics go to stderr. Exit status: `0` success, `1` operational failure,
`2` invalid arguments or values.

```json
{
  "ok": true,
  "backend": "mock",
  "verification_status": "not_sent",
  "data": {
    "part": 1,
    "channel": 1,
    "patch_name": "Full Grand 1",
    "midi_messages_hex": ["B0 00 59", "B0 20 40", "C0 00"],
    "sent": false
  },
  "warnings": ["Part 1 -> channel 1 is an unconfirmed default assumption."]
}
```

`verification_status` is one of:

| Status | Meaning |
|---|---|
| `verified` | A documented SysEx readback from the unit matched the requested state. |
| `sent_unverified` | Bytes were handed to a real MIDI port; no matching readback. |
| `mocked` | Mock backend. No hardware involved. |
| `not_sent` | Dry run, refusal, or failure before transmission. |

A successful send alone is never `verified`. If the readback shows a different
state, the command fails with `MIDI_NOT_VERIFIED` and a diagnosis (for example a
part receiving on a different channel than configured).

Error codes include `AMBIGUOUS_PATCH`, `PATCH_NOT_FOUND`, `WRONG_PATCH_KIND`,
`INVALID_PART`, `INVALID_CHANNEL`, `INVALID_BANK`, `INVALID_PROGRAM`,
`INVALID_NOTE`, `INVALID_ARGUMENT`, `CONFIRMATION_REQUIRED`, `PORT_NOT_FOUND`,
`PORT_AMBIGUOUS`, `PORT_OPEN_FAILED`, `MIDI_SEND_FAILED`, `MIDI_NOT_VERIFIED`,
`DEVICE_TIMEOUT`, `DEVICE_BUSY`, `EXPANSION_NOT_LOADED`,
`WINDOWS_INTEROP_UNAVAILABLE`, `ADAPTER_NOT_FOUND`,
`ADAPTER_DEPENDENCY_MISSING`, `ADAPTER_FAILED`, `CATALOG_NOT_FOUND`,
`SOURCE_NOT_FOUND`, `CONFIG_INVALID`. The full list is in
`src/integra7_conductor/errors.py`.

## Patch IDs, names and numbering

- A patch **ID** such as `sn-a-preset-0001` is derived only from the MIDI
  address, so it is stable and unique. IDs are the reliable way to select.
- A **name** is accepted by `part select --patch` only when it identifies
  exactly one patch. `Jazz Kit` exists in two banks, so it is refused with a
  list of candidate IDs and nothing is sent.
- `program` is the zero-based value sent in the Program Change (0–127).
  `display_pc` is the 1-based number Roland prints (1–128). Full Grand 1 is
  MSB 89, LSB 64, `program` 0, `display_pc` 1.

## Ports, parts and channels

These are separate things:

- A **MIDI port** (`performance_port`, `control_port`, `input_port`) is a
  Windows device name. Names resolve exactly, then ignoring RtMidi's trailing
  index (`INTEGRA-7 1`), then by unique substring. Ambiguity is an error.
- A **part** (1–16) receives on a **MIDI channel** that may differ from its
  number. Unmapped parts assume part N = channel N and every result says so.
  `integra7 part channels --from-device --save` replaces the assumption with
  what the unit reports.
- A **Studio Set** change goes out on the Studio Set Control Channel (default
  16), not a part channel, and replaces all part settings. It needs `--yes` or
  `--dry-run`; agents are never prompted interactively.

Channel messages go to `performance_port`. RQ1 SysEx goes to the port chosen by
`sysex_port` (`performance` by default, or `control`). Which port the unit
answers on has not been verified on hardware; both are configurable.

## Configuration

File: `~/.config/integra7-conductor/config.toml` (override with `--config` or
`INTEGRA7_CONFIG`). Precedence: **CLI flags > `INTEGRA7_*` environment > config
file > defaults**. `integra7 config show` prints each value and its origin.

| Key | Default | Notes |
|---|---|---|
| `backend` | `windows` in WSL, else `native` | `windows`, `native` or `mock` |
| `performance_port` | `INTEGRA-7` | Output for bank select, program change, notes |
| `control_port` | `INTEGRA-7 CTRL` | Used for SysEx when `sysex_port = "control"` |
| `input_port` | `INTEGRA-7` | Input for SysEx replies |
| `sysex_port` | `performance` | `performance` or `control` |
| `device_id` | `16` (0x10) | Wire value; the unit displays it as 17 |
| `studio_set_control_channel` | `16` | `0` means OFF |
| `[part_channels]` | none | Explicit map, e.g. `2 = 4` |
| `windows_python` | discovered | Windows or `/mnt` path to `python.exe` |
| `windows_adapter` | unset | Optional packaged adapter `.exe` |
| `adapter_timeout_s` / `lock_timeout_s` | `15` / `10` | Process and lock timeouts |
| `readback_timeout_ms` / `settle_ms` | `800` / `150` | SysEx reply wait; pause before readback |
| `verify` | `true` | Attempt readback after a change |
| `dry_run` | `false` | Make every change a dry run |
| `expansion_policy` | `warn` | `warn`, `refuse` or `ignore` |
| `expansions_declared` / `loaded_expansions` | `false` / `[]` | Set by `integra7 expansions declare` |
| `db_path` | `~/.local/share/integra7-conductor/patches.db` | Catalog location |

Environment variables use the upper-cased key: `INTEGRA7_BACKEND=mock`,
`INTEGRA7_DEVICE_ID=0x11`, `INTEGRA7_DB_PATH=/tmp/p.db`.

## MCP server

`integra7-mcp` is a stdio server that calls the same service functions as the
CLI and returns the same envelopes.

```bash
claude mcp add integra7 -- integra7-mcp                          # Claude Code
claude mcp add integra7-mock -e INTEGRA7_BACKEND=mock -- integra7-mcp
```

The Claude Code syntax above was checked against `claude mcp add --help` on
2026-11-20. For Codex, the equivalent is `codex mcp add integra7 -- integra7-mcp`
or, in `~/.codex/config.toml`:

```toml
[mcp_servers.integra7]
command = "integra7-mcp"
```

Codex was not installed on the development machine, so check
`codex mcp --help` for the current syntax.

Tools: `search_patches`, `get_patch`, `list_midi_ports`,
`get_configured_part_channels`, `select_patch`, `select_studio_set` (defaults to
`dry_run=true`), `audition_patch`, `get_device_capabilities`,
`get_device_state`, `get_current_part_patch`, `get_expansion_slots`,
`list_effect_parameters`, `get_effects`, `set_effects`.

Smoke test: *"Find five warm electric-piano tones in the factory library; show
their IDs and bank numbers; dry-run selection of the second match on Part 2;
only execute after I select it."*

## Expressive wind parts

A score part can carry an `expression` object, which plays a saxophone (or other
SuperNATURAL Acoustic wind) line as phrases instead of separate notes:

```json
{"part": 1, "patch_id": "sn-a-preset-0236",
 "expression": {"style": "breathy_ballad_tenor", "seed": 1947},
 "notes": [[0, "G4", 1.5, 74, "breath"], [1.5, "F4", 0.5, 66], [2, "Eb4", 1, 68]]}
```

It slurs by overlapping notes and tongues by leaving gaps, shapes each phrase
with a CC1 dynamics curve, adds delayed vibrato with channel aftertouch on long
notes only, and uses Roland's own sax articulations: SubTone (CC82), Staccato
(CC80), Fall (CC81), growl (CC18) and breath noise (CC16). Those controller roles
come from Roland's Parameter Guide; the curves, timings and the five styles
(`warm_jazz_tenor`, `breathy_ballad_tenor`, `aggressive_blues_tenor`,
`lyrical_alto`, `pop_sax`) are this project's heuristics, tuned by ear. The same
seed always gives the same performance. Options `intensity`, `humanize`,
`vibrato`, `subtone`, `growl`, `scoops` and `falls` scale each ingredient
(0 switches it off). Note marks: `breath`, `tongue`, `accent`, `ghost`, `peak`,
`straight`, `stacc`, `fall`, `scoop`.

The part should be monophonic with legato on, and scoops need a numeric bend
range: `integra7 fx set part.1.mono_poly=mono part.1.legato=on part.1.bend_range=2`
(the example scores do this in their `fx` block).

`examples/sax-articulation-test.json` plays each control on its own for checking
by ear, and `integra7 play SCORE --dry-run --dump-events FILE` writes every MIDI
event a score would send.

## Catalog and data sources

The catalog is built from two community Cubase patch scripts (Apache-2.0,
bundled in `data/sources/`) and classified with the Bank Select table in
Roland's MIDI Implementation. As imported on 2026-11-20, `patches audit`
reports 6,044 distinct addresses from 6,037 primary and 2,851 comparison
records, including:

- 1 conflicting label in the primary file (two names at GM2 121/0/PC 116),
- 86 name disagreements and 64 category disagreements between the two files
  (kept as aliases and alternate categories),
- 7 records in a bank Roland does not document (89/101; left as `unknown`),
- 41 SRX-01 tones the source lists under "Drums" (classified by bank as tones),
- 2 addresses Roland documents that neither file contains.

These numbers are computed from the sources on each import; none is assumed.
**Names have not been checked against Roland's Sound List PDF**; addresses were
range-checked against the MIDI Implementation. Details:
[docs/sources-and-licenses.md](docs/sources-and-licenses.md).

## Expansions

SRX and ExSN expansions take one of four virtual slots each; ExPCM takes all
four. The published MIDI Implementation has no address for the slots, so this
tool cannot read which expansions are loaded and does not load them.

- Catalog entries carry `expansion_required` from Roland's bank table.
- `integra7 expansions declare SRX-06 ExSN1` records what you loaded on the
  unit. It is reported as `assumed`, never verified.
- `expansion_policy = "warn"` sends with a warning; `"refuse"` blocks patches
  whose expansion is not declared.
- A patch that needs an expansion is never reported `verified`.

Undocumented expansion-loading SysEx is not implemented. See
[docs/experimental-expansions.md](docs/experimental-expansions.md).

## Safety

- Every value is range-checked before anything is sent.
- `--dry-run` exists for every operation that changes sound and prints the exact
  bytes, port and channel.
- An audition's note-off is in the same transaction, and the adapter also sends
  it from a cleanup path if anything fails after the note-on. Maximum 5 s.
- Hardware transactions are serialized with a file lock so bank select and
  program change from two callers cannot interleave.
- There is no raw SysEx command. The only parameter writes are the named,
  range-checked Studio Set effect settings in `integra7 fx`; they edit the
  temporary Studio Set and are confirmed by readback.

## Development

```bash
~/.local/share/integra7-conductor/venv/bin/python -m pytest
~/.local/share/integra7-conductor/venv/bin/ruff check .
~/.local/share/integra7-conductor/venv/bin/mypy
```

Layout:

```text
src/integra7_conductor/
  cli.py  mcp_server.py  config.py  models.py  errors.py
  catalog/   banks.py (Roland bank table)  parser.py  database.py  search.py  audit.py
  midi/      protocol.py  sysex.py  backend.py  mock_backend.py
             windows_adapter.py (standalone, runs under Windows Python)  wsl_interop.py
  services/  core.py  patches.py  parts.py  studio_sets.py  device.py  expansions.py
data/sources/   bundled Cubase scripts + license and attribution
scripts/        setup-wsl.sh  setup-windows.ps1
docs/           setup, protocol, sources, hardware test plan, expansions
tests/          offline test suite and fixtures
```

Differences from the layout suggested in the original spec (`docs/PRD.md`): the catalog database is
generated into the user data directory rather than `data/generated/`; a
`services/device.py` and `catalog/banks.py` were added; there is no separate
`scripts/import-patches.py` because `integra7 patches import` is the one-command
import.

## Known limitations

- Hardware testing so far used 5-pin MIDI through an audio interface with the
  WinMM fallback; the Roland USB driver ports and the mido/RtMidi path are untested.
- Studio Set selection has not been tried on hardware.
- Reverb and chorus parameters beyond type and level, and each tone's own
  multi-effect (MFX), are not controllable yet.
- Patch names are unverified against Roland's Sound List.
- Expansion slots cannot be read or changed.
- Scene/preset orchestration (phase 6 of `docs/PRD.md`) is not implemented.
- No project license has been chosen yet; `pyproject.toml` has no `license`
  field.
