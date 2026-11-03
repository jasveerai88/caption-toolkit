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


if __name__ == "__main__":
    unittest.main()
