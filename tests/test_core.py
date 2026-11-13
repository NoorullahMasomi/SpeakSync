"""Tests:  .venv\\Scripts\\python -m unittest discover -s tests -v"""
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speaksync import media, updates                                   # noqa: E402
from speaksync.project import (Project, fmt_time, parse_script, parse_time, script_text,  # noqa: E402
                               srt_text)


class TimeAndScript(unittest.TestCase):
    def test_time(self):
        self.assertEqual(parse_time("1:05.3"), 65.3)
        self.assertEqual(parse_time("0:01:05,300"), 65.3)
        self.assertEqual(parse_time("12"), 12.0)
        self.assertIsNone(parse_time("abc"))
        self.assertEqual(fmt_time(65.3), "1:05.3")
        self.assertEqual(fmt_time(5), "0:05")
        self.assertEqual(fmt_time(3725.5), "1:02:05.5")
        self.assertEqual(fmt_time(65.3, srt=True), "00:01:05,300")

    def test_script(self):
        txt = "[0:01 - 0:03] Hello and welcome.\n\n[0:05-0:12]  In this\nvideo.\n\nNo time here\n\n[0:09 - 0:04] bad time"
        p = parse_script(txt)
        self.assertEqual(len(p), 4)
        self.assertEqual((p[0]["start"], p[0]["end"], p[0]["text"]), (1.0, 3.0, "Hello and welcome."))
        self.assertEqual(p[1]["text"], "In this video.")
        self.assertIsNone(p[2]["start"])
        self.assertIsNone(p[3]["start"])                              # end before start = no time
        back = parse_script(script_text(p))
        self.assertEqual([x["text"] for x in back], [x["text"] for x in p])

    def test_dari_and_srt(self):
        srt = srt_text([(1.0, 2.5, "سلام دوستان"), (3, 4, "<i>second</i>")])
        p = parse_script("﻿" + srt)
        self.assertEqual(p[0]["text"], "سلام دوستان")
        self.assertEqual(p[1]["text"], "second")
        self.assertEqual((p[0]["start"], p[0]["end"]), (1.0, 2.5))


class ProjectFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.video = self.tmp / "v.mp4"
        self.video.write_bytes(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parts_and_takes(self):
        p = Project.create(self.tmp / "proj", "My film", self.video, 20)
        p.import_script("[0:05 - 0:07] two\n\n[0:01 - 0:03] one\n\nthree", replace=True)
        self.assertEqual([x["text"] for x in p.data["parts"]], ["one", "two", "three"])
        pid = p.data["parts"][0]["id"]
        p.save_take(pid, b"a" * 300, ".webm")
        p.save_take(pid, b"b" * 300, ".webm")                             # the old try is kept
        self.assertEqual(p.take_path(pid).read_bytes(), b"b" * 300)
        self.assertEqual(len(list((p.folder / "takes" / "old").iterdir())), 1)
        # the page sends parts back: ids stay, bad values are fixed
        parts = p.info()["parts"]
        parts[1]["start"], parts[1]["end"] = 30, 31                       # after the video end -> clamped
        parts.append({"id": "bad id", "start": 2, "end": None, "text": "x"})
        p.set_parts(parts)
        p.save()
        q = Project.open(p.folder / "project.speaksync")
        self.assertEqual(q.data["parts"][0]["id"], pid)
        self.assertTrue(q.info()["parts"][0]["take"])
        last = q.data["parts"][-1]
        self.assertIsNone(last["start"])
        self.assertTrue(last["id"].startswith("p_"))
        clamped = [x for x in q.data["parts"] if x["text"] == "two"][0]
        self.assertLessEqual(clamped["end"], 20)
        self.assertGreaterEqual(clamped["end"] - clamped["start"], 0.199)


class Plans(unittest.TestCase):
    parts = [{"id": "a", "start": 1.0, "end": 3.0, "text": "A"},
             {"id": "b", "start": 4.0, "end": 6.0, "text": "B"},
             {"id": "c", "start": 8.0, "end": 9.0, "text": "C"}]

    def test_fit(self):
        voices = {"a": (Path("a.wav"), 2.0), "b": (Path("b.wav"), 4.4)}   # b is too long (room 4 s)
        plan = media.make_plan(self.parts, voices, "fit", 10.0)
        self.assertEqual(plan.duration, 10.0)
        self.assertEqual([p.start for p in plan.places], [1.0, 4.0])
        self.assertAlmostEqual(plan.places[1].tempo, 1.1, 3)
        self.assertFalse(plan.warnings)
        plan = media.make_plan(self.parts, {"b": (Path("b.wav"), 6.0)}, "fit", 10.0)
        self.assertTrue(plan.warnings)                                     # 6 s does not fit in 4 s even at 1.25x

    def test_wait(self):
        voices = {"a": (Path("a.wav"), 3.7), "c": (Path("c.wav"), 0.5)}
        plan = media.make_plan(self.parts, voices, "wait", 10.0)
        # a: part is 2 s, voice 3.7 s -> picture held 2.0 s (3.7 + 0.3 rest - 2)
        self.assertAlmostEqual(plan.pieces[1].hold, 2.0, 3)
        self.assertAlmostEqual(plan.duration, 12.0, 3)
        self.assertAlmostEqual(plan.places[1].start, 10.0, 3)              # c moved 2 s later
        total = sum(pc.b - pc.a + pc.hold for pc in plan.pieces)
        self.assertAlmostEqual(total, plan.duration, 3)


class Updates(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updates.is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(updates.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(updates.is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("", "1.0.0"))


class RealVideo(unittest.TestCase):
    """Makes a small test video and two 'voices', then exports in both modes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        ff = media.ffmpeg()
        cls.video = cls.tmp / "clip.mp4"
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=10",
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.video)], check=True, capture_output=True)
        cls.voice = []
        for k, secs in enumerate((2.0, 3.5)):
            f = cls.tmp / f"voice{k}.webm"
            subprocess.run([ff, "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d=0.5", "-f", "lavfi",
                            "-i", f"sine=frequency={500 + 200 * k}:duration={secs}:sample_rate=48000",
                            "-filter_complex", "[0][1]concat=n=2:v=0:a=1", "-c:a", "libopus", str(f)],
                           check=True, capture_output=True)
            cls.voice.append(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _project(self, mode):
        info = media.probe(self.video)
        self.assertAlmostEqual(info.duration, 10.0, 0)
        self.assertTrue(info.has_audio)
        p = Project.create(self.tmp / f"proj_{mode}", "Test", self.video, info.duration)
        p.import_script("[0:01 - 0:03] one\n\n[0:05 - 0:06] two", replace=True)
        p.data["mode"] = mode
        for part, f in zip(p.data["parts"], self.voice):
            p.save_take(part["id"], f.read_bytes(), ".webm")
        p.save()
        return p

    def _export(self, p):
        job = media.Job()
        out = p.folder / "export" / "out.mp4"
        self.assertTrue(job.start(p, out)["ok"])
        for _ in range(600):
            s = job.status()
            if not s["running"]:
                break
            time.sleep(0.2)
        self.assertEqual(s["stage"], "done", s.get("error"))
        return out, s

    def test_fit_export(self):
        p = self._project("fit")
        out, s = self._export(p)
        info = media.probe(out)
        self.assertAlmostEqual(info.duration, 10.0, delta=0.15)
        self.assertTrue(info.has_audio)
        self.assertTrue(out.with_suffix(".srt").exists())
        self.assertFalse((p.folder / "export" / "_work").exists())

    def test_wait_export(self):
        p = self._project("wait")
        out, s = self._export(p)
        info = media.probe(out)
        # part one: 2 s room, ~2.1 s voice (+0.3 rest) -> ~0.4 s held
        # part two: 1 s room, ~3.6 s voice (+0.3 rest) -> ~2.9 s held      => about 13.3 s
        self.assertAlmostEqual(info.duration, 13.3, delta=0.35)
        self.assertAlmostEqual(info.duration, s["duration"], delta=0.15)


if __name__ == "__main__":
    unittest.main()
