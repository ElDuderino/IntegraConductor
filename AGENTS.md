# Notes for coding agents

Integra7 Conductor drives a Roland INTEGRA-7 over MIDI from WSL through a Windows
adapter. `README.md` covers setup, commands and the JSON contract.

- **Asked to compose, arrange or play music, or to make something sound
  better?** Read `docs/composing-for-the-integra7.md` first. It records what a
  listener at the hardware actually approved: which tones work, how to play a
  saxophone part, the room settings, the brush kit's key map, and how to debug
  a sound that is off. Add to it when a listener confirms something new, and
  mark it as heard.
- You cannot hear the instrument. Never report that something sounds good;
  report what was sent and what was read back, and ask the listener.
- Start a session with `integra7 doctor`, `integra7 device state` and
  `integra7 fx show`; cabling and loaded expansions change between sessions.
- `verified` means a SysEx readback matched. Sending alone is `sent_unverified`.
- Protocol facts come from Roland's MIDI Implementation and Parameter Guide
  (`docs/midi-protocol.md`); write only to documented addresses, through named
  parameters. There is deliberately no raw SysEx command.
- Checks: `python -m pytest`, `ruff check .`, `mypy` (venv from
  `scripts/setup-wsl.sh`). Hardware results go in the README status table with
  a date; mock results never count as hardware results.
