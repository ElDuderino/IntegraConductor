# MIDI protocol notes

Everything here is taken from Roland's *INTEGRA-7 MIDI Implementation*
(<https://static.roland.com/assets/media/pdf/INTEGRA-7_MI.pdf>)
unless marked as an assumption. Nothing in this file has been confirmed on a
physical unit.

## Selecting a tone on a part

Sent on the part's receive channel, as three messages in one transaction:

```text
Bn 00 mm     CC#0   Bank Select MSB
Bn 20 ll     CC#32  Bank Select LSB
Cn pp        Program Change, pp = zero-based program (Roland prints pp + 1)
```

`n` is the channel minus one. Full Grand 1 (MSB 89, LSB 64, PC 1) on channel 1 is
`B0 00 59`, `B0 20 40`, `C0 00`.

The unit ignores these when SYSTEM:MIDI *Rx Program Change* / *Rx Bank Select*
or the part's *Rx Switch*, *Rx Program Change* or *Rx Bank Select* is off.

## Bank Select map

Transcribed into `src/integra7_conductor/catalog/banks.py`.

| MSB | LSB | Programs | Group |
|---|---|---|---|
| 85 | 0 | 1–64 | Studio Set |
| 86 | 0 / 64 | 1–32 / 1–14 | User / Preset PCM Drum Kit |
| 87 | 0–1 / 64–70 | 1–128 | User (256) / Preset (896) PCM Synth Tone |
| 88 | 0 / 64 | 1–64 / 1–26 | User / Preset SN Drum Kit |
| 88 | 101 | 1–7 | ExSN6 (SN Drum) |
| 89 | 0–1 / 64–65 | 1–128 | User / Preset SN Acoustic Tone (256 each) |
| 89 | 96–100 | 17, 17, 50, 12, 12 | ExSN1–ExSN5 |
| 92 | 0, 2, 4, 7, 11, 15, 19 | 79, 12, 34, 5, 11, 21, 12 | SRX-01, 03, 05, 06, 07, 08, 09 drum kits |
| 93 | 0, 1, 2, 3 | 41, 50, 128, 128 | SRX-01 to SRX-04 tones |
| 93 | 4–6, 7–10, 11–14, 15–18, 19–22 | 312, 449, 475, 448, 414 | SRX-05 to SRX-09 tones |
| 93 | 23, 24, 26 | 100, 42, 50 | SRX-10, SRX-11, SRX-12 tones |
| 95 | 0–3 / 64–72 | 1–128 | User (512) / Preset (1109) SN Synth Tone |
| 96 | 0 | 1–19 | ExPCM drum kits |
| 97 | 0–3 | 1–128 | ExPCM tones (512) |
| 120 | 0 | 1–57 (9 kits) | GM2 Drum Kit |
| 121 | 0– | 1–128 | GM2 Tone (256) |

## Selecting a Studio Set

Bank 85/0 plus Program Change `number − 1`, sent on the **Studio Set Control
Channel** (System Common offset `00 11`: 0–15 = channel 1–16, 16 = OFF). The
configured default of 16 is an assumption about the factory setting; read the
real value with `integra7 device state`. Roland's guidance:
<https://support.roland.com/hc/en-us/articles/205926959>.

## SysEx

Manufacturer `41`, model ID `00 00 64`, device ID `10`–`1F` (displayed 17–32) or
`7F`. RQ1 = `11`, DT1 = `12`.

```text
RQ1  F0 41 dev 00 00 64 11 aa bb cc dd ss tt uu vv sum F7
DT1  F0 41 dev 00 00 64 12 aa bb cc dd data... sum F7
```

Checksum: `(128 − (sum of address and size-or-data bytes) mod 128) mod 128`.
Roland's worked example, `F0 41 10 00 00 64 12 18 00 06 00 02 60 F7`, is a unit
test. The Implementation says requests must use a block's fixed start address
and size, and that data over 256 bytes is split into packets about 20 ms apart;
this tool therefore requests whole blocks and reassembles consecutive packets.

Blocks used (read only):

| Block | Address | Size | Fields read |
|---|---|---|---|
| Setup | `01 00 00 00` | `38` | `00` Sound Mode, `04`/`05`/`06` Studio Set BS MSB / LSB / PC |
| System Common | `02 00 00 00` | `2F` | `11` Studio Set Control Channel, `29` Rx Program Change, `2A` Rx Bank Select |
| Studio Set Part *n* | `18 00 (20+n−1) 00` | `4D` | `00` Receive Channel, `01` Receive Switch, `06`/`07`/`08` Tone BS MSB / LSB / PC |

Identity Request `F0 7E dev 06 01 F7`; the reply carries Roland `41` and family
code `64 02`.

Replies are accepted only if framing, manufacturer, model, command, checksum and
(unless broadcasting) device ID all validate.

## What counts as verified

- **Part select:** after a settle delay, the part's block is read and its bank
  MSB, LSB and program must equal the request. If the block's receive channel
  differs from the channel used, the error says so.
- **Studio Set select:** Setup's Studio Set PC must equal `number − 1`.
- **Audition:** never verified; sound cannot be observed over MIDI.
- **Expansion tones:** never `verified`, since slot contents cannot be read.

## Assumptions and open questions for hardware

- Port roles: channel messages and SysEx both default to the `INTEGRA-7` port,
  with `INTEGRA-7 CTRL` available through `sysex_port = "control"`. Which port
  answers RQ1 over USB is unknown.
- Whether Setup's Studio Set PC updates immediately after a recall, and how long
  the unit needs before a part block reflects a tone change (`settle_ms`,
  default 150 ms; 500 ms after a Studio Set change).
- Whether the unit reports the new bank/program for a tone in an unloaded
  expansion.
- Exact port names produced by the Roland driver under RtMidi.

## Effect writes

`integra7 fx set` writes single bytes with DT1 into the Temporary Studio Set:
Studio Set Common (`18 00 00 xx`: reverb, chorus and master EQ switches),
Common Chorus (`18 00 04 xx`), Common Reverb (`18 00 06 xx`), Motional Surround
(`18 00 08 xx`), Master EQ (`18 00 09 xx`) and Studio Set Part
(`18 00 20+n-1 xx`). Each write is followed by an RQ1 of the whole block and
compared. The parameter table is in `services/fx.py`; nothing outside it can be
written and there is no raw SysEx facility. The type-dependent reverb and chorus
parameters (the nibbled `Parameter 1..n` values) are not exposed.
