# Integra7 Conductor — Product Requirements & Implementation Specification

> **Historical document.** This is the original specification the project was built
> from, kept for its design rationale. It is not maintained: the README and the
> other files in `docs/` describe what actually exists, including what was added
> later (effects control, score playback, expressive wind parts) and what was
> never built (expansion switching, scenes).

**Repository:** `integra7-conductor`  
**Python package:** `integra7_conductor`  
**CLI:** `integra7`  
**MCP server:** `integra7-mcp`  
**Target development environment:** Windows 11 + WSL2 (Ubuntu), invoked by Claude Code or OpenAI Codex  
**Target hardware:** Roland INTEGRA-7 connected to **Windows** via USB MIDI  
**Status:** Implementation-ready specification; physical hardware behavior must be validated locally.

> **Agent instruction:** You are the lead engineer implementing this repository. Read this entire PRD before writing code. Build a usable, well-tested MVP without waiting for decisions on optional features. Deliver the phases in order, test with a fake MIDI backend before requiring hardware, and clearly document any hardware-only verification that you cannot perform. Do not claim real device verification unless it actually occurred.

---

## 1. Vision

Create an agent-friendly command-line and MCP interface to the Roland INTEGRA-7. A human or coding agent should be able to say:

- “Find warm electric piano sounds, and load the second one on Part 2.”
- “Load Full Grand 1 on Part 1 and a fretless bass on Part 3.”
- “What expansion boards are loaded, and can I select this SRX tone?”
- “Switch to Studio Set 12.”
- “Audition this patch briefly.”

The core of the product is **reliable, deterministic MIDI control**, *not* a generative AI model. Claude Code/Codex supplies natural-language reasoning and calls stable tools; the program owns patch identity, MIDI validation, device routing, expansion requirements, and transparent result reporting.

### Success definition

From a shell inside WSL, the command `integra7 ...` can search a locally indexed patch library and invoke a Windows-native MIDI adapter to send valid, correctly routed MIDI messages to an attached INTEGRA-7. The exact same operations are exposed to both Claude Code and Codex, first through the CLI, then through an optional stdio MCP server.

## 2. Architectural decision (mandatory)

**Use Windows as the USB MIDI host. WSL is the agent-facing orchestration environment.**

Microsoft documents launching Windows `.exe` programs directly from WSL. The MVP should use this capability instead of requiring USB passthrough into WSL.

```text
          Claude Code / Codex (WSL2)
                       |
                       v
              integra7 CLI (WSL)
          /            |              \
  SQLite index     JSON results    MCP interface
                       |
        structured, validated request
                       |
                       v
        WSL → Windows process interop
          (no interactive shell needed)
                       |
                       v
         Windows MIDI adapter (Python)
              mido + python-rtmidi
                       |
              Roland USB driver
                       |
                       v
                Roland INTEGRA-7
```

**Important:** Do not assume Linux `mido` can enumerate or directly access the Windows Roland driver. Do not make `usbipd`/ALSA passthrough a dependency for the primary implementation. A native Linux adapter may be supported later, but is optional.

### Process topology

1. **WSL CLI** executes indexing/search/configuration operations locally; no Windows process should be required to search patches or run unit tests.
2. **Windows adapter** handles MIDI I/O (including optional SysEx responses) using an installed Windows Python environment, or a packaged `.exe` later.
3. **WSL transport** launches the Windows adapter as a child process with an argument array, not a string assembled for a shell. Return a single structured JSON result. Use `wslpath -w` as appropriate when passing file paths to Windows.
4. Use one adapter invocation per atomic hardware operation; for a multi-message operation, hold the port open across the relevant MIDI sequence. Do not launch a Windows process separately for each MIDI byte/message.
5. Keep a **clear backend interface** (`MockMidiBackend`, `WindowsMidiBackend`, optional `NativeMidiBackend`) so offline testing and hardware access use the same application logic.
6. Prefer a minimal Python implementation and standard-library modules (argparse or Typer if justified; sqlite3; dataclasses/Pydantic). Use `mido` and `python-rtmidi` on Windows.
7. A resident Windows bridge service may be added later if latency, simultaneous clients, or long-lived SysEx readback justify it. **Do not require an HTTP server or firewall rules for the MVP.**

### Path/layout requirements

- Support a git checkout on `/mnt/c/...` (easiest initial setup) and avoid gratuitous assumptions about its location.
- Support a checkout under WSL's native filesystem if practical, using Windows-accessible paths via `wslpath`. Diagnose UNC/path issues rather than failing opaquely. Document which checkout layout was tested.
- Allow an explicitly configured Windows Python executable or adapter executable path. Do not assume the default `python` command is Windows Python.
- When using Windows Python, keep its virtual environment native to Windows. Do not try to import Windows wheel binaries into WSL Python.
- Use UTF-8 JSON and preserve Unicode/special characters in patch names. Keep stdout machine-readable and send diagnostics to stderr.
- Detect and explain when Windows executable interop is disabled, the chosen executable is missing, or the configured port cannot be opened.

## 3. Sources and implementation authority

**Official Roland sources (prefer these for protocol correctness):**

1. INTEGRA-7 Sound List: https://cdn.roland.com/assets/media/pdf/INTEGRA-7_Sound_List_je01_W.pdf
2. INTEGRA-7 MIDI Implementation: https://static.roland.com/assets/media/pdf/INTEGRA-7_MI.pdf
3. INTEGRA-7 Owner's Manual: https://cdn.roland.com/assets/media/pdf/INTEGRA-7_OM.pdf
4. INTEGRA-7 Parameter Guide: https://cdn.roland.com/assets/media/pdf/INTEGRA-7_Parameter_Guide_e01_W.pdf
5. Roland's Studio Set selection guidance: https://support.roland.com/hc/en-us/articles/205926959-INTEGRA-7-How-do-I-select-Studio-Sets-via-MIDI
6. Roland Windows USB driver information: https://support.roland.com/hc/en-us/articles/360046252771-INTEGRA-7-How-to-Install-and-Verify-the-USB-Driver-on-Windows-or-Mac

**Machine-readable source data and reference implementations:**

7. Cubase patch lists: https://github.com/odashi/integra7-cubase
8. **Primary import candidate:** https://github.com/odashi/integra7-cubase/blob/master/roland-integra-7-full.txt
9. **Incomplete comparison file:** https://github.com/odashi/integra7-cubase/blob/master/roland-integra-7.txt
10. Aural Alchemist (reference architecture, parameter/SysEx examples): https://github.com/shimpe/Integra7AuralAlchemist
11. Microsoft WSL interop: https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop
12. Mido RtMidi backend: https://mido.github.io/mido/backends/rtmidi.html

**Experimental/community reference only:**

13. Expansion loading discussion: https://forums.rolandclan.com/viewtopic.php?p=282206
14. Follow-up expansion / control SysEx discussion: https://forums.rolandclan.com/viewtopic.php?start=15&t=55157

### Source reliability notes

- The original `roland-integra-7.txt` is marked **incomplete** by its maintainer; prefer `roland-integra-7-full.txt` for initial parsing, but **do not assume the “full” file is perfectly exhaustive or error-free**. Cross-check against Roland's canonical tables and report coverage/disagreements.
- The Cubase script format includes `[...]` patch records such as `[p3, 0, 89, 64] Full Grand 1`, with fields representing **zero-based MIDI program, bank MSB, bank LSB**. Do not subtract one again when using those entries.
- Roland's printed **PC** convention is typically 1–128. In a MIDI Program Change packet, program is **0–127**.
- Aural Alchemist is GPL-3.0, and the Cubase repository is Apache-2.0. Treat these as references, obey licenses and attribution, and **do not copy GPL source into this project by default**. Include provenance/attribution where required.
- The official Roland SysEx address map must be preferred for supported RQ1/DT1 functionality. Expansion-loading commands using undocumented `0F 00 ...` addresses are *not* a fully documented Roland API and require separate experimental treatment.

## 4. Features and phased milestones

### Phase 0 — Repository bootstrap and offline tests (must finish first)

Implement a usable Python package with an installed `integra7` console entry point, project metadata, dependencies, clean error reporting, linting, type checking where practical, and pytest suite. Provide a `--backend mock` mode that records the exact MIDI messages it would send.

Deliverables:

- `pyproject.toml` with supported Python version and dependencies.
- Entry-point CLI usable from WSL.
- Structured JSON output and exit codes.
- Configuration file support with documented overrides.
- Mock transport and deterministic tests; no INTEGRA-7 hardware required.
- README with separate Windows and WSL installation instructions.

### Phase 1 — Patch catalog import and search (MVP)

Implement an **offline import pipeline** from the more complete Cubase patch script into a normalized SQLite database (plus optional JSON export).

Required:

- Parse `[mode]`, `[g1]`, `[g2]`, and patch definitions (at least `[p2,...]` and `[p3,...]`) and preserve hierarchy. Handle whitespace, encoding, unusual names, escaped/special characters, repeated category headers, and malformed records gracefully.
- Preserve every source record with provenance (source file, row or line, original name, source-specific category hierarchy).
- Normalize a patch to a stable ID, display name, record kind (`tone`, `drum_kit`, `studio_set`, `unknown`), engine or bank family when known, category, MSB, LSB, zero-based `program`, and 1-based `display_pc`.
- Detect duplicates by the correct MIDI address / record type combination; report conflicting labels rather than silently dropping them. Different names can be synonyms/aliases; do not overwrite raw data.
- Classify expansion requirements (`SRX-01`…`SRX-12`, `ExSN1`…`ExSN6`, `ExPCM`) from *documented* bank mappings, not a guess from sound names. For uncertain source rows store `expansion_required: unknown` and flag for review.
- Provide normalized name search, substring, tokens, and optional fuzzy rank; filter by sound engine, kind, category, and expansion. Keep search deterministic; no LLM needed.
- Create tests for **Full Grand 1** (`MSB=89, LSB=64, MIDI program=0, displayed PC=1`) and **Integra Preview** (`MSB=85, LSB=0, MIDI program=0, displayed PC=1`). Explicitly test that the first is a tone and the second a Studio Set.
- Add reproducible import scripts and an audit command that outputs counts, duplicates, unresolved kinds, missing fields, and cross-source discrepancies. **Do not invent an expected total patch count; calculate it from sources.**
- Prefer bundling a generated normalized catalog only where license/attribution permits. If data must be generated during installation, document a one-command workflow. Do not scrape/document-import on each CLI run.

Suggested commands:

```bash
integra7 patches import data/sources/roland-integra-7-full.txt
integra7 patches search "rhodes" --kind tone --limit 15 --json
integra7 patches show sn-a-preset-0001 --json
integra7 patches audit --json
integra7 patches export --format json --output patches.json
```

**Database design preference:** SQLite with indexes and optional FTS5, plus a versioned schema. A simple JSON export is also required for portability. Source attribution must be retained.

Suggested normalized record:

```json
{
  "id": "sn-a-preset-0001",
  "name": "Full Grand 1",
  "kind": "tone",
  "engine": "SN-A",
  "category": "Ac.Piano",
  "bank_msb": 89,
  "bank_lsb": 64,
  "program": 0,
  "display_pc": 1,
  "expansion_required": null,
  "source": "Roland Sound List / Cubase source cross-check"
}
```

The example ID is illustrative; define a stable, collision-resistant scheme. The `source` claim above is only appropriate after actual cross-checking; do not mark unverified records as verified.

### Phase 2 — Windows MIDI transport and reliable patch selection (MVP)

Install or launch the actual MIDI adapter under **Windows Python**, using `mido` + `python-rtmidi` and Roland's Windows USB driver.

**MIDI sequence to select a tone:**

1. CC #0 = bank MSB.
2. CC #32 = bank LSB.
3. Program Change = stored zero-based program number.

For Full Grand 1 on channel 1, the emitted MIDI bytes should be exactly:

```text
B0 00 59
B0 20 40
C0 00
```

Note that human MIDI channels are 1–16 and Mido channels are 0–15. Validate all ranges before transmission.

**Mandatory separation of concepts:**

- A physical **MIDI output port** is not a Studio Set **part**.
- A **part number** is not necessarily the same as its MIDI receive channel.
- A **Studio Set change** is not a normal part tone change: it uses the configurable **Studio Set Control Channel** and may replace many part settings.
- The performance port and `INTEGRA-7 CTRL` port must be separately configurable. The proper routing depends on the operation and Roland documentation. Do not hard-code all SysEx traffic to one port.
- The unit may need relevant MIDI receive filters enabled (`Rx Switch`, Bank Select, Program Change, SysEx). Return actionable diagnostics if the unit seems unresponsive.

**First-cut part mapping:** explicit config mapping `part -> receive channel`; set defaults `1->1, ... 16->16` only as a clearly labeled *assumption* until actual configuration can be read. Provide a `channel-map` command to inspect and override, and later prefer hardware readback where documented.

**Mandatory result semantics:** separate `sent_unverified`, `verified`, `mocked`, and `not_sent`. Successful `port.send` must **not** report `verified` unless a meaningful readback has actually matched the desired state.

**Configuration:** support `performance_port`, `control_port`, `input_port`, `device_id` (Roland SysEx default configurable), `studio_set_control_channel`, `part_channels`, backend type, Windows adapter command/path, timeouts, `dry_run`, and optional expansion policy. Document precedence of CLI flags, environment, config, defaults.

Suggested commands:

```bash
integra7 doctor --json
integra7 ports --json
integra7 part channels --json
integra7 part channels set --part 2 --channel 4
integra7 part select --part 2 --patch "Full Grand 1" --dry-run --json
integra7 part select --part 2 --patch-id sn-a-preset-0001 --json
integra7 studio-set select 1 --dry-run --json
integra7 studio-set select 1 --yes --json
```

Support selecting a sound by patch ID (unambiguous) and name (only when exact or uniquely resolved; otherwise return candidate IDs and refuse to guess). Headless agents must not receive an interactive prompt they cannot answer.

### Phase 3 — MCP tools and useful musician workflows

Expose a **stdio MCP server** started from WSL, using a maintained MCP Python SDK or FastMCP library. No hosted service, cloud API, model API keys, or DAW installation required. Keep the library implementation independent of any particular agent.

At minimum expose:

- `search_patches(query, filters, limit)`
- `get_patch(patch_id)`
- `list_midi_ports()`
- `get_configured_part_channels()`
- `select_patch(part, patch_id, dry_run=false)`
- `select_studio_set(number, dry_run=true)`
- `audition_patch(part, patch_id, note, velocity, duration_ms)`
- `get_device_capabilities()`

If available later:

- `get_device_state()` and `get_current_part_patch()` — supported only when genuine SysEx queries/readback are implemented.
- `get_expansion_slots()` — must return `unknown` or `unsupported` rather than fabricate a state.
- `set_expansion_slots()` — **experimental / disabled by default**.
- `set_part_parameters()` — documented and validated MIDI/SysEx parameters only.

MCP tools should expose typed schemas, descriptions that teach agents the difference between patch IDs and names, and structured error responses. Provide copy/pasteable registration examples for **Claude Code** and **Codex**, but check the **currently installed** agent CLI's MCP registration syntax before writing examples; those commands can evolve.

Suggested natural-language smoke test:

> Find five warm electric-piano tones in the factory library; show their IDs and bank numbers; dry-run selection of the second match on Part 2; only execute after I select it.

### Phase 4 — Bidirectional SysEx device-state inspection

Implement only after basic Windows MIDI I/O works. Use Roland's **published MIDI Implementation** for manufacturer/model/device ID, RQ1 data requests, DT1 data responses/writes, address maps, sizes, and checksum. Support configurable SysEx device ID and input-port routing.

Requirements:

- A reusable, unit-tested Roland SysEx checksum function.
- Safe request-response matching, timeout, checksum validation, device/model validation and fragment handling where needed.
- Never confuse a cached value, configured assumption, observed MIDI response, or verified readback.
- Resolve an actual part's MIDI receive channel from the device when possible. If not possible, preserve explicit configuration and identify it as such.
- Avoid inventing addresses or treating undocumented community snippets as officially specified.
- Document any differences between `INTEGRA-7` and `INTEGRA-7 CTRL` discovered on real hardware.

### Phase 5 — Expansion board inspection and optional switching (experimental)

The unit has four expansion slots. SRX and ExSN expansions generally occupy one slot; **ExPCM uses all four**. A tone that requires an unloaded expansion must not be reported as successfully selected just because a program change was sent.

Implement expansion state **readback first** if reliably possible; otherwise use explicit configured state with an `assumed` marker. Present a clear `unavailable/unknown` result when state cannot be established.

A community-reported mechanism uses an undocumented SysEx request form resembling:

```text
F0 41 10 00 00 64 11 0F 00 30 00 AA BB CC DD CHECKSUM F7
```

**Do not implement this as an ordinary, safe default.** The `11` byte in Roland's published protocol denotes **RQ1**, not DT1 (`12`); the extension's behavior must be investigated and verified. Before any experimental transmission:

- Document provenance, limitations and risk in `docs/experimental-expansions.md`.
- Confirm the correct device ID, message routing, slot code mapping, checksum, timing, busy/ack response, and ExPCM exclusivity.
- Add a disabled-by-default feature flag and an explicit acknowledgement/confirmation for any expansion write.
- Capture/restore the previous expansion configuration only when verified and technically feasible; otherwise warn of disruptive changes and do not advertise rollback.
- Never claim expansion loading worked until it can be observed or genuinely verified.
- Never overwrite persistent user sound/Studio Set memory as a side effect.

**This feature is NOT an MVP gate.** A working CLI plus MIDI patch selection is more valuable than risky expansion automation.

### Phase 6 — Scene/preset orchestration (stretch)

Support a declarative scene describing patches on up to 16 parts, required expansions and channel mappings, with explicit `plan`, `dry_run`, and `apply` operations.

The planner should detect mutually incompatible expansion needs (more than four single-slot expansions, or ExPCM plus any others) and report them before changing hardware. For reproducibility, store the chosen exact patch IDs, not merely fuzzy language descriptions.

---

## 5. CLI and API behavior contract

### Output

- `--json` always emits a **single JSON object** to stdout, including errors. Human logs/debug go to stderr.
- API response contains `ok`, `data` or `error`, `backend`, and `verification_status` when an action is attempted.
- Include a stable error code (examples: `PORT_NOT_FOUND`, `AMBIGUOUS_PATCH`, `INVALID_CHANNEL`, `EXPANSION_NOT_LOADED`, `MIDI_NOT_VERIFIED`, `WINDOWS_INTEROP_UNAVAILABLE`, `DEVICE_TIMEOUT`).
- Nonzero process exit status for failed commands; agents can use these reliably.
- Avoid outputting false confidence: `sent_unverified` is distinct from `verified`.
- Implement `--dry-run` for every operation that can alter sound or settings. Dry-run outputs *what would be sent*, including hex bytes and destination port/channel, and sends nothing.
- Provide command help, examples and stable argument names.

Example JSON result for a dry-run selection:

```json
{
  "ok": true,
  "backend": "mock",
  "verification_status": "mocked",
  "data": {
    "part": 1,
    "channel": 1,
    "patch_name": "Full Grand 1",
    "midi_messages_hex": ["B0 00 59", "B0 20 40", "C0 00"],
    "sent": false
  }
}
```

### Safety and operational robustness

- Use valid ranges: part 1–16; channel 1–16; bank values 0–127; zero-based MIDI program 0–127; displayed program 1–128; note/velocity values according to MIDI rules.
- Refuse ambiguous patch names rather than choosing arbitrarily.
- An audition must always send **note off** in a `finally` cleanup path (or equivalent) even after an interruption or exception. Enforce a reasonable maximum duration and safe default velocity.
- Do not permit arbitrary raw SysEx from an autonomous agent by default.
- Do not assume one device port name; enumerate and permit explicit selection.
- Serialize hardware-changing transactions to avoid interleaved bank-select/program-change sequences from competing callers. Implement a basic lock or equivalent around an atomic hardware action.
- Do not use network services or elevate privileges without need.
- External model inference is not required. Semantic embeddings are optional, after deterministic local search is working.

## 6. Suggested repository structure

```text
integra7-conductor/
├── README.md
├── PRD.md
├── AGENTS.md                     # optional concise coding-agent notes
├── pyproject.toml
├── .gitignore
├── src/integra7_conductor/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── catalog/
│   │   ├── parser.py
│   │   ├── database.py
│   │   ├── search.py
│   │   └── audit.py
│   ├── midi/
│   │   ├── protocol.py
│   │   ├── backend.py
│   │   ├── mock_backend.py
│   │   ├── windows_adapter.py
│   │   ├── wsl_interop.py
│   │   └── sysex.py
│   ├── services/
│   │   ├── patches.py
│   │   ├── parts.py
│   │   ├── studio_sets.py
│   │   └── expansions.py
│   └── mcp_server.py
├── scripts/
│   ├── integra7                   # WSL entry point/wrapper, if needed
│   ├── setup-windows.ps1
│   ├── setup-wsl.sh
│   └── import-patches.py
├── data/
│   ├── fixtures/
│   └── generated/                # licensing and generation instructions
├── docs/
│   ├── setup-windows-wsl.md
│   ├── midi-protocol.md
│   ├── sources-and-licenses.md
│   ├── hardware-test-plan.md
│   └── experimental-expansions.md
└── tests/
    ├── test_cubase_parser.py
    ├── test_patch_search.py
    ├── test_midi_encoding.py
    ├── test_cli_json.py
    ├── test_wsl_interop.py
    ├── test_sysex.py
    └── test_mcp_tools.py
```

This is a suggested layout, not an instruction to create empty placeholder files. Adapt if needed, and document changes.

## 7. Local installation and workflow expectations

Document **two** separate Python environments, one for the WSL agent CLI and one for Windows MIDI I/O.

### Windows prerequisites

- Roland INTEGRA-7 USB driver installed and recognized by Windows.
- INTEGRA-7 configured for Roland's USB driver mode `VENDER` when applicable (Roland uses that spelling), device reboot/reconnect as directed by Roland.
- Supported Windows Python version installed; Windows-side `mido`, `python-rtmidi` installed.
- Explicitly identified MIDI input/output port names using a real port-enumeration command.

### WSL prerequisites

- WSL2 and normal Windows executable interop enabled.
- Linux Python environment for the catalog, CLI, tests and MCP server.
- Configured absolute path or discovered path to the Windows adapter executable or Windows Python interpreter.
- Document calling a Windows executable from Bash with safe quoting, argument arrays and `wslpath`; do not rely on `cmd.exe /C` string interpolation.

Document a reproducible quickstart where an engineer can:

1. Clone repo and set up both environments.
2. Import/prepare the patch database offline.
3. Run automated unit tests.
4. `integra7 doctor` to diagnose interop and MIDI port configuration.
5. Search patches while the synth is disconnected.
6. Dry-run a patch change with exact MIDI output.
7. Connect INTEGRA-7 and list Windows MIDI ports.
8. Execute the same patch change on real hardware.
9. Register MCP server in Claude Code or Codex and use the same operation.

Include both native Windows invocation and WSL invocation examples.

## 8. Automated verification and acceptance tests

### Hardware-free tests (required for MVP)

- [ ] Tests run entirely in Linux/WSL with a mock MIDI backend.
- [ ] Full Grand 1 maps to `89/64/0` (zero-based program) and emits `B0 00 59`, `B0 20 40`, `C0 00` for channel 1.
- [ ] Studio Set Integra Preview maps to `85/0/0` but uses **Studio Set** command routing, not the generic part-select API.
- [ ] Part 2 mapped to channel 4 emits channel-4 messages, not channel-2 messages.
- [ ] Invalid channel, bank, program, part and note values are rejected.
- [ ] Ambiguous name returns multiple candidates and sends no MIDI.
- [ ] `[p2]` / `[p3]` formats, categories and duplicates import correctly.
- [ ] Search works without a Windows MIDI connection.
- [ ] Dry-run sends no bytes and prints correct planned actions.
- [ ] Windows interop launcher argument quoting works for paths with spaces and patch names containing quotes/apostrophes.
- [ ] Port opening error, timeout and disconnected-device failures return structured errors.
- [ ] Audition cannot leave a hanging MIDI note after an exception.
- [ ] Unloaded/unknown expansion requirement produces a warning or refusal according to configured policy; never a false verified success.
- [ ] CLI JSON output parses cleanly, including errors.
- [ ] MCP tool schemas and mocked tool operations are tested.

### Physical hardware tests (document; run only with available synth)

- [ ] Roland driver/device visible from Windows MIDI port enumeration.
- [ ] Windows adapter invoked from WSL with no USB passthrough.
- [ ] Actual Part 1 patch changed to Full Grand 1; verified manually or by supported readback.
- [ ] A second part with explicitly configured channel changed without unintentionally changing Part 1.
- [ ] Studio Set recall works after setting and verifying the Studio Set Control Channel.
- [ ] MIDI input/readback works with the appropriate port and documented SysEx addresses, if implemented.
- [ ] Expansion detection and switching separately tested only after experimental safety checks.

Use a testing status table in the README: `tested_offline`, `tested_windows_without_device`, `tested_on_hardware`, `not_tested`, plus date and observed result. Never automatically mark hardware tests passed because mock tests succeeded.

## 9. Explicit non-goals for the first MVP

- Building a DAW, sequencer, visual editor, audio recorder or sound synthesizer.
- Running the INTEGRA-7 USB driver inside WSL.
- Accessing the Windows audio streams from WSL.
- Auto-loading undocumented expansion SysEx in normal operation.
- Persistently overwriting user Studio Sets / user tones.
- Real-time low-latency MIDI performance from chat; MIDI audition is a convenience test, not the audio engine.
- Networked/multi-computer control, hosted services, cloud dependencies, or elaborate graphical UIs.

## 10. Definition of done

**MVP is done when all of these work:**

1. A freshly cloned repository can be installed with documented WSL and Windows setup steps.
2. Source patch data is parsed into an indexed, searchable catalog with accurate program numbering and clear provenance.
3. A user in WSL can execute `integra7 patches search ...` and `integra7 part select ... --dry-run` with clear JSON output.
4. The Windows backend can enumerate Windows MIDI devices and emit the correct bank-select/program-change sequence using the installed Windows MIDI driver, when available.
5. Unit/integration tests pass using mocks and representative source fixtures.
6. The documented physical INTEGRA-7 test can be completed without changing the architecture. If hardware is absent, it remains explicitly **unverified**.
7. Claude Code and Codex can invoke the CLI; an MCP entry point is implemented once the CLI MVP is stable.
8. README clearly explains setup, CLI usage, tests, known caveats, port routing, and expansions.

## 11. Engineering execution instructions

Implement in the following order. Avoid asking the user for incidental decisions; use the recommended defaults, explain assumptions, and proceed:

1. Survey the cited source data/docs and record relevant protocol facts. Identify ambiguities; don't copy undocumented MIDI data as fact.
2. Create the Python package and mock backend. Write MIDI byte tests before hardware I/O.
3. Implement the Cubase parser, SQLite index, search, audit and export. Include representative fixtures and integration tests.
4. Implement `integra7` CLI, config and dry-run. Make its output reliable for coding agents.
5. Implement the Windows Python adapter and WSL launcher with diagnostics. Keep the Windows device access isolated from Linux code.
6. Write complete setup documentation. Avoid any hidden manual steps; provide scripts where useful.
7. Implement the MCP stdio server, reusing the exact same service functions as the CLI.
8. Add safe, officially documented SysEx readback as time allows.
9. Leave undocumented expansion switching behind an explicit experimental flag, pending real-device validation.
10. Finish by running tests, reporting what was actually verified, and listing the **exact** commands for me to run on my own INTEGRA-7.

**Implementation priorities:** working CLI and trustworthy patch catalog > successful WSL-to-Windows MIDI handoff > clean MCP tools > readback and nuanced state handling > experimental expansion switching.

**Do not stop at a plan or scaffolding. Implement and test runnable code.** If hardware isn't present in your environment, finish the mock-tested implementation and document the smallest reproducible hardware validation procedure.
