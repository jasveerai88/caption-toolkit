> **Merged into [Faceless QC Lite](https://github.com/jasveerai88/faceless-qc-lite)** — as of v2.0.0 this tool ships inside the Faceless QC Lite pre-upload suite: same checks, byte-identical engine, plus one combined `suite` run across all six checks. This repo stays public for existing links; development continues there. Install the suite: `pipx install faceless-qc-lite`

# caption-toolkit

**Check, fix, lint, repair and convert SRT / WebVTT captions — from the command line, with nothing but Python.**

Captions that flash past too fast are the silent killer of retention on
faceless and captioned video. `caption-toolkit` measures every caption's
reading speed in characters per second (CPS), tells you plainly whether the
file passes, warns, or must be held — and can automatically fix too-fast
captions by extending them into the silence that already follows them.
And because machine transcription (Whisper and friends) leaves its own
structural mess — overlapping cues, flicker gaps, empty cues, nine-second
monsters — `lint` reports that mess cue by cue and `repair` cleans up
what can be cleaned up without ever touching the words.

- Pure Python 3 standard library — no dependencies, no install step
- Local only — your caption files never leave your machine
- Script-friendly exit codes: `0` = PASS, `1` = WARN, `2` = HOLD

## Thresholds

| Verdict | Rule |
|---|---|
| PASS | median CPS ≤ 17 and max CPS ≤ 30 |
| WARN | median CPS > 17 (and no HOLD rule triggered) |
| HOLD | median CPS > 20 |
| HOLD | **any single caption > 30 CPS** — even when the median is fine |
| HOLD | any caption with end ≤ start (invalid timing, cannot be measured) |

These are the same caption-speed gates used by
[Faceless QC Lite](https://github.com/jasveerai88/faceless-qc-lite),
extracted into a standalone, discoverable tool.

## Usage

```bash
# 1. Check a captions file (SRT or VTT)
python3 src/caption_toolkit.py check examples/sample.srt

# 2. Fix too-fast captions (writes sample.fixed.srt next to the input)
python3 src/caption_toolkit.py fix examples/sample.srt

# 3. Lint the structure (report only — overlaps, gaps, lengths, empty cues)
python3 src/caption_toolkit.py lint examples/messy-whisper.srt

# 4. Repair the structure (writes messy-whisper.repaired.srt; or use -o OUT)
python3 src/caption_toolkit.py repair examples/messy-whisper.srt

# 5. Convert between formats
python3 src/caption_toolkit.py convert examples/sample.srt --to vtt
python3 src/caption_toolkit.py convert examples/sample.vtt --to srt
```

`fix` only ever changes **timing**: it extends a too-fast caption's end time
into the gap before the next caption (target: 17 CPS), never moves a caption
earlier, never shortens one, never overlaps the next caption, and never
touches the text. If there is no gap, it says so and leaves that caption
unchanged. The last caption may extend freely. `--target` must be a positive
finite number — anything else (0, negative, `nan`, `inf`) is rejected with
an error before any file is touched.

Captions whose end time is at or before their start time are **invalid**:
they are never silently ignored. `check` lists them and returns HOLD;
`fix`, `repair` and `convert` refuse with an error and write nothing until
the timings are corrected by hand. `lint` reports them as a finding.

## Lint & repair — post-Whisper structural QA

`check` answers one question (reading speed). Raw transcription output
fails in other ways, so `lint` walks every cue — including empty ones,
which the CPS parser cannot even see — and reports:

| Finding | Severity | Rule |
|---|---|---|
| `overlap` | HOLD | a cue ends after the next cue starts |
| `empty-text` | HOLD | a cue with no text at all |
| `invalid-timing` | HOLD | end ≤ start — cannot be measured |
| `cps-hold` | HOLD | a single cue over 30 CPS (same gate as `check`) |
| `too-short` | WARN | under 0.8s on screen |
| `too-long` | WARN | over 7s on screen |
| `line-too-long` | WARN | a line over 42 visible chars |
| `too-many-lines` | WARN | more than 2 lines in one cue |
| `flicker-gap` | WARN | under 80ms between a cue's end and the next start |
| `cps-fast` | WARN | a single cue over 17 CPS |

The verdict uses the same scale as `check`: PASS (no findings, exit 0),
WARN (exit 1), HOLD (any HOLD-severity finding, exit 2). Cue numbers are
file order and count *every* cue, empty ones included.

`repair` then fixes — conservatively, and only these things:

- **Drops** empty cues.
- **Trims ends** so every gap to the next cue is at least 80ms (this is
  also how overlaps are fixed). An end is never trimmed below
  start + 0.4s; if that makes a fix impossible, the cue is left exactly
  as it was and reported `NOT fixed` — never silently forced.
- **Splits** a cue over 7s (or over 2 lines) at a word boundary,
  dividing its span proportionally to each part's character count, with
  an 80ms gap between parts.

Repair **never adds, removes or rewords caption text** — a split keeps
every word, in order; only line breaks inside a split cue may move. It
never overwrites its input (default output: `FILE.repaired.srt` /
`.vtt`; `-o` chooses the name), it is idempotent (repairing its own
output changes nothing), and its exit code is the lint verdict of the
repaired file, so a file that still has problems never exits 0.
Repair is structural only — for reading speed, run `fix`.

## Use with AI agents

Every command takes `--json`: one JSON object with the same verdicts,
per-caption rows and exit codes as the text report (errors come back as
`{"error": ...}`):

```bash
python3 src/caption_toolkit.py check examples/sample.srt --json
python3 src/caption_toolkit.py fix examples/sample.srt --json
python3 src/caption_toolkit.py lint examples/messy-whisper.srt --json
python3 src/caption_toolkit.py repair examples/messy-whisper.srt --json
python3 src/caption_toolkit.py convert examples/sample.srt --to vtt --json
```

Agents: read [SKILL.md](SKILL.md) first — commands, the full JSON schemas,
exit codes, and the honesty rules (a HOLD is a hold; `fix` is timing-only).

## Real run (verbatim)

Input — `examples/sample.srt`, whose first caption crams 44 characters into
1 second:

```text
$ python3 src/caption_toolkit.py check examples/sample.srt
caption-toolkit check — sample.srt
  #1 00:00:00.000 --> 00:00:01.000 | 44 chars / 1.00s = 44.0 CPS  <-- HOLD (>30 CPS)
  #2 00:00:05.000 --> 00:00:09.000 | 34 chars / 4.00s = 8.5 CPS
  #3 00:00:10.000 --> 00:00:14.000 | 26 chars / 4.00s = 6.5 CPS
Captions: 3 | median 8.5 CPS | max 44.0 CPS
Verdict: HOLD (PASS median <=17, WARN median >17, HOLD median >20 or any >30)
(exit code: 2)
```

```text
$ python3 src/caption_toolkit.py fix examples/sample.srt
caption-toolkit fix — sample.srt -> sample.fixed.srt
  #1: end 00:00:01.000 -> 00:00:02.589 | 44.0 -> 17.0 CPS
Verdict before: HOLD | after: PASS (median 8.5 CPS, max 17.0 CPS)
Note: timing only — no caption text was changed, and no caption was moved earlier or shortened.
(exit code: 0)
```

```text
$ python3 src/caption_toolkit.py check examples/sample.fixed.srt
caption-toolkit check — sample.fixed.srt
  #1 00:00:00.000 --> 00:00:02.589 | 44 chars / 2.59s = 17.0 CPS
  #2 00:00:05.000 --> 00:00:09.000 | 34 chars / 4.00s = 8.5 CPS
  #3 00:00:10.000 --> 00:00:14.000 | 26 chars / 4.00s = 6.5 CPS
Captions: 3 | median 8.5 CPS | max 17.0 CPS
Verdict: PASS (PASS median <=17, WARN median >17, HOLD median >20 or any >30)
(exit code: 0)
```

```text
$ python3 src/caption_toolkit.py convert examples/sample.srt --to vtt
caption-toolkit convert — sample.srt (srt) -> sample.vtt (vtt) | 3 captions
(exit code: 0)
```

Lint & repair (verbatim, v0.3.0) — input `examples/messy-whisper.srt` is
a deliberately broken transcription: cue #2 starts before cue #1 ends,
cue #3 follows cue #2 by only 50ms, cue #4 is empty, and cue #5 sits on
screen for 9 seconds:

```text
$ python3 src/caption_toolkit.py lint examples/messy-whisper.srt
caption-toolkit lint — messy-whisper.srt
  #1 [HOLD] overlap: ends 00:00:02.600, caption #2 starts 00:00:02.400 — 200ms overlap
  #2 [WARN] flicker-gap: gap to caption #3 is 50ms (minimum 80ms)
  #4 [HOLD] empty-text: caption has no text
  #5 [WARN] too-long: 9.00s on screen (maximum 7s)
  #5 [WARN] line-too-long: line 1 is 87 chars (maximum 42)
Findings: 5 (2 HOLD, 3 WARN) across 6 captions
Verdict: HOLD
(exit code: 2)
```

```text
$ python3 src/caption_toolkit.py repair examples/messy-whisper.srt
caption-toolkit repair — messy-whisper.srt -> messy-whisper.repaired.srt
  #1: end 00:00:02.600 -> 00:00:02.320 — overlap with caption #2 (200ms)
  #2: end 00:00:04.900 -> 00:00:04.870 — gap to caption #3 was 50ms (minimum 80ms)
  #4: dropped — empty text
  #5: split into 2 captions — 9.00s on screen (maximum 7s)
Result: 6 captions written to messy-whisper.repaired.srt | lint after repair: PASS
Note: text preserved word-for-word — repairs only drop empty cues, trim ends, and split long cues at word boundaries.
(exit code: 0)
```

```text
$ python3 src/caption_toolkit.py lint examples/messy-whisper.repaired.srt
caption-toolkit lint — messy-whisper.repaired.srt
Findings: none across 6 captions
Verdict: PASS
(exit code: 0)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
# Ran 50 tests — OK
```

The suite covers both directions: slow captions PASS (exit 0), a WARN-band
file exits 1, fast captions HOLD (exit 2), `fix` measurably improves CPS and
its output passes `check`, a no-gap caption is honestly reported as
unfixable, and SRT→VTT→SRT conversion round-trips timing and text. The
v0.1.1 regression tests add: zero-duration and inverted captions HOLD
instead of passing, an all-invalid file reports its invalid captions,
`fix` refuses invalid files and writes nothing, bad `--target` values
(0, negative, `nan`, `inf`) are rejected cleanly, and `fix` can never move
a caption's end earlier — even when captions overlap. The v0.3.0 tests
add: every lint rule fires (and the clean file fires none), lint counts
the empty cue `check` cannot see, JSON and text modes agree, `repair`
fixes the bundled messy example down to a lint PASS with every word
preserved, **repair is idempotent** (its own output repairs to a
byte-identical file with zero changes), an unfixable overlap is left
untouched and reported, a split tiles the original span with an 80ms
gap, and repair refuses invalid files, an all-empty file, a bad output
suffix, and overwriting its own input.

## Internal use

This tool does a real job inside its author's own production engine: it is
the caption-QC step for the **Leaked News** and **SADA — The Rooftop
Catcher** YouTube channels, where every Short's captions must pass the CPS
gate before upload. It is not a demo in search of a purpose.

## Known limits

- `lint` and `repair` work in file order and expect cues to be listed
  chronologically; a cue that starts before its predecessor is treated
  as an overlap, not re-sorted.
- `repair` splits only at word boundaries: a single-word cue longer
  than 7s is reported `NOT fixed`, never cut mid-word. Line breaks
  inside a split cue are re-wrapped at 42 chars; unsplit cues keep
  their original lines exactly.
- `convert` writes to the same folder and will overwrite an existing file
  with the target name (e.g. converting `a.vtt --to srt` replaces `a.srt`).
- WebVTT cue settings (e.g. `align:start position:0%`) are not preserved on
  conversion; cue identifiers are preserved SRT↔VTT where the format allows.
- CPS counts characters, not words — the standard proxy for reading speed,
  and the same measure the thresholds above were calibrated with.

## Privacy

What it touches: only the caption file you point it at (and, for `fix` /
`convert`, the output file it writes beside it). What it stores: nothing.
What it sends: nothing — there is no network code in this tool.

## Support

If this saves you a re-render, consider sponsoring:
**https://github.com/sponsors/jasveerai88**

## Licence

MIT — see [LICENSE](LICENSE).
