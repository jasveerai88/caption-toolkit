---
name: caption-toolkit
description: Check, fix, lint, repair and convert SRT/WebVTT captions — reading speed (CPS) checks with PASS/WARN/HOLD verdicts, structural lint for post-Whisper files (overlaps, flicker gaps, empty cues, long cues/lines), and conservative repair (drop empty cues, trim ends, split long cues — text never reworded). Use when a caption file must be speed-checked before publishing, too-fast captions extended into following gaps, raw transcription output structurally cleaned, or SRT converted to VTT (or back).
---

# caption-toolkit — agent skill

## Purpose

Measures every caption's reading speed in characters per second (CPS —
characters including spaces, divided by on-screen seconds) and returns a
verdict. It can also repair too-fast captions by extending them into the
silence that follows them (timing only), and convert between SRT and
WebVTT. Pure Python standard library; local only.

`lint` / `repair` add structural QA for raw transcription output:
`lint` reports per-cue findings (overlap, flicker-gap under 80ms,
empty-text, invalid-timing, too-short under 0.8s, too-long over 7s,
line-too-long over 42 visible chars, too-many-lines over 2, and the CPS
gates per cue) under the same PASS/WARN/HOLD scale; `repair` drops empty
cues, trims ends to restore an 80ms minimum gap, and splits over-long
cues at word boundaries — never adding, removing or rewording text.

Verdict gates (same as Faceless QC Lite's caption check):
- `PASS` — median CPS ≤ 17 and max CPS ≤ 30 (exit 0)
- `WARN` — median CPS > 17, no HOLD rule triggered (exit 1)
- `HOLD` — median CPS > 20, **or any single caption > 30 CPS**, **or any
  caption with end ≤ start** (exit 2)

## When to use / not use

Use when:
- A caption file (`.srt` / `.vtt`) needs a pre-publish speed check.
- Too-fast captions should be extended into following gaps (`fix`).
- Raw transcription output (Whisper etc.) needs a structural report
  (`lint`) or a conservative structural cleanup (`repair`).
- Converting captions between SRT and WebVTT.

Do NOT use when:
- Transcribing or generating captions — this tool only measures, repairs
  timing/structure, and converts existing files.
- Rewriting caption text — `fix` never changes text, never moves a start,
  never shortens a caption, never overlaps the next one; `repair` never
  adds, removes or rewords text either (it drops *empty* cues, trims
  ends, and splits long cues at word boundaries).
- The file has invalid captions (end ≤ start) — `fix`/`repair`/`convert`
  refuse; the timings must be corrected by hand first. Do not work around
  this by editing the captions yourself unless the user asked for that.

## Commands

```bash
# Check (human report / JSON)
python3 src/caption_toolkit.py check examples/sample.srt
python3 src/caption_toolkit.py check examples/sample.srt --json

# Fix — writes FILE.fixed.srt beside the input; optional CPS target
python3 src/caption_toolkit.py fix examples/sample.srt --json
python3 src/caption_toolkit.py fix examples/sample.srt --target 20

# Lint — report only; writes nothing
python3 src/caption_toolkit.py lint examples/messy-whisper.srt
python3 src/caption_toolkit.py lint examples/messy-whisper.srt --json

# Repair — writes FILE.repaired.<same format> unless -o names the output
python3 src/caption_toolkit.py repair examples/messy-whisper.srt
python3 src/caption_toolkit.py repair examples/messy-whisper.srt -o clean.srt --json

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

`lint`:
- `file`, `format`, `verdict` (PASS = no findings; WARN = findings, none
  HOLD-severity; HOLD = any HOLD-severity finding)
- `caption_count` — every cue in file order, **including empty ones**
  (this differs from `check`, whose parser cannot see empty cues)
- `finding_count`, `hold_count`, `warn_count`
- `findings` — per finding: `index` (file order), `rule` (`overlap`,
  `empty-text`, `invalid-timing`, `cps-hold`, `too-short`, `too-long`,
  `line-too-long`, `too-many-lines`, `flicker-gap`, `cps-fast`),
  `severity` (`"HOLD"` / `"WARN"`), `start_s`, `end_s`, `message`,
  `detail` (rule-specific numbers: `overlap_ms` / `gap_ms` +
  `next_index`, `duration_s`, `line` + `chars`, `lines`, `cps`)

`repair`:
- `file`, `format`, `output_file`, `output_format`
- `caption_count_before`, `caption_count_after`
- `changes` — per change, `index` = the cue's position in the INPUT
  file, `action` one of:
  - `dropped-empty` (an empty cue was removed)
  - `trimmed-end` — with `old_end_s`, `new_end_s`, `next_index`,
    `gap_ms` (negative = it was an overlap), `reason` (`"overlap"` /
    `"gap"`)
  - `split` — with `into` (part count), `reason`, `parts`
    (`start_s` / `end_s` per part)
  - `unfixable` — with `reason`; the cue was left byte-for-byte as it was
- `remaining_findings` — lint findings of the repaired file (same shape
  as `lint`'s `findings`; indices now refer to the OUTPUT file)
- `verdict_after` — the lint verdict of the repaired file; the exit code
  matches it
- `note` — the word-for-word text-preservation guarantee

`convert`:
- `file`, `from_format`, `to_format`, `output_file`, `caption_count`,
  `status` (`"ok"`)

On error, stdout is a single object: `{"error": "<message>"}` — for
invalid-caption refusals it also carries `invalid_captions`. Exit code is
unchanged (2). Never a traceback.

## Exit codes

- `check`: 0 = PASS, 1 = WARN, 2 = HOLD or error.
- `fix`: the exit code of the *after* verdict (0/1/2); 2 on any error.
- `lint`: 0 = PASS (no findings), 1 = WARN, 2 = HOLD or error.
- `repair`: the exit code of the lint verdict *after* repair (0/1/2);
  2 on any error. A successful repair can therefore still exit 1 or 2
  when findings it does not fix remain (e.g. CPS speed — that is `fix`'s
  job — or an unfixable overlap).
- `convert`: 0 on success, 2 on error.
- Errors (all commands): file not found, unsupported file type, no caption
  events parsed, invalid captions present, or an invalid `--target`
  (must be a positive finite number — validated before any file is touched;
  nothing is written on error). `repair` additionally errors when the
  output would overwrite the input, the `-o` name does not end in
  `.srt`/`.vtt`, or every caption in the file is empty.

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
- **`repair` never rewords.** It drops empty cues, trims ends, and splits
  long cues at word boundaries (every word preserved, in order; only a
  split cue's line breaks may move). An `unfixable` change entry means
  the cue was left exactly as it was — surface it, never describe the
  file as fully repaired while `remaining_findings` is non-empty.
  Repair is idempotent: running it on its own output reports no changes.
- **Cue numbering differs by command.** `check` numbers only the cues its
  parser can measure; `lint`/`repair` number every cue in file order,
  including empty ones — so the same cue can carry different indices in
  different commands' output. Say which command produced an index when
  you quote one.
- **CPS is a proxy.** It counts characters, not words or comprehension;
  the thresholds are calibrated gates, not a guarantee of readability.
- **Conversion is lossy at the edges.** WebVTT cue settings are not
  preserved; cue identifiers are preserved where the format allows, and
  `convert` overwrites an existing file with the target name.
- Local only: the tool reads and writes files beside the input and sends
  nothing anywhere.
