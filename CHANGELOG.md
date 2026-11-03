# Changelog

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
