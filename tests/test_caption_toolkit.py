#!/usr/bin/env python3
"""Tests for caption-toolkit. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
SRC = PACK_ROOT / "src" / "caption_toolkit.py"
sys.path.insert(0, str(PACK_ROOT / "src"))

import caption_toolkit as ct  # noqa: E402

SLOW_SRT = """1
00:00:00,000 --> 00:00:04,000
Hello and welcome back.

2
00:00:05,000 --> 00:00:09,000
Today we look at the news.

3
00:00:10,000 --> 00:00:14,000
Thanks for watching today.
"""

FAST_SRT = """1
00:00:00,000 --> 00:00:01,000
This caption is far too fast to read at all.

2
00:00:02,000 --> 00:00:03,000
Another very fast caption that nobody can read.

3
00:00:04,000 --> 00:00:05,000
And a third one rushing past the viewer quickly.
"""

WARN_SRT = """1
00:00:00,000 --> 00:00:02,000
This line is somewhat quick to read.

2
00:00:03,000 --> 00:00:05,000
This line is also a bit quick now.

3
00:00:06,000 --> 00:00:08,000
And this one is a little quick too.
"""

# First caption is too fast, but there is a 4-second gap after it,
# so `fix` can extend it and bring its CPS down.
FIXABLE_SRT = """1
00:00:00,000 --> 00:00:01,000
This caption needs more time to read.

2
00:00:05,000 --> 00:00:09,000
A slow one follows later on.
"""


def write(tmp, name, content):
    p = Path(tmp) / name
    p.write_text(content, encoding="utf-8")
    return p


def run_cli(*argv, cwd=None):
    return subprocess.run(
        [sys.executable, str(SRC), *argv],
        capture_output=True, text=True, cwd=cwd,
    )


class CheckTests(unittest.TestCase):
    def test_slow_captions_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Verdict: PASS", r.stdout)

    def test_fast_captions_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "fast.srt", FAST_SRT)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("Verdict: HOLD", r.stdout)

    def test_warn_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "warn.srt", WARN_SRT)
            caps = ct.parse_captions(f)
            verdict, med, mx = ct.verdict_for([c.cps for c in caps])
            self.assertEqual(verdict, "WARN", f"median={med} max={mx}")
            self.assertGreater(med, 17)
            self.assertLessEqual(med, 20)
            self.assertLessEqual(mx, 30)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("Verdict: WARN", r.stdout)

    def test_missing_file_is_error_not_pass(self):
        r = run_cli("check", "/nonexistent/nope.srt")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ERROR", r.stdout)


class FixTests(unittest.TestCase):
    def test_fix_improves_cps(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "fixable.srt", FIXABLE_SRT)
            before = ct.parse_captions(f)
            before_first_cps = before[0].cps
            self.assertGreater(before_first_cps, 30)

            r = run_cli("fix", str(f))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            out = Path(tmp) / "fixable.fixed.srt"
            self.assertTrue(out.is_file())
            after = ct.parse_captions(out)
            self.assertLess(after[0].cps, before_first_cps)
            self.assertLessEqual(after[0].cps, 17.5)
            # Text never changed, start never moved, never overlaps next caption.
            self.assertEqual(after[0].text, before[0].text)
            self.assertEqual(after[0].start, before[0].start)
            self.assertLessEqual(after[0].end, after[1].start)
            # The fixed file itself passes `check`.
            r2 = run_cli("check", str(out))
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertIn("Verdict: PASS", r2.stdout)


    def test_fix_blocked_when_no_gap(self):
        blocked = (
            "1\n00:00:00,000 --> 00:00:01,000\n"
            "This caption is far too fast to read at all.\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n"
            "The next caption starts right away here.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "blocked.srt", blocked)
            r = run_cli("fix", str(f))
            # No gap to extend into: fix reports it and the file stays HOLD.
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("could not extend", r.stdout)
            self.assertIn("after: HOLD", r.stdout)

    def test_check_accepts_vtt(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:04.000\nHello and welcome back.\n\n"
            "00:00:05.000 --> 00:00:09.000\nToday we look at the news.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.vtt", vtt)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Verdict: PASS", r.stdout)


class ConvertTests(unittest.TestCase):
    def test_convert_srt_to_vtt(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            r = run_cli("convert", str(f), "--to", "vtt")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            vtt = Path(tmp) / "slow.vtt"
            self.assertTrue(vtt.is_file())
            text = vtt.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("WEBVTT"))
            self.assertIn("00:00:00.000 --> 00:00:04.000", text)
            self.assertNotIn(",", text.split("-->")[0])

    def test_convert_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            original = ct.parse_captions(f)
            self.assertEqual(run_cli("convert", str(f), "--to", "vtt").returncode, 0)
            vtt = Path(tmp) / "slow.vtt"
            self.assertEqual(run_cli("convert", str(vtt), "--to", "srt").returncode, 0)
            back = ct.parse_captions(f)
            self.assertEqual(len(back), len(original))
            for a, b in zip(original, back):
                self.assertAlmostEqual(a.start, b.start, places=3)
                self.assertAlmostEqual(a.end, b.end, places=3)
                self.assertEqual(a.text, b.text)
            # And the VTT parse matches too.
            from_vtt = ct.parse_captions(vtt)
            self.assertEqual([c.text for c in from_vtt],
                             [c.text for c in original])

    def test_convert_same_format_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            r = run_cli("convert", str(f), "--to", "srt")
            self.assertEqual(r.returncode, 2)
            self.assertIn("ERROR", r.stdout)


# --- Regression tests for the v0.1.1 bug-free-gate fixes -----------------

# Two healthy captions plus one zero-duration caption full of text.
# The old parser silently dropped the broken cue and reported PASS.
ZERO_DURATION_SRT = """1
00:00:00,000 --> 00:00:04,000
Hello and welcome back.

2
00:00:05,000 --> 00:00:05,000
This caption has zero duration but plenty of text to read.

3
00:00:10,000 --> 00:00:14,000
Thanks for watching today.
"""

INVERTED_SRT = """1
00:00:00,000 --> 00:00:04,000
Hello and welcome back.

2
00:00:09,000 --> 00:00:05,000
This caption ends before it even starts at all.
"""

ALL_INVALID_SRT = """1
00:00:05,000 --> 00:00:05,000
The only caption in this file is broken.
"""


class InvalidCaptionTests(unittest.TestCase):
    """C1: captions with end <= start must never be silently dropped."""

    def test_zero_duration_caption_is_hold_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "zero.srt", ZERO_DURATION_SRT)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("Verdict: HOLD", r.stdout)
            self.assertIn("Invalid captions: 1", r.stdout)
            self.assertNotIn("Verdict: PASS", r.stdout)

    def test_inverted_caption_is_hold_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "inverted.srt", INVERTED_SRT)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("Verdict: HOLD", r.stdout)
            self.assertIn("Invalid captions: 1", r.stdout)

    def test_all_invalid_reports_invalid_not_no_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "allbad.srt", ALL_INVALID_SRT)
            r = run_cli("check", str(f))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("Invalid captions: 1", r.stdout)
            self.assertIn("Verdict: HOLD", r.stdout)
            self.assertNotIn("no caption events parsed", r.stdout)

    def test_parser_collects_invalid_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "zero.srt", ZERO_DURATION_SRT)
            valid, invalid = ct.parse_captions_detailed(f)
            self.assertEqual(len(valid), 2)
            self.assertEqual(len(invalid), 1)
            self.assertLessEqual(invalid[0].end, invalid[0].start)
            self.assertIn("zero duration", invalid[0].text)

    def test_fix_refuses_invalid_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "zero.srt", ZERO_DURATION_SRT)
            r = run_cli("fix", str(f))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("ERROR", r.stdout)
            self.assertIn("Invalid captions: 1", r.stdout)
            self.assertFalse((Path(tmp) / "zero.fixed.srt").exists())


class FixTargetValidationTests(unittest.TestCase):
    """C2: --target must be a positive finite number, validated up front."""

    def _assert_clean_rejection(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "fixable.srt", FIXABLE_SRT)
            r = run_cli("fix", str(f), "--target", target)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("ERROR", r.stdout)
            self.assertNotIn("Traceback", r.stderr)
            self.assertFalse((Path(tmp) / "fixable.fixed.srt").exists())

    def test_target_zero_rejected(self):
        self._assert_clean_rejection("0")

    def test_target_nan_rejected(self):
        self._assert_clean_rejection("nan")

    def test_target_inf_rejected(self):
        self._assert_clean_rejection("inf")

    def test_target_negative_rejected_no_corrupt_file(self):
        self._assert_clean_rejection("-5")

    def test_fix_captions_rejects_bad_targets_directly(self):
        caps = [ct.Caption(start=0.0, end=1.0, lines=["Some text here."])]
        for bad in (0, -5, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ct.fix_captions(caps, target_cps=bad)

    def test_fix_never_moves_end_earlier_when_overlapped(self):
        # The next caption starts BEFORE the fast caption's original end
        # (overlap). The old min(desired, limit) logic moved the end
        # earlier — corrupting the caption. It must stay put instead.
        caps = [
            ct.Caption(start=0.0, end=2.0,
                       lines=["This caption is far too fast to read at all."]),
            ct.Caption(start=1.0, end=5.0,
                       lines=["A slow one that overlaps the first."]),
        ]
        fixed, changes = ct.fix_captions(caps, target_cps=17.0)
        for orig, new in zip(caps, fixed):
            self.assertGreaterEqual(new.end, orig.end)
            self.assertGreater(new.end, new.start)
        self.assertEqual(fixed[0].end, 2.0)  # blocked, unchanged
        self.assertTrue(changes[0].get("blocked"))


# --- Agent-ready JSON output (v0.2.0) ------------------------------------

import json  # noqa: E402


class JsonOutputTests(unittest.TestCase):
    """--json: one JSON object, same verdicts and exit codes as text mode;
    errors are {"error": ...} objects, never plain text or tracebacks."""

    def test_check_json_on_bundled_sample(self):
        sample = PACK_ROOT / "examples" / "sample.srt"
        r = run_cli("check", str(sample), "--json")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tool"], "caption-toolkit")
        self.assertEqual(out["version"], ct.__version__)
        self.assertEqual(out["command"], "check")
        self.assertEqual(out["verdict"], "HOLD")
        self.assertEqual(out["caption_count"], 3)
        self.assertAlmostEqual(out["max_cps"], 44.0)
        self.assertAlmostEqual(out["median_cps"], 8.5)
        self.assertEqual(out["captions"][0]["status"], "hold")
        self.assertEqual(out["invalid_captions"], [])

    def test_check_json_agrees_with_human_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            human = run_cli("check", str(f))
            machine = run_cli("check", str(f), "--json")
            self.assertEqual(human.returncode, machine.returncode)
            self.assertIn("Verdict: PASS", human.stdout)
            self.assertEqual(json.loads(machine.stdout)["verdict"], "PASS")

    def test_check_json_error_is_json_object(self):
        r = run_cli("check", "/nonexistent/nope.srt", "--json")
        self.assertEqual(r.returncode, 2)
        out = json.loads(r.stdout)  # parses — never plain text
        self.assertIn("error", out)
        self.assertIn("file not found", out["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_check_json_invalid_captions_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "zero.srt", ZERO_DURATION_SRT)
            r = run_cli("check", str(f), "--json")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["verdict"], "HOLD")
            self.assertEqual(len(out["invalid_captions"]), 1)
            self.assertEqual(out["caption_count"], 2)

    def test_fix_json_reports_verdicts_and_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "fixable.srt", FIXABLE_SRT)
            r = run_cli("fix", str(f), "--json")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["command"], "fix")
            self.assertEqual(out["verdict_before"], "HOLD")
            self.assertEqual(out["verdict_after"], "PASS")
            self.assertEqual(len(out["changes"]), 1)
            self.assertLessEqual(out["changes"][0]["new_cps"], 17.5)
            self.assertTrue((Path(tmp) / "fixable.fixed.srt").is_file())

    def test_fix_json_bad_target_is_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "fixable.srt", FIXABLE_SRT)
            r = run_cli("fix", str(f), "--target", "0", "--json")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("error", out)
            self.assertIn("--target", out["error"])
            self.assertFalse((Path(tmp) / "fixable.fixed.srt").exists())

    def test_convert_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "slow.srt", SLOW_SRT)
            r = run_cli("convert", str(f), "--to", "vtt", "--json")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["command"], "convert")
            self.assertEqual(out["from_format"], "srt")
            self.assertEqual(out["to_format"], "vtt")
            self.assertEqual(out["caption_count"], 3)
            self.assertTrue((Path(tmp) / "slow.vtt").is_file())


if __name__ == "__main__":
    unittest.main()
