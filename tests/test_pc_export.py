"""Tests for scripts/pc.py export_series on disposable Git repositories.

Run: python3 -m unittest discover -s tests -p 'test_*.py'
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pc  # noqa: E402


def sh(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-C", str(cwd), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pc export ")
        root = Path(self.tmp.name)
        self.base = root / "upstream"
        self.base.mkdir()
        sh(self.base, "init", "-q")
        (self.base / "a.txt").write_text("one\n")
        sh(self.base, "add", "a.txt")
        sh(self.base, "commit", "-qm", "base")
        self.pin = sh(self.base, "rev-parse", "HEAD")
        self.work = root / "work copy"
        sh(root, "clone", "-q", str(self.base), str(self.work))
        for n in (1, 2):
            (self.work / f"f{n}.txt").write_text(f"change {n}\n")
            sh(self.work, "add", ".")
            sh(self.work, "commit", "-qm", f"change {n}")
        self.owner = root / "owner"
        self.series = self.owner / "patches" / "photocraft"
        self.series.mkdir(parents=True)
        (self.series / "series").write_text("")
        sh(self.owner, "init", "-q")
        sh(self.owner, "add", ".")
        sh(self.owner, "commit", "-qm", "empty series")
        pc.export_series(self.work, self.base, self.pin, self.series, self.owner)
        sh(self.owner, "add", ".")
        sh(self.owner, "commit", "-qm", "exported")
        self.names = pc.series(self.series)

    def tearDown(self):
        self.tmp.cleanup()

    def export(self):
        return pc.export_series(self.work, self.base, self.pin, self.series, self.owner)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.series.iterdir()}

    def test_clean_export_rebuilds_the_work_tree(self):
        self.assertEqual(len(self.names), 2)
        (self.work / "f3.txt").write_text("three\n")
        sh(self.work, "add", ".")
        sh(self.work, "commit", "-qm", "change 3")
        head, count = self.export()
        self.assertEqual(count, 3)
        self.assertEqual(len(pc.series(self.series)), 3)
        self.assertEqual([p.name for p in self.series.parent.iterdir() if p.name.startswith(".")], [])

    def test_edited_header_is_refused_and_kept(self):
        patch = self.series / self.names[0]
        patch.write_text(patch.read_text().replace("Subject:", "Subject: edited", 1))
        before = self.snapshot()
        with self.assertRaisesRegex(pc.Failure, "uncommitted, staged or untracked"):
            self.export()
        self.assertEqual(self.snapshot(), before)

    def test_untracked_candidate_patch_is_refused_and_kept(self):
        (self.series / "9999-candidate.patch").write_text("candidate\n")
        before = self.snapshot()
        with self.assertRaisesRegex(pc.Failure, "uncommitted, staged or untracked"):
            self.export()
        self.assertEqual(self.snapshot(), before)

    def test_staged_change_is_refused(self):
        (self.series / "series").write_text("".join(n + "\n" for n in self.names) + "# note\n")
        sh(self.owner, "add", ".")
        with self.assertRaisesRegex(pc.Failure, "uncommitted, staged or untracked"):
            self.export()

    def test_failure_during_the_swap_restores_the_old_series(self):
        (self.work / "f3.txt").write_text("three\n")
        sh(self.work, "add", ".")
        sh(self.work, "commit", "-qm", "change 3")
        before = self.snapshot()
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("injected failure")
            return real(src, dst)

        with mock.patch.object(pc.os, "replace", flaky):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual([p.name for p in self.series.parent.iterdir() if p.name.startswith(".")], [])

    def test_failure_while_writing_leaves_the_series_untouched(self):
        before = self.snapshot()
        with mock.patch.object(pc, "apply_series", side_effect=pc.Failure("injected")):
            with self.assertRaisesRegex(pc.Failure, "injected"):
                self.export()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual([p.name for p in self.series.parent.iterdir() if p.name.startswith(".")], [])

    def test_dirty_work_copy_is_refused(self):
        (self.work / "f1.txt").write_text("dirty\n")
        with self.assertRaisesRegex(pc.Failure, "work copy has uncommitted"):
            self.export()


if __name__ == "__main__":
    unittest.main()
