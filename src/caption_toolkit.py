#!/usr/bin/env python3
"""caption-toolkit — check, fix and convert SRT / WebVTT captions.

Pure Python standard library. Local only: no network, no uploads, no accounts.

Caption speed is measured in characters per second (CPS), counting the
caption text with spaces (newlines collapsed to one space), divided by the
on-screen duration in seconds.

Thresholds (same gates as Faceless QC Lite's caption check):
  - PASS : median CPS <= 17 and max CPS <= 30
  - WARN : median CPS > 17 (and not HOLD)
  - HOLD : median CPS > 20 OR any single caption > 30 CPS

Exit codes for `check`: 0 = PASS, 1 = WARN, 2 = HOLD.
File / parse errors print ``ERROR: ...`` and return 2 (never a pass).

Captions whose end time is <= their start time are INVALID: they are
never silently dropped. `check` lists them and returns HOLD (exit 2);
`fix` and `convert` refuse (exit 2, nothing written) until they are
corrected by hand.

Commands:
  check FILE.srt|FILE.vtt
  fix FILE.srt|FILE.vtt [--target CPS]   (writes FILE.fixed.srt)
  convert FILE.srt --to vtt
  convert FILE.vtt --to srt
"""
import argparse
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.1.1"

WARN_CPS = 17.0
HOLD_MEDIAN_CPS = 20.0
HOLD_MAX_CPS = 30.0
DEFAULT_FIX_TARGET_CPS = 17.0

_TS_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)


def ts_to_sec(ts):
    """'01:02:03,500' / '02:03.5' -> seconds (float)."""
    ts = ts.replace(",", ".")
    parts = [float(x) for x in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def sec_to_ts(sec, sep):
    """Seconds -> 'HH:MM:SS<sep>mmm' where sep is ',' (SRT) or '.' (VTT)."""
    if sec < 0:
        sec = 0.0
    total_ms = int(round(sec * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


@dataclass
class Caption:
    start: float
    end: float
    lines: list = field(default_factory=list)
    identifier: str = ""

    @property
    def text(self):
        return "\n".join(self.lines)

    @property
    def duration(self):
        return self.end - self.start

    @property
    def char_count(self):
        # Strip markup tags, collapse newlines to one space (reference logic).
        plain = re.sub(r"<[^>]+>", "", self.text)
        return len(plain.replace("\n", " ").strip())

    @property
    def cps(self):
        if self.duration <= 0:
            return float("inf")
        return self.char_count / self.duration


def parse_captions_detailed(path):
    """Parse an .srt or .vtt file into (valid, invalid) Caption lists.

    A cue with text whose end time is <= its start time is INVALID: it is
    collected in the second list, never silently dropped, so callers can
    report it instead of certifying a broken file.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
    valid = []
    invalid = []
    # Split into blocks on blank lines; works for both SRT and VTT.
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        ts_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                ts_idx = i
                break
        if ts_idx is None:
            continue  # WEBVTT header, NOTE blocks, STYLE blocks, numbers-only leftovers
        m = _TS_RE.search(lines[ts_idx])
        if not m:
            continue
        start, end = ts_to_sec(m.group(1)), ts_to_sec(m.group(2))
        identifier = ""
        if ts_idx > 0:
            before = lines[ts_idx - 1].strip()
            # SRT cue numbers are not identifiers; VTT identifiers are kept.
            if not before.isdigit():
                identifier = before
        body = lines[ts_idx + 1:]
        if body:
            cap = Caption(start=start, end=end, lines=body,
                          identifier=identifier)
            if end > start:
                valid.append(cap)
            else:
                invalid.append(cap)
    return valid, invalid


def parse_captions(path):
    """Parse an .srt or .vtt file into a list of valid Caption objects.

    Invalid cues (end <= start) are excluded here; use
    parse_captions_detailed() when they must be reported (the CLI does).
    """
    valid, _invalid = parse_captions_detailed(path)
    return valid


def print_invalid(invalid):
    """List invalid captions (end <= start) for a report."""
    print(f"Invalid captions: {len(invalid)} "
          f"(end time <= start time — cannot be measured):")
    for cap in invalid:
        first = cap.lines[0] if cap.lines else ""
        if len(first) > 60:
            first = first[:57] + "..."
        print(f"  ! {sec_to_ts(cap.start, '.')} --> {sec_to_ts(cap.end, '.')} "
              f"| {cap.char_count} chars | {first}")


def detect_format(path):
    suffix = Path(path).suffix.lower()
    if suffix == ".srt":
        return "srt"
    if suffix == ".vtt":
        return "vtt"
    return None


def render(captions, fmt):
    """Render captions as SRT or VTT text."""
    out = []
    if fmt == "vtt":
        out.append("WEBVTT")
        out.append("")
        for cap in captions:
            if cap.identifier:
                out.append(cap.identifier)
            out.append(f"{sec_to_ts(cap.start, '.')} --> {sec_to_ts(cap.end, '.')}")
            out.extend(cap.lines)
            out.append("")
    else:  # srt
        for i, cap in enumerate(captions, 1):
            out.append(str(i))
            out.append(f"{sec_to_ts(cap.start, ',')} --> {sec_to_ts(cap.end, ',')}")
            out.extend(cap.lines)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def verdict_for(cps_values):
    """Return (verdict, median, max) for a non-empty list of CPS values."""
    med = statistics.median(cps_values)
    mx = max(cps_values)
    if med > HOLD_MEDIAN_CPS or mx > HOLD_MAX_CPS:
        return "HOLD", med, mx
    if med > WARN_CPS:
        return "WARN", med, mx
    return "PASS", med, mx


EXIT_FOR_VERDICT = {"PASS": 0, "WARN": 1, "HOLD": 2}


def cmd_check(args):
    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: file not found: {path}")
        return 2
    if detect_format(path) is None:
        print(f"ERROR: unsupported file type (expected .srt or .vtt): {path}")
        return 2
    captions, invalid = parse_captions_detailed(path)
    if not captions and not invalid:
        print(f"ERROR: no caption events parsed from {path.name}")
        return 2
    print(f"caption-toolkit check — {path.name}")
    verdict = med = mx = None
    if captions:
        cps_values = [c.cps for c in captions]
        verdict, med, mx = verdict_for(cps_values)
        for i, cap in enumerate(captions, 1):
            flag = ""
            if cap.cps > HOLD_MAX_CPS:
                flag = "  <-- HOLD (>30 CPS)"
            elif cap.cps > WARN_CPS:
                flag = "  <-- fast (>17 CPS)"
            print(f"  #{i} {sec_to_ts(cap.start, '.')} --> {sec_to_ts(cap.end, '.')} "
                  f"| {cap.char_count} chars / {cap.duration:.2f}s = {cap.cps:.1f} CPS{flag}")
        print(f"Captions: {len(captions)} | median {med:.1f} CPS | max {mx:.1f} CPS")
    if invalid:
        # A broken caption can never be certified: report it and HOLD.
        print_invalid(invalid)
        print("Verdict: HOLD (invalid captions present: end <= start)")
        return 2
    print(f"Verdict: {verdict} (PASS median <=17, WARN median >17, "
          f"HOLD median >20 or any >30)")
    return EXIT_FOR_VERDICT[verdict]


def fix_captions(captions, target_cps=DEFAULT_FIX_TARGET_CPS):
    """Extend too-fast captions into the following gap where possible.

    Returns (new_captions, changes) where changes is a list of dicts.
    A caption is never moved earlier, never shortened, and never extended
    past the next caption's start (the last caption may extend freely).
    Text is never changed.
    """
    if not math.isfinite(target_cps) or target_cps <= 0:
        raise ValueError(
            f"target_cps must be a positive finite number, got {target_cps!r}")
    new = [Caption(start=c.start, end=c.end, lines=list(c.lines),
                   identifier=c.identifier) for c in captions]
    changes = []
    for i, cap in enumerate(new):
        if cap.cps <= target_cps or cap.char_count == 0:
            continue
        old_end, old_cps = cap.end, cap.cps
        # Round the desired duration UP to whole milliseconds, so the
        # rendered (millisecond) timestamps do not push CPS back over target.
        desired_ms = math.ceil(cap.char_count / target_cps * 1000)
        desired_end = cap.start + desired_ms / 1000
        limit = new[i + 1].start if i + 1 < len(new) else desired_end
        new_end = min(desired_end, limit)
        # Mechanical guarantee: an end may only ever move LATER — never
        # earlier than the caption's original end, and never to <= start
        # (an overlapping next caption must not corrupt this one).
        if new_end < old_end:
            new_end = old_end
        cap.end = new_end
        assert cap.end >= old_end, "fix moved a caption end earlier"
        assert cap.end > cap.start, "fix made a caption end <= its start"
        fully = cap.end >= desired_end - 1e-9
        if cap.end > old_end:
            changes.append({
                "index": i + 1, "old_end": old_end, "new_end": cap.end,
                "old_cps": old_cps, "new_cps": cap.cps, "fully_fixed": fully,
            })
        else:
            changes.append({
                "index": i + 1, "old_end": old_end, "new_end": cap.end,
                "old_cps": old_cps, "new_cps": cap.cps, "fully_fixed": False,
                "blocked": True,
            })
    return new, changes


def cmd_fix(args):
    # Validate the target BEFORE touching any file: a zero, negative,
    # NaN or infinite target must never crash or corrupt the output.
    if not math.isfinite(args.target) or args.target <= 0:
        print(f"ERROR: --target must be a positive finite number "
              f"(got {args.target})")
        return 2
    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: file not found: {path}")
        return 2
    if detect_format(path) is None:
        print(f"ERROR: unsupported file type (expected .srt or .vtt): {path}")
        return 2
    captions, invalid = parse_captions_detailed(path)
    if invalid:
        print(f"ERROR: {path.name} contains invalid captions "
              f"(end <= start) — fix them by hand first; nothing written:")
        print_invalid(invalid)
        return 2
    if not captions:
        print(f"ERROR: no caption events parsed from {path.name}")
        return 2
    fixed, changes = fix_captions(captions, target_cps=args.target)
    out_path = path.with_name(path.stem + ".fixed.srt")
    out_path.write_text(render(fixed, "srt"), encoding="utf-8")
    print(f"caption-toolkit fix — {path.name} -> {out_path.name}")
    if not changes:
        print(f"No captions above {args.target:.0f} CPS — nothing to fix.")
    for ch in changes:
        if ch.get("blocked"):
            print(f"  #{ch['index']}: could not extend (no gap before next caption) "
                  f"— still {ch['new_cps']:.1f} CPS")
        else:
            note = "" if ch["fully_fixed"] else " (partial: ran out of gap)"
            print(f"  #{ch['index']}: end {sec_to_ts(ch['old_end'], '.')} -> "
                  f"{sec_to_ts(ch['new_end'], '.')} | {ch['old_cps']:.1f} -> "
                  f"{ch['new_cps']:.1f} CPS{note}")
    before = verdict_for([c.cps for c in captions])[0]
    after_values = [c.cps for c in fixed]
    after, med, mx = verdict_for(after_values)
    print(f"Verdict before: {before} | after: {after} "
          f"(median {med:.1f} CPS, max {mx:.1f} CPS)")
    print("Note: timing only — no caption text was changed, "
          "and no caption was moved earlier or shortened.")
    return EXIT_FOR_VERDICT[after]


def cmd_convert(args):
    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: file not found: {path}")
        return 2
    src_fmt = detect_format(path)
    if src_fmt is None:
        print(f"ERROR: unsupported file type (expected .srt or .vtt): {path}")
        return 2
    if args.to == src_fmt:
        print(f"ERROR: file is already {src_fmt}: {path.name} (use --to "
              f"{'vtt' if src_fmt == 'srt' else 'srt'})")
        return 2
    captions, invalid = parse_captions_detailed(path)
    if invalid:
        print(f"ERROR: {path.name} contains invalid captions "
              f"(end <= start) — fix them by hand first; nothing written:")
        print_invalid(invalid)
        return 2
    if not captions:
        print(f"ERROR: no caption events parsed from {path.name}")
        return 2
    out_path = path.with_suffix("." + args.to)
    out_path.write_text(render(captions, args.to), encoding="utf-8")
    print(f"caption-toolkit convert — {path.name} ({src_fmt}) -> "
          f"{out_path.name} ({args.to}) | {len(captions)} captions")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="caption-toolkit",
        description="Check, fix and convert SRT/WebVTT captions (stdlib only).")
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="report per-caption CPS and a PASS/WARN/HOLD verdict")
    p_check.add_argument("file", help="captions file (.srt or .vtt)")
    p_check.set_defaults(func=cmd_check)

    p_fix = sub.add_parser("fix", help="extend too-fast captions into the following gap; writes FILE.fixed.srt")
    p_fix.add_argument("file", help="captions file (.srt or .vtt)")
    p_fix.add_argument("--target", type=float, default=DEFAULT_FIX_TARGET_CPS,
                       help="target CPS to fix down to (default: 17)")
    p_fix.set_defaults(func=cmd_fix)

    p_conv = sub.add_parser("convert", help="convert between SRT and WebVTT")
    p_conv.add_argument("file", help="captions file (.srt or .vtt)")
    p_conv.add_argument("--to", choices=("srt", "vtt"), required=True,
                        help="output format")
    p_conv.set_defaults(func=cmd_convert)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
