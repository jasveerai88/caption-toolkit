# caption-toolkit

**Check, fix and convert SRT / WebVTT captions — from the command line, with nothing but Python.**

Captions that flash past too fast are the silent killer of retention on
faceless and captioned video. `caption-toolkit` measures every caption's
reading speed in characters per second (CPS), tells you plainly whether the
file passes, warns, or must be held — and can automatically fix too-fast
captions by extending them into the silence that already follows them.

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

# 3. Convert between formats
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
`fix` and `convert` refuse with an error and write nothing until the
timings are corrected by hand.

## Use with AI agents

Every command takes `--json`: one JSON object with the same verdicts,
per-caption rows and exit codes as the text report (errors come back as
`{"error": ...}`):

```bash
python3 src/caption_toolkit.py check examples/sample.srt --json
python3 src/caption_toolkit.py fix examples/sample.srt --json
python3 src/caption_toolkit.py convert examples/sample.srt --to vtt --json
```

Agents: read [SKILL.md](SKILL.md) first — commands, the full JSON schemas,
exit codes, and the honesty rules (a HOLD is a hold; `fix` is timing-only).

## Real run (verbatim, v0.2.0)

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

## Tests

```bash
python3 -m unittest discover -s tests -v
# Ran 28 tests — OK
```

The suite covers both directions: slow captions PASS (exit 0), a WARN-band
file exits 1, fast captions HOLD (exit 2), `fix` measurably improves CPS and
its output passes `check`, a no-gap caption is honestly reported as
unfixable, and SRT→VTT→SRT conversion round-trips timing and text. The
v0.1.1 regression tests add: zero-duration and inverted captions HOLD
instead of passing, an all-invalid file reports its invalid captions,
`fix` refuses invalid files and writes nothing, bad `--target` values
(0, negative, `nan`, `inf`) are rejected cleanly, and `fix` can never move
a caption's end earlier — even when captions overlap.

## Internal use

This tool does a real job inside its author's own production engine: it is
the caption-QC step for the **Leaked News** and **SADA — The Rooftop
Catcher** YouTube channels, where every Short's captions must pass the CPS
gate before upload. It is not a demo in search of a purpose.

## Known limits

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
