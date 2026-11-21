# Expansions: what is and is not implemented

## Implemented

- `expansion_required` on every catalog entry, from Roland's Bank Select table.
- `integra7 expansions declare …` to record what you loaded on the unit. This is
  stored as an assumption (`state: "assumed"`).
- `expansion_policy`: `warn` (default), `refuse`, `ignore`.
- `integra7 expansions plan …` checks slot limits: at most four single-slot
  expansions (SRX-01…12, ExSN1…6); ExPCM uses all four and excludes the rest.
- Tones that need an expansion are never reported `verified`.

## Not implemented: reading the slots

The published MIDI Implementation's address map (Setup, System, Temporary
Studio Set, Temporary Tone) contains no expansion-slot parameter. The Setup
block has reserved bytes, but their meaning is not documented, so they are not
interpreted. `get_expansion_slots` / `expansions status` therefore return
`unknown` or the declared assumption, never a device reading.

## Not implemented: loading expansions over SysEx

Community posts describe a message of this shape:

```text
F0 41 10 00 00 64 11 0F 00 30 00 AA BB CC DD sum F7
```

It is deliberately absent from this code base:

- The address `0F 00 30 00` is not in Roland's published address map.
- Command byte `11` is RQ1 (a data *request*) in the published protocol, yet the
  message is described as causing a load. That is behavior outside the
  specification.
- The slot-code values, expected reply or busy indication, load duration,
  behavior while loading, and ExPCM handling have not been verified here.
- Loading changes which tones the current Studio Set can play, and there is no
  verified way to capture and restore the previous slot contents.

Sources (unverified, not used for implementation):
<https://forums.rolandclan.com/viewtopic.php?p=282206>,
<https://forums.rolandclan.com/viewtopic.php?start=15&t=55157>.

## Before anyone adds it

1. With a unit attached, record what the unit and Roland's own editor exchange
   when expansions are loaded, and confirm the codes for all 19 expansions.
2. Establish which port and device ID are required, the reply or completion
   signal, and timing.
3. Determine whether the current slot contents can be read; without that, do
   not offer rollback.
4. Put it behind a config flag that is off by default, plus a per-call
   acknowledgement, plus `--dry-run`. Keep it out of the MCP tool list unless
   explicitly enabled.
5. Report the result as `sent_unverified` unless slot contents were read back.
6. Never write user Studio Set or tone memory as a side effect.
