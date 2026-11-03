# Changelog

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
