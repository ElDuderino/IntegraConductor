# Composing and playing music on the INTEGRA-7

Field notes from building `examples/blue-conductor.json` and
`examples/last-set-at-the-blue-room.json` with the owner listening on real
hardware (2026-11-20). Read this before writing a new piece. Everything marked
**heard** was judged by a person at the unit; everything else is documented by
Roland or is an untested idea, and says so.

The agent cannot hear. Every sonic judgement here came from the listener, so
plan each session around short things they can listen to and answer.

## Workflow that worked

1. **Look before playing.** `integra7 doctor`, `integra7 device state`,
   `integra7 fx show`. Know the Studio Set, the part channels and what effects
   are already on.
2. **Search the catalog, prefer built-in SuperNATURAL tones**
   (`integra7 patches search "..." --expansion none --engine SN-A`). Expansion
   tones only sound if that pack is in one of the four slots, which cannot be
   read back; ask which are loaded and record them with
   `integra7 expansions declare`.
3. **Write a generator script, not a hand-typed score.** See
   `examples/compose_last_set.py`: chord table, per-instrument patterns, seeded
   variation, then it writes the JSON score. Edit, regenerate, replay.
4. **Dry-run, then play:** `integra7 play SCORE --dry-run`, then without.
5. **Debug by soloing:** `integra7 play SCORE --parts 1`. When something sounds
   wrong, find which part first.
6. **A/B in numbered takes.** Play two or three short solo variants back to back
   and tell the listener the order; they answer "the first one".
7. **Let the listener drive.** They can loop the piece in one terminal
   (`--loop 3 --keep-patch 1 --keep-fx`) and change patches or effects from
   another; `part select` and `fx set` are fed into the running playback.
8. **Save what they liked into the score** so it no longer depends on manual
   steps.

## Debugging a sound that is "off"

- **Read the part before blaming the tone.** A vibraphone that sounded like a
  "muted blip" was fine; the Studio Set Part had attack/decay/release offsets
  near zero (9/12/19, neutral is 64). `integra7 fx show --part N` shows
  `attack_offset`, `decay_offset`, `release_offset`; reset with
  `integra7 fx set part.N.attack_offset=0 ...`. The same tone on another part
  is a quick cross-check. **heard**
- **"No sound" may be monitoring**, not MIDI. Confirm the software path on the
  PC's own synth (`--performance-port "Microsoft GS Wavetable"`), then check
  whether the unit's display changed, then the audio path.
- **Do not assume General MIDI drum notes.** Read the kit's key map from the
  unit: Temporary Tone for the part (`sysex.temporary_tone_address(part)`),
  plus SuperNATURAL Drum Kit offset `03 00 00`, plus Note offset `00 10 00` for
  key 27 (one more per key, size `13`); the first four nibbles are the
  instrument number, named in the Parameter Guide's "SuperNATURAL Drum Inst
  List".

## Instruments

| Role | Tone | Notes |
|---|---|---|
| Acoustic bass | Ac Bass 1 `sn-a-preset-0135` | "Decent" from the first try. **heard** |
| Piano | Full Grand 1 `sn-a-preset-0001`, UprightPiano `sn-a-preset-0006` | Upright suits an old club. **heard** |
| Vibraphone | `sn-a-preset-0166` | Needs ringing notes (about 2 beats) and sustain pedal changed per chord; short notes sound choked. **heard** |
| Rhythm guitar | StandardJazz `sn-a-preset-0099` | Four to the bar, three-note voicings, very quiet (level about 60). **heard** |
| Muted trumpet | MutedTrumpet `sn-a-preset-0221` | Sparse answering fills, far back in the room. **heard** |
| Brushes | Jazz Brushes `sn-d-preset-0009` | Key map below. **heard** |
| Sticks | Jazz Kit `sn-d-preset-0007` | GM-style notes 36 kick, 38 snare, 44 pedal hi-hat, 51 ride, 49 crash worked. **heard** |
| Tenor sax | T Sax 1 Soft `sn-a-preset-0236`; ExSN2 Tenor Sax 2 `exsn2-0004` | The hardest to make convincing; see below. |

Struck and plucked instruments are the most convincing. A solo saxophone is the
least: the listener called the tones "very close but not authentic" until the
performance, not the tone, was reworked.

**Jazz Brushes key map (read from the unit):** 36 jazz kick, 37 brush slide,
38 brush tap, 39 brush slap, 40 soft tap, 41/43/45/47/48/50 brush toms,
42 brush hi-hat closed, 44 hi-hat pedal, 46 brush hi-hat open, 51 brush 18"
ride, 53 brush 20" ride, 55 brush splash, 57 brush crash, 88 applause.
A ballad pattern that worked: slide on every beat, tap and pedal hi-hat on 2
and 4, a soft tap on the swung off-beat after them, a barely audible kick on 1
and 3. Key 88 after the last chord gives the room an audience. **heard**

## Saxophone and other SuperNATURAL winds

Use a part `expression` block (`services/expression.py`); do not hand-write
controllers. Roland's documented roles for the saxes: CC1 dynamics (+vibrato),
channel aftertouch vibrato, CC16 breath noise, CC18 growl, CC19 bend mode,
CC65 portamento/glissando, CC80 staccato, CC81 fall, CC82 subtone.

- **CC1 is blowing dynamics, not vibrato.** Ramping CC1 for vibrato was an
  early mistake.
- **Make the part monophonic with legato on**, and give it a numeric bend range
  for scoops: `part.N.mono_poly=mono part.N.legato=on part.N.bend_range=2`.
  With the default bend range `tone`, pitch bend triggers the tone's
  glissando/fall instead of an ordinary bend. Put the part back to `tone` for
  chordal instruments, or only one note will sound.
- Slur by overlapping notes, tongue with a gap, re-tongue repeated pitches,
  leave room to breathe between phrases, shape each phrase with a CC1 arc,
  vibrato late and only on long notes, subtone on quiet phrases.
- Result with style `breathy_ballad_tenor`: "really close". **heard**
- Not yet judged by ear: `examples/sax-articulation-test.json`, and how the
  Fall (CC81) and SubTone (CC82) switches really behave. Ask the listener to
  run it before leaning on falls.
- If a sax still will not do, offer a lead the unit does better in the same
  style: vibes, piano trio, clarinet (the `compose_last_set.py` variants).

## Room and effects

- **Motional Surround beats the plain reverb** for a live-room feel; the
  listener preferred it. While it is on, the unit bypasses the Studio Set
  reverb and chorus, so "reverb on one instrument" means that part's
  `ambience_send`. **heard**
- **Go big.** A small room with moderate sends sounded dry, "like my head is in
  the band". What sounded "amazing": **heard**

  ```
  surround.switch=on surround.room_type=hall1 surround.room_size=large
  surround.ambience_level=127 surround.ambience_time=88
  surround.ambience_density=100 surround.depth=100
  part.N.ambience_send = 105-127   (lead about 110, far instruments 120-127)
  part.N.surround_fb   = -30 (lead) to -60 (furthest)
  ```

- **Negative `surround_fb` moves a part away from the listener.** Positive
  values, and pulling back to `room_size=medium` / `ambience_time=65`, made it
  worse. **heard**
- Spread parts with `surround_lr` (about -30 to +30) and set `pan` to match for
  when surround is off.
- A master EQ for an older recording: `low_gain=2` at 200 Hz, `mid_gain=-2` at
  2500 Hz, `high_gain=-6` at 4000 Hz.
- Effects edit the temporary Studio Set. A score's `fx` block is re-applied on
  every play, so manual tweaks need `--keep-fx` until they are written into the
  score.

## Arrangement habits that helped

- Seeded variation in velocity and timing; never uniform jitter. Lead slightly
  behind the beat (about 20 ms), bass slightly ahead (about -6 ms).
- Swing ratio about 0.66 at 132 bpm, 0.64 at 76 bpm.
- Period harmony for a 1940s ballad: sixth chords, diminished passing chords,
  ii-V turnarounds, a plagal minor (iv-minor-6) before the last chord; bass in
  two; piano left-hand shell on the change with the right hand answering a beat
  later.
- Balance (part level): lead 108-112, bass 104-110, drums 88-100, piano 84-92,
  rhythm guitar about 60, background horn about 62.
- There is no tempo map: slow into an ending by stretching the beat positions
  of the last bar in the generator (`slow_down` in `compose_last_set.py`).
- About a minute is a good length for a clip; `--loop` covers longer listening.

## Things that will trip you up

- Playback holds the MIDI port for its whole length; readback commands return
  `DEVICE_BUSY` until it ends, and live changes are not confirmed.
- An `expression` part sends sax controllers to whatever tone is on that part.
- The tool cannot hear, read expansion slots, or save a Studio Set. Edits are
  lost when another Studio Set is loaded unless saved on the unit.
- From Windows `cmd`, run `integra7 ...` inside the repository folder
  (`integra7.cmd`); the real program lives in WSL.
