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
| Sticks | Jazz Kit `sn-d-preset-0007` | GM-style notes 36 kick, 38 snare, 44 pedal hi-hat, 51 ride, 49 crash worked. For medium swing with surround off (level 114): kick about 90 on one and three and 62 on two and four, "magic"; a feathered kick at 26-40 went unheard. **heard** |
| Tenor sax | T Sax 1 Soft `sn-a-preset-0236`; ExSN2 Tenor Sax 2 `exsn2-0004` | The hardest to make convincing; see below. |

**Vibraphone at faster tempos** (`examples/compose_half_past_blue.py`, 138 bpm,
Vibes Soft `sn-a-preset-0169`):

- Mallet rolls written as repeated strokes, about 11 a second (5 per beat at
  138 bpm), pedal down, first stroke accented and the rest 16 lower and
  swelling, spaced evenly in real time (undo the player's swing with
  `unswung`): "perfect". **heard**
- The ballad recipe (every note ringing 2 beats, pedal held until the next
  chord) made the notes of an eighth-note line clash, "like harmonics are
  clashing because of the long sustain". **heard**
- The fix: pedal up except under rolls and the last chord, each note ringing
  1.5 beats (1 below C4) and stopped when a note a step away or the same note
  is struck. "Clashing is basically gone ... sounds really good". **heard**
- With vibes 94, bass 108, piano 86 (comping velocities near 58) and drums 92,
  the listener heard only bass and vibes and barely noticed the piano. **heard**

- A piano that sounded "slightly dischordant" under the vibes was the notes,
  not the tone: voicings holding a note a semitone or minor ninth from the
  melody (D under Eb on C minor, F under F# on Ab7), the lead dropping into the
  piano's octave, and vibes notes ringing into the next chord. Removing those
  notes, moving the piano above the low phrase and damping the vibes when a
  chord a semitone away lands: "a lot cleaner". **heard**

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
- **Register and plain playing beat the expression layer** (T Sax 1 Soft, four
  solo takes of one phrase, 104 bpm). The listener said the sax in a full tune
  "still just sounds bad" although the same tone played from a keyboard around
  middle C sounds "really good". Of: (1) `breathy_ballad_tenor` at D4-D5,
  (2) plain notes at D4-D5, each attacked with a gap (length x 0.85), velocity
  about 100, no controllers, (3) `warm_jazz_tenor` with every note tongued,
  (4) the same as 2 an octave lower (D3-D4): take 4 "sounded literally a
  million times better". So keep a tenor between about D3 and D4, and try
  plain, firmly struck, separately attacked notes before the expression block.
  Not yet separated: whether the expression layer is fine in the low register.
  **heard**
- That recipe applied to the tenor in a full tune (`examples/velvet-hour.json`:
  lines dropped an octave to Bb2-D4, no `expression` block, length x 0.85,
  velocity 78-110, part still mono/legato): "that's it, it sounds literally a
  million times better". The same change to the tenor lead of the 76 bpm
  ballad (`compose_last_set.py`, big surround room left on): "so much
  better". **heard**
- Not yet judged by ear: `examples/sax-articulation-test.json`, and how the
  Fall (CC81) and SubTone (CC82) switches really behave. Ask the listener to
  run it before leaning on falls.
- If a sax still will not do, offer a lead the unit does better in the same
  style: vibes, piano trio, clarinet (the `compose_last_set.py` variants).

## Acid house and techno (`examples/compose_prism_acid.py`, 2026-11-21)

The Prism promo soundtrack (128 bpm, A minor) moved from firmware emulations to
the unit. The generator reads its notes from `prism_score.py` in the
Aretas3DAssets repository.

- **TR drums without SRX-08 or ExPCM:** SRX-05 "All TR Menu" `srx05-drum-0034`
  holds three machines in one kit (key names read from the unit): 36-50 TR-707,
  51-78 TR-808, 79-103 TR-909. Putting the same kit on three parts (kick, hats,
  clap/snare/crash) gives each its own level and reverb send.
- **Pick kicks by length, not by name.** 808 kick 1 (key 51) sounded "poppy",
  wanting "more sustain and low end oomph". **heard** Measured from a recording
  (time to fall 20 dB; share of energy at 30-80 Hz): 707 kicks 36/37 48 ms, 63%;
  808 kicks 51-53 about 40 ms; 808 kick 54 437 ms, 93%; 808 kick 55 over 1 s,
  98%; 909 kicks 79/80/81 36/157/203 ms. Key 54 with key 51 layered at 0.55 of
  its velocity, part level 106: accepted ("everything else is great now").
  **heard**
- **303 line:** SuperNATURAL synth TB Bass 2 `sn-s-preset-0687` (one saw,
  resonant low-pass, mono, legato), part `mono_poly=mono legato=on`. A slide is
  an overlapping note (1.3 sixteenths long) with CC65 at 127 just before the
  note slid into and 0 before any other. The tone ignores velocity, so an
  accent is CC11 (unaccented steps at 0.78) plus 12 more on CC74. Cutoff and
  resonance sweeps are CC74 and CC71. "Pretty good". **heard**
- CC74, CC71 and CC65 change the Studio Set Part's cutoff offset, resonance
  offset and portamento switch (64 = the tone's own value): sent at level 0 and
  read back from the part block (offsets `13`, `14`, `10`). Reset them at the
  end of a score or the part stays filtered.
- **Preset leads carry their own delay,** which does not follow the tempo.
  Stn MG Lead `sn-s-preset-0879` on E5-A5 sounded "like a squeaky horn"; Reso
  Juno `sn-s-preset-0926` on the lead and on two echo parts: "the reverb is way
  off beat and throws me off". **heard** Read the tone's MFX type before using
  it (SuperNATURAL Synth Tone offset `00 02 00`, first byte): the leads and
  most SEQ tones read 34-36, basses 31-32, SEQ 10 `sn-s-preset-0556` and
  Trance Key 1 read 1. That 34-36 are delays is from memory of Roland's effect
  list, not checked against the Parameter Guide.
- Of the three machines, played one after another, the 707 version was
  preferred: 707 kick (key 36) with the long 808 kick (key 54) under it at 0.9
  of its velocity, 707 snare, clap, hats, crash and ride. "The un tss un tss in
  that 707 is pretty sick". It is the generator's default. **heard**
- **Check what the listener misses against the source, per beat.** They missed
  "a crash cymbal or something on every kick" from the original. It was the
  ride on every beat after the drop: in the original the highs (5-14 kHz) on
  the beat rise 8.5 dB at the drop; ours rose 2.5 dB with the 707 ride (key 50)
  at velocity 60. At velocity 122 they rise 17 dB and match the open hats.
  Measured, not yet heard.
- The original is far wetter than the first translation, as the listener
  suspected ("super heavy delay / hall"): about a 6 s hall with sends of 0.3
  to 0.85 and a dotted-eighth ping-pong delay on acid, lead and clap. Ours now
  repeats the acid line a dotted eighth and a quarter-and-a-half later on two
  quiet parts (levels 46 and 34, panned left and right) and uses reverb sends
  acid 60, clap 95, pad 100, lead 120, hats 28. Not yet heard.
- **Layered kicks can cancel; measure the layer, do not blame the reverb.** The
  wetter version with the loud ride was "sounding good", but "the kick low end
  is scooped out by that reverb ... the deep thump is basically gone". Moving
  the acid echoes up an octave, ducking them on the kick and cutting the acid
  reverb send did not help. A recording showed 4.5 dB less at 30-70 Hz than the
  approved 808 take, from bar 1 on, so it was the kick itself: the 707 kick
  (66 Hz) partly cancels the long 808 kick (50 Hz). At 30-70 Hz: 808 kick 54
  alone at velocity 127, 14.2 dB; with the 707 kick at 127, 12.4; with the 707
  at 90, 13.0; at velocity 114 under the 707 at 127, 10.5. With key 54 at 127,
  the 707 kick at 0.7 of it and the kick part at level 127: "yeah that's really
  good now". **heard**
- That approved version (`examples/prism-acid.json`): 707 kit, ride at velocity
  122, acid echoes a dotted eighth and two dotted eighths late, an octave up,
  levels 46 and 34, ducked 0.85 on each kick; reverb `hall2` with sends acid 42,
  clap 95, pad 100, lead 120, hats 28; SEQ 10 lead with eighth-note echoes;
  levels kick 127, hats 122, clap 112, acid 90, pad 80, lead 76. **heard**
- The 707 hats ignore CC74 (the 808 hats follow it), so the "door" also scales
  hat velocities down to 0.2 in bar 1. Not judged on its own.

## Room and effects

- **Motional Surround beats the plain reverb** for a live-room feel; the
  listener preferred it. While it is on, the unit bypasses the Studio Set
  reverb and chorus, so "reverb on one instrument" means that part's
  `ambience_send`. **heard**
- **But it can bury the rhythm section.** In the 138 bpm vibes quartet
  (`examples/half-past-blue.json`) with the big-hall settings below, the
  listener could not hear the piano or drums even after raising their levels;
  with `surround.switch=off` (plain reverb `hall2`, vibes `reverb_send` 127,
  the others 10-25) "I can hear everything clearly", "sounds a lot better". The big room was approved
  on a 76 bpm ballad; for a faster, busier tune start with surround off. **heard**
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
- Three-note answering phrases in the lead's one-and-a-half-beat gaps did not
  work, on the comping piano's right hand ("we're interrupting the piano vibe")
  or on a jazz guitar ("too short to be meaningful ... interrupts the vibe
  continuity"); they were removed. An answer needs real room, as the muted
  trumpet has in the ballad. **heard**
- A break filled with snare only (three triplets, then a six-stroke ruff
  growing into the last chord, kick underneath): "great", once brought down
  from velocities 66-118 (see `compose_half_past_blue.py`). **heard**
- A six-piece at 104 bpm with surround off (`examples/velvet-hour.json`,
  from `compose_velvet_hour.py`): muted trumpet as a lead (`warm_jazz_tenor`,
  intensity 0.8, no subtone/scoops/falls) trading whole two-bar phrases with
  T Sax 1 Soft, then the two in sixths; upright piano taking the bridge with
  no pedal; trumpet 106, sax 100, piano 98, bass 102, guitar 66, brushes 108.
  First listen, as a whole: "Wow that was really good". No detail judged
  yet. **heard**
- Balance with Motional Surround off, medium swing quartet
  (`examples/half-past-blue.json`): vibes 94, piano 102 (comping velocity about
  70), bass 102, drums 114. "Basically perfect". **heard**
- Balance with the big surround room, ballad (part level): lead 108-112, bass 104-110, drums 88-100, piano 84-92,
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
