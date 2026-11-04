# Changelog

## v0.3.0 — 2026-11-04

Post-Whisper structural QA: two new commands, `lint` and `repair`.

- **`lint FILE` (report-only)** — per-cue structural findings with
  severities, under the same PASS / WARN / HOLD verdict scale and exit
  codes as `check`: `overlap` (HOLD), `empty-text` (HOLD),
  `invalid-timing` (HOLD), `cps-hold` (a cue over 30 CPS, HOLD),
  `too-short` (< 0.8s), `too-long` (> 7s), `line-too-long` (> 42 visible
  chars), `too-many-lines` (> 2 lines), `flicker-gap` (< 80ms to the
  next cue), `cps-fast` (> 17 CPS). Lint numbers cues in file order and
  counts **every** cue — including empty-text cues, which the `check`
  parser skips entirely (that blind spot is why lint exists).
- **`repair FILE [-o OUT]`** — conservative, text-preserving repairs
  only: drop empty cues; trim ends so every gap to the next cue is at
  least 80ms (also fixing overlaps), never below start + 0.4s — an
  impossible trim is reported `NOT fixed` and the cue left untouched;
  split a cue over 7s or over 2 lines at a word boundary, dividing its
  span proportionally to character counts with 80ms between parts.
  Caption text is never added, removed or reworded (a split keeps every
  word in order; only its line breaks may move). Repair never
  overwrites its input, refuses invalid-caption files like
  `fix`/`convert` (nothing written), prints a per-cue change log, and
  exits with the lint verdict of the repaired file. **Idempotent:**
  repairing its own output reports no changes and writes a
  byte-identical file — pinned by a test.
- Both commands support `--json` with the v0.2.0 conventions (one
  object, findings/changes as arrays, `{"error": ...}` objects, same
  exit codes).
- New example `examples/messy-whisper.srt` — a deliberately broken
  transcription (overlap, 50ms flicker gap, empty cue, 9-second cue)
  used for the README's verbatim lint + repair runs.
- One design fix during development: the greedy split plan could leave
  a sub-0.4s tail part on line-driven splits; a character-balanced plan
  is now tried before a cue is reported unsplittable.
- Tests: 50 total (was 28) — every lint rule both directions, JSON/text
  agreement, word-preservation and span-tiling of splits, the
  idempotence test, unfixable-overlap, refusal and `-o` validation
  tests, and VTT lint/repair coverage.

## v0.2.0 — 2026-11-03

Agent-ready release (no behaviour change to the text reports):

- **`--json` on all three commands** (`check`, `fix`, `convert`): one
  JSON object with the same verdicts and details as the text report —
  per-caption CPS rows with statuses, invalid captions, fix changes with
  before/after verdicts, conversion results — plus `warnings`. Exit codes
  unchanged; errors in `--json` mode are `{"error": "..."}` (invalid-
  caption refusals also carry the `invalid_captions` list) with the same
  exit code — never a traceback, never plain text.
- **`SKILL.md`** added at the repo root for AI coding agents: purpose,
  when to use / not use, exact commands, the output JSON schemas, exit
  codes, and the honesty rules (a HOLD is a hold; invalid captions are
  never silently dropped; `fix` is timing-only).
- README gained a short "Use with AI agents" section.
- Tests added for the JSON output (parses, verdicts agree with text mode
  on PASS and HOLD files, invalid captions surface in JSON, fix reports
  changes, JSON error objects on missing file and bad `--target`); suite
  is now 28 tests.

## v0.1.1 — 2026-11-03

Bug-fix release from the owner's bug-free production gate audit. No new
features; every fix has a regression test (21 tests total, was 10).

- **Invalid captions are no longer silently dropped.** A cue with text
  whose end time is ≤ its start time used to vanish in the parser, so
  `check` could certify a broken file as PASS. The parser now collects
  invalid cues separately: `check` lists them and returns HOLD (exit 2);
  `fix` and `convert` refuse with an error and write nothing. A file
  whose captions are all invalid now reports those captions instead of
  the misleading "no caption events parsed".
- **`fix --target` is validated up front.** `--target 0` and
  `--target nan` crashed with tracebacks, and `--target -5` wrote a
  corrupt file (ends moved before starts) while claiming it "could not
  extend". Non-positive or non-finite targets (including `inf`) now get
  a clean `ERROR:` and exit 2 before any file is touched. Inside
  `fix_captions`, an end may now only ever move later — never earlier
  than its original end, never to ≤ its start — enforced mechanically
  and asserted.
- **Docs:** README real-run commands now use the real
  `examples/sample.srt` paths (they failed verbatim from the pack root)
  and were re-run verbatim as proof; the thresholds table now states
  explicitly that any single caption > 30 CPS is a HOLD, and documents
  the invalid-caption rule.

## v0.1.0 — 2026-11-03

First release.

- `check FILE.srt|vtt` — per-caption CPS report with median/max and a
  PASS / WARN / HOLD verdict (exit 0 / 1 / 2). Thresholds: WARN median
  > 17 CPS; HOLD median > 20 CPS or any single caption > 30 CPS.
- `fix FILE` — writes `FILE.fixed.srt`, extending too-fast captions into
  the following gap toward a 17 CPS target (millisecond-ceiled so the
  rendered file really lands at or under target). Timing only: text,
  start times and ordering are never changed; unfixable captions (no gap)
  are reported, not silently left.
- `convert FILE.srt --to vtt` and `convert FILE.vtt --to srt` — format
  conversion preserving timing, text and (for VTT) cue identifiers.
- 10 stdlib-unittest tests covering PASS, WARN, HOLD, fix improvement,
  blocked fix, VTT input, and convert round-trip.
- Pure Python standard library; local only; MIT licence.
