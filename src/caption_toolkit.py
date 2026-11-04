#!/usr/bin/env python3
"""caption-toolkit — check, fix, lint, repair and convert SRT / WebVTT captions.

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
  check FILE.srt|FILE.vtt [--json]
  fix FILE.srt|FILE.vtt [--target CPS] [--json]   (writes FILE.fixed.srt)
  lint FILE.srt|FILE.vtt [--json]                 (report-only structural findings)
  repair FILE.srt|FILE.vtt [-o OUT] [--json]      (writes FILE.repaired.<fmt>)
  convert FILE.srt --to vtt [--json]
  convert FILE.vtt --to srt [--json]

`lint` is post-Whisper structural QA: overlapping cues, cues shorter
than 0.8s or longer than 7s, lines over 42 chars, more than 2 lines,
gaps under 80ms to the next cue (flicker), empty cues, and CPS over the
check thresholds — each as a per-cue finding with a severity, under the
same PASS / WARN / HOLD verdict scale and exit codes as `check`.

`repair` applies only conservative, text-preserving fixes: drop empty
cues, trim ends so every gap to the next cue is at least 80ms (never
below start + 0.4s — impossible trims are reported unfixable, not
forced), and split cues over 7s or over 2 lines at word boundaries with
durations divided proportionally to character counts. Caption text is
never added, removed or reworded; like `fix`/`convert`, `repair`
refuses files with invalid captions (end <= start) and writes nothing.

With --json, every command prints one JSON object instead of its text
report (same verdicts, same details, same exit codes; errors become
{"error": ...}). See SKILL.md for the schemas.
"""
import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.3.0"
TOOL = "caption-toolkit"

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


def _invalid_rows(invalid):
    """Invalid captions (end <= start) as JSON-ready dicts."""
    return [{"start_s": round(c.start, 3), "end_s": round(c.end, 3),
             "chars": c.char_count,
             "text": c.lines[0] if c.lines else ""} for c in invalid]


def _error(args, message, invalid=None):
    """Tool errors: 'ERROR: ...' in text mode, {"error": ...} in JSON mode.

    Same message, same exit code (2). In JSON mode an invalid-caption
    refusal also carries the invalid_captions list the text report shows.
    """
    if getattr(args, "json", False):
        payload = {"error": message}
        if invalid:
            payload["invalid_captions"] = _invalid_rows(invalid)
        print(json.dumps(payload))
    else:
        print(f"ERROR: {message}")
        if invalid:
            print_invalid(invalid)
    return 2


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
        return _error(args, f"file not found: {path}")
    fmt = detect_format(path)
    if fmt is None:
        return _error(args, f"unsupported file type (expected .srt or .vtt): {path}")
    captions, invalid = parse_captions_detailed(path)
    if not captions and not invalid:
        return _error(args, f"no caption events parsed from {path.name}")
    verdict = med = mx = None
    if captions:
        verdict, med, mx = verdict_for([c.cps for c in captions])
    if getattr(args, "json", False):
        rows = []
        for i, cap in enumerate(captions, 1):
            status = ("hold" if cap.cps > HOLD_MAX_CPS
                      else "fast" if cap.cps > WARN_CPS else "ok")
            rows.append({"index": i, "start_s": round(cap.start, 3),
                         "end_s": round(cap.end, 3),
                         "duration_s": round(cap.duration, 3),
                         "chars": cap.char_count, "cps": round(cap.cps, 3),
                         "status": status, "text": cap.text})
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "check",
            "file": path.name, "format": fmt,
            "verdict": "HOLD" if invalid else verdict,
            "reason": ("invalid captions present: end <= start"
                       if invalid else None),
            "caption_count": len(captions),
            "median_cps": round(med, 3) if med is not None else None,
            "max_cps": round(mx, 3) if mx is not None else None,
            "captions": rows, "invalid_captions": _invalid_rows(invalid),
            "warnings": [],
        }, indent=2))
        return 2 if invalid else EXIT_FOR_VERDICT[verdict]
    print(f"caption-toolkit check — {path.name}")
    if captions:
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
        return _error(args, f"--target must be a positive finite number "
                            f"(got {args.target})")
    path = Path(args.file)
    if not path.is_file():
        return _error(args, f"file not found: {path}")
    if detect_format(path) is None:
        return _error(args, f"unsupported file type (expected .srt or .vtt): {path}")
    captions, invalid = parse_captions_detailed(path)
    if invalid:
        return _error(args, f"{path.name} contains invalid captions "
                            f"(end <= start) — fix them by hand first; "
                            f"nothing written:", invalid)
    if not captions:
        return _error(args, f"no caption events parsed from {path.name}")
    fixed, changes = fix_captions(captions, target_cps=args.target)
    out_path = path.with_name(path.stem + ".fixed.srt")
    out_path.write_text(render(fixed, "srt"), encoding="utf-8")
    before = verdict_for([c.cps for c in captions])[0]
    after, med, mx = verdict_for([c.cps for c in fixed])
    if getattr(args, "json", False):
        change_rows = [{
            "index": ch["index"], "old_end_s": round(ch["old_end"], 3),
            "new_end_s": round(ch["new_end"], 3),
            "old_cps": round(ch["old_cps"], 3), "new_cps": round(ch["new_cps"], 3),
            "fully_fixed": ch["fully_fixed"], "blocked": bool(ch.get("blocked")),
        } for ch in changes]
        warnings = [
            f"caption #{ch['index']}: could not extend (no gap before next "
            f"caption) — still {ch['new_cps']:.1f} CPS"
            for ch in changes if ch.get("blocked")
        ]
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "fix",
            "file": path.name, "output_file": out_path.name,
            "target_cps": args.target, "changes": change_rows,
            "verdict_before": before, "verdict_after": after,
            "median_cps": round(med, 3), "max_cps": round(mx, 3),
            "warnings": warnings,
            "note": "timing only — no caption text was changed, and no "
                    "caption was moved earlier or shortened",
        }, indent=2))
        return EXIT_FOR_VERDICT[after]
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
        return _error(args, f"file not found: {path}")
    src_fmt = detect_format(path)
    if src_fmt is None:
        return _error(args, f"unsupported file type (expected .srt or .vtt): {path}")
    if args.to == src_fmt:
        return _error(args, f"file is already {src_fmt}: {path.name} (use --to "
                            f"{'vtt' if src_fmt == 'srt' else 'srt'})")
    captions, invalid = parse_captions_detailed(path)
    if invalid:
        return _error(args, f"{path.name} contains invalid captions "
                            f"(end <= start) — fix them by hand first; "
                            f"nothing written:", invalid)
    if not captions:
        return _error(args, f"no caption events parsed from {path.name}")
    out_path = path.with_suffix("." + args.to)
    out_path.write_text(render(captions, args.to), encoding="utf-8")
    if getattr(args, "json", False):
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "convert",
            "file": path.name, "from_format": src_fmt, "to_format": args.to,
            "output_file": out_path.name, "caption_count": len(captions),
            "status": "ok", "warnings": [],
        }, indent=2))
        return 0
    print(f"caption-toolkit convert — {path.name} ({src_fmt}) -> "
          f"{out_path.name} ({args.to}) | {len(captions)} captions")
    return 0


# ---------------------------------------------------------------------------
# Lint & repair (v0.3.0) — post-Whisper structural QA.
#
# `lint` only reports. `repair` applies the conservative fixes described
# in repair_captions() and never adds, removes or rewords caption text.
# Both number cues in file order, INCLUDING empty-text cues — the check
# parser skips those entirely, which is exactly the blind spot lint
# exists to close.
# ---------------------------------------------------------------------------

MIN_CUE_DURATION_S = 0.8    # a cue shorter than this flashes past
MAX_CUE_DURATION_S = 7.0    # a cue longer than this outstays its welcome
MAX_LINE_CHARS = 42         # visible characters per line
MAX_CUE_LINES = 2           # lines per cue
MIN_GAP_S = 0.08            # 80ms between one cue's end and the next start
MIN_TRIMMED_CUE_S = 0.4     # repair never trims an end below start + this
_EPS = 1e-6


def _plain_len(text):
    """Visible character count (markup tags stripped)."""
    return len(re.sub(r"<[^>]+>", "", text))


def is_empty_caption(cap):
    """True when the cue carries no visible text (nothing or whitespace)."""
    return re.sub(r"<[^>]+>", "", cap.text).strip() == ""


def parse_captions_full(path):
    """Parse ALL cues in file order, including empty-text ones.

    parse_captions_detailed() skips cues with no body lines entirely;
    lint/repair must see them (an empty cue is a finding / a drop), so
    this parser keeps every block that carries a timing line. Timing
    validity is NOT judged here — callers check end <= start themselves.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
    cues = []
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
            continue  # WEBVTT header, NOTE blocks, STYLE blocks
        m = _TS_RE.search(lines[ts_idx])
        if not m:
            continue
        start, end = ts_to_sec(m.group(1)), ts_to_sec(m.group(2))
        identifier = ""
        if ts_idx > 0:
            before = lines[ts_idx - 1].strip()
            if not before.isdigit():
                identifier = before
        cues.append(Caption(start=start, end=end,
                            lines=lines[ts_idx + 1:], identifier=identifier))
    return cues


def lint_captions(captions):
    """Structural findings for a cue list (file order). Report-only.

    Each finding is a dict: index (1-based, file order — empty and
    invalid cues are counted, unlike `check`), rule, severity
    ("WARN" / "HOLD"), start_s, end_s, message, detail.
    """
    findings = []

    def add(i, cap, rule, severity, message, detail=None):
        findings.append({
            "index": i, "rule": rule, "severity": severity,
            "start_s": round(cap.start, 3), "end_s": round(cap.end, 3),
            "message": message, "detail": detail or {},
        })

    for i, cap in enumerate(captions, 1):
        if cap.end <= cap.start:
            add(i, cap, "invalid-timing", "HOLD",
                f"end {sec_to_ts(cap.end, '.')} is not after start "
                f"{sec_to_ts(cap.start, '.')} — cannot be measured")
            continue
        if is_empty_caption(cap):
            add(i, cap, "empty-text", "HOLD", "caption has no text")
        if cap.duration < MIN_CUE_DURATION_S - _EPS:
            add(i, cap, "too-short", "WARN",
                f"{cap.duration:.2f}s on screen (minimum 0.8s)",
                {"duration_s": round(cap.duration, 3)})
        elif cap.duration > MAX_CUE_DURATION_S + _EPS:
            add(i, cap, "too-long", "WARN",
                f"{cap.duration:.2f}s on screen (maximum 7s)",
                {"duration_s": round(cap.duration, 3)})
        for ln, line in enumerate(cap.lines, 1):
            n = _plain_len(line)
            if n > MAX_LINE_CHARS:
                add(i, cap, "line-too-long", "WARN",
                    f"line {ln} is {n} chars (maximum 42)",
                    {"line": ln, "chars": n})
        if len(cap.lines) > MAX_CUE_LINES:
            add(i, cap, "too-many-lines", "WARN",
                f"{len(cap.lines)} lines (maximum 2)",
                {"lines": len(cap.lines)})
        if not is_empty_caption(cap):
            if cap.cps > HOLD_MAX_CPS:
                add(i, cap, "cps-hold", "HOLD",
                    f"{cap.cps:.1f} CPS (over the 30 CPS hold limit)",
                    {"cps": round(cap.cps, 3)})
            elif cap.cps > WARN_CPS:
                add(i, cap, "cps-fast", "WARN",
                    f"{cap.cps:.1f} CPS (fast — over 17 CPS)",
                    {"cps": round(cap.cps, 3)})
        if i < len(captions):
            nxt = captions[i]  # cue i+1 (0-based index i)
            gap = nxt.start - cap.end
            if gap < -_EPS:
                add(i, cap, "overlap", "HOLD",
                    f"ends {sec_to_ts(cap.end, '.')}, caption #{i + 1} "
                    f"starts {sec_to_ts(nxt.start, '.')} — "
                    f"{round(-gap * 1000)}ms overlap",
                    {"next_index": i + 1,
                     "overlap_ms": round(-gap * 1000)})
            elif gap < MIN_GAP_S - _EPS:
                add(i, cap, "flicker-gap", "WARN",
                    f"gap to caption #{i + 1} is {round(gap * 1000)}ms "
                    f"(minimum 80ms)",
                    {"next_index": i + 1, "gap_ms": round(gap * 1000)})
    return findings


def lint_verdict(findings):
    """PASS (no findings) / WARN / HOLD (any HOLD-severity finding)."""
    if any(f["severity"] == "HOLD" for f in findings):
        return "HOLD"
    return "WARN" if findings else "PASS"


def print_findings(findings):
    for f in findings:
        print(f"  #{f['index']} [{f['severity']}] {f['rule']}: {f['message']}")


def cmd_lint(args):
    path = Path(args.file)
    if not path.is_file():
        return _error(args, f"file not found: {path}")
    fmt = detect_format(path)
    if fmt is None:
        return _error(args, f"unsupported file type (expected .srt or .vtt): {path}")
    captions = parse_captions_full(path)
    if not captions:
        return _error(args, f"no caption events parsed from {path.name}")
    findings = lint_captions(captions)
    verdict = lint_verdict(findings)
    if getattr(args, "json", False):
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "lint",
            "file": path.name, "format": fmt, "verdict": verdict,
            "caption_count": len(captions),
            "finding_count": len(findings),
            "hold_count": sum(1 for f in findings
                              if f["severity"] == "HOLD"),
            "warn_count": sum(1 for f in findings
                              if f["severity"] == "WARN"),
            "findings": findings, "warnings": [],
        }, indent=2))
        return EXIT_FOR_VERDICT[verdict]
    print(f"caption-toolkit lint — {path.name}")
    if findings:
        print_findings(findings)
        holds = sum(1 for f in findings if f["severity"] == "HOLD")
        print(f"Findings: {len(findings)} ({holds} HOLD, "
              f"{len(findings) - holds} WARN) across {len(captions)} captions")
    else:
        print(f"Findings: none across {len(captions)} captions")
    print(f"Verdict: {verdict}")
    return EXIT_FOR_VERDICT[verdict]


def _wrap_words(words):
    """Greedy word wrap at MAX_LINE_CHARS visible chars per line."""
    lines, cur, cur_len = [], [], 0
    for w in words:
        wl = _plain_len(w)
        trial = wl if not cur else cur_len + 1 + wl
        if cur and trial > MAX_LINE_CHARS:
            lines.append(" ".join(cur))
            cur, cur_len = [w], wl
        else:
            cur.append(w)
            cur_len = trial
    if cur:
        lines.append(" ".join(cur))
    return lines


def _plan_split(cap, words):
    """Group a long cue's words into parts that each fit the duration
    and line limits (greedy, proportional to character counts)."""
    counts = [_plain_len(w) for w in words]
    total = sum(counts) + len(words) - 1
    if total <= 0:
        return None
    parts, cur, cur_chars = [], [], 0
    for w, c in zip(words, counts):
        trial_chars = c if not cur else cur_chars + 1 + c
        share = cap.duration * trial_chars / total
        if cur and (share > MAX_CUE_DURATION_S + _EPS
                    or len(_wrap_words(cur + [w])) > MAX_CUE_LINES):
            parts.append(cur)
            cur, cur_chars = [w], c
        else:
            cur.append(w)
            cur_chars = trial_chars
    if cur:
        parts.append(cur)
    return parts


def _balanced_plan(words, n):
    """Split words into up to n parts of near-equal character counts."""
    counts = [_plain_len(w) for w in words]
    total = sum(counts) + len(words) - 1
    if total <= 0 or len(words) < 2:
        return None
    n = min(n, len(words))
    ideal = total / n
    parts, cur, cur_chars = [], [], 0
    for w, c in zip(words, counts):
        trial = c if not cur else cur_chars + 1 + c
        if (cur and len(parts) < n - 1 and trial > ideal
                and cur_chars >= ideal / 2):
            parts.append(cur)
            cur, cur_chars = [w], c
        else:
            cur.append(w)
            cur_chars = trial
    if cur:
        parts.append(cur)
    return parts if len(parts) >= 2 else None


def _spans_for(cap, plan):
    """Tile a word plan across the cue's span. Returns (parts, fail)."""
    counts = [_plain_len(" ".join(part)) for part in plan]
    total = sum(counts)
    usable = cap.duration - MIN_GAP_S * (len(plan) - 1)
    if total <= 0 or usable <= 0:
        return None, "no room to split this caption"
    spans = [usable * c / total for c in counts]
    if min(spans) < MIN_TRIMMED_CUE_S - 1e-9:
        return None, (f"splitting would leave a part under "
                      f"{MIN_TRIMMED_CUE_S:.1f}s")
    parts = []
    t = cap.start
    for group, span in zip(plan, spans):
        parts.append(Caption(start=t, end=t + span,
                             lines=_wrap_words(group),
                             identifier=cap.identifier if not parts else ""))
        t += span + MIN_GAP_S
    parts[-1].end = cap.end  # absorb float dust; the span total is exact
    return parts, None


def split_caption(cap):
    """Split one cue at word boundaries. Returns (parts, fail_reason).

    The parts tile the cue's original span with 80ms gaps between them,
    durations divided proportionally to each part's character count.
    Text is preserved word-for-word; only line breaks may move. The
    greedy plan (each part within the duration/line limits) is tried
    first; if its proportions would leave a part under 0.4s, a
    character-balanced plan with the same part count is tried before
    the cue is honestly reported unsplittable.
    """
    words = cap.text.split()
    if len(words) < 2:
        return None, "a single word cannot be split at a word boundary"
    greedy = _plan_split(cap, words)
    candidates = []
    if greedy and len(greedy) >= 2:
        candidates.append(greedy)
        balanced = _balanced_plan(words, len(greedy))
        if balanced and balanced != greedy:
            candidates.append(balanced)
    else:
        # The greedy plan sees one part as enough (the cue only breaks
        # the as-written line limit): a balanced two-way split is the fix.
        balanced = _balanced_plan(words, 2)
        if balanced:
            candidates.append(balanced)
    fail = "no word boundary splits this caption"
    for plan in candidates:
        parts, why = _spans_for(cap, plan)
        if parts is not None:
            return parts, None
        fail = why
    return None, fail


def repair_captions(captions):
    """Conservative structural repairs. Returns (new_captions, changes).

    Input cues must have valid timing (end > start) — the CLI refuses
    invalid files before calling this. Repairs, in order: drop empty
    cues; split cues over 7s or over 2 lines at word boundaries; trim
    ends so every gap to the next cue is at least 80ms (an end is never
    trimmed below start + 0.4s — if that is impossible the cue is left
    unchanged and reported unfixable). Text is never added, removed or
    reworded; a split keeps every word, in order. Change indices refer
    to the cue's position in the INPUT list.
    """
    changes = []
    work = []
    for i, cap in enumerate(captions, 1):
        if is_empty_caption(cap):
            changes.append({"index": i, "action": "dropped-empty"})
            continue
        work.append((i, Caption(start=cap.start, end=cap.end,
                                lines=list(cap.lines),
                                identifier=cap.identifier)))
    staged = []
    for origin, cap in work:
        if (cap.duration > MAX_CUE_DURATION_S + _EPS
                or len(cap.lines) > MAX_CUE_LINES):
            parts, fail = split_caption(cap)
            if parts is None:
                changes.append({"index": origin, "action": "unfixable",
                                "reason": f"long caption left unsplit — {fail}"})
                staged.append((origin, cap))
            else:
                if cap.duration > MAX_CUE_DURATION_S + _EPS:
                    reason = (f"{cap.duration:.2f}s on screen "
                              f"(maximum {MAX_CUE_DURATION_S:.0f}s)")
                else:
                    reason = (f"{len(cap.lines)} lines "
                              f"(maximum {MAX_CUE_LINES})")
                changes.append({
                    "index": origin, "action": "split", "into": len(parts),
                    "reason": reason,
                    "parts": [{"start_s": round(p.start, 3),
                               "end_s": round(p.end, 3)} for p in parts],
                })
                staged.extend((origin, p) for p in parts)
        else:
            staged.append((origin, cap))
    for j in range(len(staged) - 1):
        origin, cur = staged[j]
        nxt_origin, nxt = staged[j + 1]
        gap = nxt.start - cur.end
        if gap < MIN_GAP_S - _EPS:
            desired = nxt.start - MIN_GAP_S
            if desired >= cur.start + MIN_TRIMMED_CUE_S - 1e-9:
                old_end = cur.end
                cur.end = desired
                changes.append({
                    "index": origin, "action": "trimmed-end",
                    "old_end_s": round(old_end, 3),
                    "new_end_s": round(desired, 3),
                    "next_index": nxt_origin,
                    "gap_ms": round(gap * 1000),
                    "reason": "overlap" if gap < -_EPS else "gap",
                })
            else:
                changes.append({
                    "index": origin, "action": "unfixable",
                    "reason": ("gap to the next caption cannot be fixed — "
                               "trimming the end would leave under "
                               f"{MIN_TRIMMED_CUE_S:.1f}s"),
                    "next_index": nxt_origin,
                })
    changes.sort(key=lambda ch: ch["index"])
    return [cap for _origin, cap in staged], changes


def cmd_repair(args):
    path = Path(args.file)
    if not path.is_file():
        return _error(args, f"file not found: {path}")
    fmt = detect_format(path)
    if fmt is None:
        return _error(args, f"unsupported file type (expected .srt or .vtt): {path}")
    out_path = path.with_name(path.stem + ".repaired." + fmt)
    out_fmt = fmt
    if args.output:
        out_path = Path(args.output)
        out_fmt = detect_format(out_path)
        if out_fmt is None:
            return _error(args, f"output file must end in .srt or .vtt: "
                                f"{args.output}")
        if out_path.resolve() == path.resolve():
            return _error(args, "output file must differ from the input "
                                "file — repair never overwrites its input")
    captions = parse_captions_full(path)
    if not captions:
        return _error(args, f"no caption events parsed from {path.name}")
    invalid = [c for c in captions if c.end <= c.start]
    if invalid:
        return _error(args, f"{path.name} contains invalid captions "
                            f"(end <= start) — fix them by hand first; "
                            f"nothing written:", invalid)
    if all(is_empty_caption(c) for c in captions):
        return _error(args, f"every caption in {path.name} is empty — "
                            f"nothing to write")
    repaired, changes = repair_captions(captions)
    try:
        out_path.write_text(render(repaired, out_fmt), encoding="utf-8")
    except OSError as exc:
        return _error(args, f"could not write {out_path}: "
                            f"{exc.strerror or exc}")
    remaining = lint_captions(repaired)
    verdict = lint_verdict(remaining)
    if getattr(args, "json", False):
        print(json.dumps({
            "tool": TOOL, "version": __version__, "command": "repair",
            "file": path.name, "format": fmt,
            "output_file": out_path.name, "output_format": out_fmt,
            "caption_count_before": len(captions),
            "caption_count_after": len(repaired),
            "changes": changes, "remaining_findings": remaining,
            "verdict_after": verdict, "warnings": [],
            "note": "text preserved word-for-word — repairs only drop "
                    "empty cues, trim ends, and split long cues at word "
                    "boundaries",
        }, indent=2))
        return EXIT_FOR_VERDICT[verdict]
    print(f"caption-toolkit repair — {path.name} -> {out_path.name}")
    if not changes:
        print("No repairs needed — nothing to change.")
    for ch in changes:
        if ch["action"] == "dropped-empty":
            print(f"  #{ch['index']}: dropped — empty text")
        elif ch["action"] == "split":
            print(f"  #{ch['index']}: split into {ch['into']} captions "
                  f"— {ch['reason']}")
        elif ch["action"] == "trimmed-end":
            if ch["gap_ms"] < 0:
                why = (f"overlap with caption #{ch['next_index']} "
                       f"({-ch['gap_ms']}ms)")
            else:
                why = (f"gap to caption #{ch['next_index']} was "
                       f"{ch['gap_ms']}ms (minimum 80ms)")
            print(f"  #{ch['index']}: end "
                  f"{sec_to_ts(ch['old_end_s'], '.')} -> "
                  f"{sec_to_ts(ch['new_end_s'], '.')} — {why}")
        elif ch["action"] == "unfixable":
            print(f"  #{ch['index']}: NOT fixed — {ch['reason']}")
    if remaining:
        print("Remaining findings:")
        print_findings(remaining)
    print(f"Result: {len(repaired)} captions written to {out_path.name} | "
          f"lint after repair: {verdict}")
    print("Note: text preserved word-for-word — repairs only drop empty "
          "cues, trim ends, and split long cues at word boundaries.")
    return EXIT_FOR_VERDICT[verdict]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="caption-toolkit",
        description="Check, fix, lint, repair and convert SRT/WebVTT captions (stdlib only).")
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="report per-caption CPS and a PASS/WARN/HOLD verdict")
    p_check.add_argument("file", help="captions file (.srt or .vtt)")
    p_check.add_argument("--json", action="store_true",
                         help="print one JSON object instead of the text report")
    p_check.set_defaults(func=cmd_check)

    p_fix = sub.add_parser("fix", help="extend too-fast captions into the following gap; writes FILE.fixed.srt")
    p_fix.add_argument("file", help="captions file (.srt or .vtt)")
    p_fix.add_argument("--target", type=float, default=DEFAULT_FIX_TARGET_CPS,
                       help="target CPS to fix down to (default: 17)")
    p_fix.add_argument("--json", action="store_true",
                       help="print one JSON object instead of the text report")
    p_fix.set_defaults(func=cmd_fix)

    p_lint = sub.add_parser("lint", help="report structural problems (overlaps, flicker gaps, cue/line length, empty cues) without changing the file")
    p_lint.add_argument("file", help="captions file (.srt or .vtt)")
    p_lint.add_argument("--json", action="store_true",
                        help="print one JSON object instead of the text report")
    p_lint.set_defaults(func=cmd_lint)

    p_rep = sub.add_parser("repair", help="drop empty cues, fix overlaps/gaps, split long cues; writes FILE.repaired.<fmt> unless -o is given")
    p_rep.add_argument("file", help="captions file (.srt or .vtt)")
    p_rep.add_argument("-o", "--output", default=None,
                       help="output file (.srt or .vtt); default: FILE.repaired.<same format>")
    p_rep.add_argument("--json", action="store_true",
                       help="print one JSON object instead of the text report")
    p_rep.set_defaults(func=cmd_repair)

    p_conv = sub.add_parser("convert", help="convert between SRT and WebVTT")
    p_conv.add_argument("file", help="captions file (.srt or .vtt)")
    p_conv.add_argument("--to", choices=("srt", "vtt"), required=True,
                        help="output format")
    p_conv.add_argument("--json", action="store_true",
                        help="print one JSON object instead of the text report")
    p_conv.set_defaults(func=cmd_convert)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
