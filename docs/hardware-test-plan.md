# Hardware test plan

None of these steps has been run on a physical INTEGRA-7 yet. Run them in
order and record the date and result in the README's testing-status table.
Stop at the first failure; each step names what to check.

Preparation: unit powered and connected by USB, Roland driver installed,
**USB Driver = VENDER**, monitoring audible, no DAW or editor holding the ports.
Save any Studio Set edits you care about first; step 7 replaces the current
Studio Set.

## 1. Windows sees the device

```powershell
& "$env:LOCALAPPDATA\integra7-conductor\venv\Scripts\python.exe" src\integra7_conductor\midi\windows_adapter.py --ports
```

Expect `INTEGRA-7` and `INTEGRA-7 CTRL` entries among inputs and outputs. Note
the exact names.

## 2. WSL reaches Windows, no USB passthrough

```bash
integra7 doctor --write-config
integra7 ports --json
```

Expect every check `ok` except possibly `part_channels` (`warn`), and
`ready_for_hardware: true`. If a configured port is not found, set the exact
name: `integra7 config set performance_port "<name>"` (also `input_port`,
`control_port`).

## 3. The unit answers SysEx

```bash
integra7 device identify --json
integra7 device state --json
```

Expect `is_integra7: true` and `device_id_matches_config: true`. If this times
out: check SYSTEM → MIDI → Rx Exclusive, the unit's Device ID
(`integra7 config set device_id 0x10` for displayed 17), then try
`integra7 config set sysex_port control`. **Record which port setting works**;
this is the open `INTEGRA-7` vs `INTEGRA-7 CTRL` question.

## 4. Read the real part channels

```bash
integra7 part channels --from-device --save --json
```

Compare with the unit's PART VIEW. This replaces the "part N = channel N"
assumption with observed values.

## 5. Change Part 1 to Full Grand 1

```bash
integra7 part select --part 1 --patch-id sn-a-preset-0001 --dry-run --json
integra7 part select --part 1 --patch-id sn-a-preset-0002 --json   # move away first
integra7 part select --part 1 --patch-id sn-a-preset-0001 --json
```

Expect `midi_messages_hex` `B0 00 59`, `B0 20 40`, `C0 00` (if part 1 is on
channel 1), `verification_status: "verified"`, and the unit's display showing
Full Grand 1 on Part 1. If the status is `sent_unverified` but the display
changed, readback needs a longer `settle_ms` or a different `sysex_port`.

## 6. A second part, without disturbing Part 1

```bash
integra7 part select --part 2 --patch "Fretless 1" --json
integra7 part show --part 1 --json
integra7 part audition --part 2 --duration-ms 600 --json
```

Expect Part 2 changed, Part 1 still `sn-a-preset-0001`, and one audible note
that stops.

## 7. Studio Set recall

```bash
integra7 device state --no-parts --json      # note studio_set_control_channel
integra7 studio-set select 2 --dry-run --json
integra7 studio-set select 2 --yes --json
integra7 studio-set select 1 --yes --json
```

Expect the display to follow and `verification_status: "verified"`. If the
unit's control channel is not 16, first run
`integra7 config set studio_set_control_channel <n>`.

## 8. Negative checks

```bash
integra7 part select --part 1 --patch "Jazz Kit" --json     # AMBIGUOUS_PATCH, nothing sent
integra7 part select --part 1 --patch-id srx06-tone-0001 --json
```

For the second command, with SRX-06 **not** loaded: note what the unit does and
what `readback.observed` reports. The result must not be `verified` either way.

## 9. Failure handling

Unplug USB and run `integra7 ports --json` and a `part select`. Expect
`PORT_NOT_FOUND` with the list of available ports, exit status 1.

## 10. Through an agent

Register the MCP server (`claude mcp add integra7 -- integra7-mcp`) and ask:
*"Find five warm electric-piano tones in the factory library; show their IDs and
bank numbers; dry-run selection of the second match on Part 2; only execute
after I select it."*

## Not covered

Expansion loading is not implemented; see `experimental-expansions.md`.
