---
name: caption-toolkit
description: Check, fix and convert SRT/WebVTT captions by reading speed (CPS) with PASS/WARN/HOLD verdicts. Use when a caption file must be speed-checked before publishing, too-fast captions extended into following gaps, or SRT converted to VTT (or back).
---

# caption-toolkit — agent skill

## Purpose

Measures every caption's reading speed in characters per second (CPS —
characters including spaces, divided by on-screen seconds) and returns a
verdict. It can also repair too-fast captions by extending them into the
silence that follows them (timing only), and convert between SRT and
WebVTT. Pure Python standard library; local only.

Verdict gates (same as Faceless QC Lite's caption check):
- `PASS` — median CPS ≤ 17 and max CPS ≤ 30 (exit 0)
- `WARN` — median CPS > 17, no HOLD rule triggered (exit 1)
- `HOLD` — median CPS > 20, **or any single caption > 30 CPS**, **or any
  caption with end ≤ start** (exit 2)

## When to use / not use

Use when:
- A caption file (`.srt` / `.vtt`) needs a pre-publish speed check.
- Too-fast captions should be extended into following gaps (`fix`).
- Converting captions between SRT and WebVTT.

Do NOT use when:
- Transcribing or generating captions — this tool only measures, repairs
  timing, and converts existing files.
- Rewriting caption text — `fix` never changes text, never moves a start,
  never shortens a caption, never overlaps the next one.
- The file has invalid captions (end ≤ start) — `fix`/`convert` refuse;
  the timings must be corrected by hand first. Do not work around this by
  editing the captions yourself unless the user asked for that.

## Commands

```bash
# Check (human report / JSON)
python3 src/caption_toolkit.py check examples/sample.srt
python3 src/caption_toolkit.py check examples/sample.srt --json

# Fix — writes FILE.fixed.srt beside the input; optional CPS target
python3 src/caption_toolkit.py fix examples/sample.srt --json
python3 src/caption_toolkit.py fix examples/sample.srt --target 20

# Convert
python3 src/caption_toolkit.py convert examples/sample.srt --to vtt --json
python3 src/caption_toolkit.py convert examples/sample.vtt --to srt
```

## Output JSON schema (`--json`)

Common fields on success: `tool` (`"caption-toolkit"`), `version`,
`command`, `warnings` (list of strings).

`check`:
- `file`, `format` (`"srt"` / `"vtt"`)
- `verdict` — `"PASS"` / `"WARN"` / `"HOLD"`
- `reason` — why the verdict is HOLD due to invalid captions, else `null`
- `caption_count`, `median_cps`, `max_cps` (nulls when no valid captions)
- `captions` — per caption: `index`, `start_s`, `end_s`, `duration_s`,
  `chars`, `cps`, `status` (`"ok"` ≤ 17 CPS, `"fast"` > 17, `"hold"` > 30),
  `text`
- `invalid_captions` — cues with end ≤ start: `start_s`, `end_s`, `chars`,
  `text` (first line)

`fix`:
- `file`, `output_file`, `target_cps`
- `changes` — per changed caption: `index`, `old_end_s`, `new_end_s`,
  `old_cps`, `new_cps`, `fully_fixed`, `blocked` (true when no gap existed;
  the caption was left unchanged and a warning is included)
- `verdict_before`, `verdict_after`, `median_cps`, `max_cps` (after values)
- `note` — the timing-only guarantee

`convert`:
- `file`, `from_format`, `to_format`, `output_file`, `caption_count`,
  `status` (`"ok"`)

On error, stdout is a single object: `{"error": "<message>"}` — for
invalid-caption refusals it also carries `invalid_captions`. Exit code is
unchanged (2). Never a traceback.

## Exit codes

- `check`: 0 = PASS, 1 = WARN, 2 = HOLD or error.
- `fix`: the exit code of the *after* verdict (0/1/2); 2 on any error.
- `convert`: 0 on success, 2 on error.
- Errors (all commands): file not found, unsupported file type, no caption
  events parsed, invalid captions present, or an invalid `--target`
  (must be a positive finite number — validated before any file is touched;
  nothing is written on error).

## Limits & honesty rules the agent must respect

- **A HOLD is a hold.** Never present a file as publishable when `check`
  returns HOLD — including when the median looks fine but one caption is
  over 30 CPS or a caption's timing is invalid.
- **Invalid captions are never silently dropped.** If the JSON contains
  `invalid_captions`, surface them; do not delete or "repair" them behind
  the user's back.
- **`fix` is timing-only.** It cannot make a badly written caption good,
  and a `blocked` change means the caption is still too fast — report it,
  don't claim the file was fixed. After fixing, re-run `check` on the
  output and report its actual verdict.
- **CPS is a proxy.** It counts characters, not words or comprehension;
  the thresholds are calibrated gates, not a guarantee of readability.
- **Conversion is lossy at the edges.** WebVTT cue settings are not
  preserved; cue identifiers are preserved where the format allows, and
  `convert` overwrites an existing file with the target name.
- Local only: the tool reads and writes files beside the input and sends
  nothing anywhere.
