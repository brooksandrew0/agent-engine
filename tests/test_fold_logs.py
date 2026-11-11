"""Tests for tools/fold_logs.py. Every fixture is built in a temp dir."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fold_logs  # noqa: E402

DECISIONS = """# Decisions

Intro line.

## 2026-11-02

### Existing newest

- a

## 2026-10-31

### Existing older

- b

## Earlier decisions (recorded before this log existed)

- c
"""

CHANGELOG = """# Changelog

Oldest first.

## 2026-10-05

### First

- x

## 2026-10-05 (evening)

### Evening

- y

## 2026-11-02

### Latest

- z
"""


class FoldBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "decisions.md").write_text(DECISIONS)
        (self.root / "CHANGELOG.md").write_text(CHANGELOG)
        for d in ("decisions.d", "changelog.d"):
            (self.root / d).mkdir()
            (self.root / d / "README.md").write_text("# not a fragment\n\n## anything\n")

    def tearDown(self):
        self.tmp.cleanup()

    def frag(self, d, name, title, body="- bullet"):
        (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / d / name).write_text(f"### {title}\n\n{body}\n")

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fold_logs.main([*args, "--root", str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def read(self, name):
        return (self.root / name).read_text()

    def remaining(self, d):
        return sorted(p.name for p in (self.root / d).iterdir() if p.name != "README.md")


class NewestFirst(FoldBase):
    def test_existing_date_goes_on_top_of_section(self):
        self.frag("decisions.d", "2026-11-02-new.md", "New one")
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertEqual(self.read("decisions.md"), DECISIONS.replace(
            "## 2026-11-02\n\n### Existing newest",
            "## 2026-11-02\n\n### New one\n\n- bullet\n\n### Existing newest"))
        self.assertEqual(self.remaining("decisions.d"), [])

    def test_new_newest_date(self):
        self.frag("decisions.d", "2026-11-03-later.md", "Later")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"), DECISIONS.replace(
            "## 2026-11-02\n", "## 2026-11-03\n\n### Later\n\n- bullet\n\n## 2026-11-02\n", 1))

    def test_new_middle_date(self):
        self.frag("decisions.d", "2026-11-01-mid.md", "Mid")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"), DECISIONS.replace(
            "## 2026-10-31\n", "## 2026-11-01\n\n### Mid\n\n- bullet\n\n## 2026-10-31\n"))

    def test_new_oldest_date_goes_before_undated_section(self):
        self.frag("decisions.d", "2026-10-01-old.md", "Old")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"), DECISIONS.replace(
            "## Earlier", "## 2026-10-01\n\n### Old\n\n- bullet\n\n## Earlier"))

    def test_several_on_one_day_in_file_name_order(self):
        self.frag("decisions.d", "2026-11-03-b.md", "B")
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.frag("decisions.d", "2026-11-02-c.md", "C")
        self.run_main("--fold")
        text = self.read("decisions.md")
        self.assertIn("## 2026-11-03\n\n### A\n\n- bullet\n\n### B\n\n- bullet\n\n## 2026-11-02\n\n"
                      "### C\n\n- bullet\n\n### Existing newest", text)
        self.assertEqual(text.count("## 2026-11-03"), 1)

    def test_empty_main_file(self):
        (self.root / "decisions.md").write_text("")
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"), "## 2026-11-03\n\n### A\n\n- bullet\n")


class OldestFirst(FoldBase):
    def test_existing_last_date_appends_at_end(self):
        self.frag("changelog.d", "2026-11-02-more.md", "More")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"), CHANGELOG + "\n### More\n\n- bullet\n")

    def test_new_date_at_end(self):
        self.frag("changelog.d", "2026-11-03-next.md", "Next")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"),
                         CHANGELOG + "\n## 2026-11-03\n\n### Next\n\n- bullet\n")

    def test_existing_earlier_date_goes_to_end_of_its_section(self):
        self.frag("changelog.d", "2026-10-05-late.md", "Late")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"),
                         CHANGELOG.replace("- x\n\n", "- x\n\n### Late\n\n- bullet\n\n", 1))

    def test_date_before_all_goes_before_first_dated_heading(self):
        self.frag("changelog.d", "2026-01-01-first.md", "Earliest")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"), CHANGELOG.replace(
            "## 2026-10-05\n", "## 2026-01-01\n\n### Earliest\n\n- bullet\n\n## 2026-10-05\n", 1))

    def test_several_on_one_day(self):
        self.frag("changelog.d", "2026-11-04-z.md", "Z")
        self.frag("changelog.d", "2026-11-03-b.md", "B")
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"), CHANGELOG
                         + "\n## 2026-11-03\n\n### A\n\n- bullet\n\n### B\n\n- bullet\n"
                         + "\n## 2026-11-04\n\n### Z\n\n- bullet\n")


class Validation(FoldBase):
    def test_check_passes_on_good_fragments(self):
        self.frag("decisions.d", "2026-11-02-ok-1.md", "Fine", "- one\n- two")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("1 fragment(s) OK", out)
        self.assertEqual(self.run_main("--check")[0], 0)

    def test_missing_fragment_dirs_are_fine(self):
        for d in ("decisions.d", "changelog.d"):
            (self.root / d / "README.md").unlink()
            (self.root / d).rmdir()
        self.assertEqual(self.run_main("--check")[0], 0)
        self.assertEqual(self.run_main("--fold")[0], 0)

    def test_bad_names(self):
        for name in ("2026-11-02-Upper.md", "2026-11-02_x.md", "2026-11-2-x.md", "2026-11-02-.md",
                     "2026-11-02-a--b.md", "2026-13-40-x.md", "notes.md", "2026-11-02-x.txt"):
            with self.subTest(name=name):
                p = self.root / "decisions.d" / name
                p.write_text("### T\n\n- b\n")
                code, out = self.run_main("--check")
                self.assertEqual(code, 1)
                self.assertIn(name, out)
                p.unlink()

    def test_bad_shapes(self):
        cases = {
            "empty": "",
            "no-title": "- just a bullet\n",
            "h2-title": "## Title\n\n- b\n",
            "blank-title": "### \n\n- b\n",
            "no-body": "### Title\n\n\n",
            "no-blank-line": "### Title\n- b\n",
            "prose-only": "### Title\n\nSome prose.\n",
            "date-heading": "### Title\n\n## 2026-11-02\n\n- b\n",
            "leading-blank": "\n### Title\n\n- b\n",
        }
        for slug, content in cases.items():
            with self.subTest(slug=slug):
                p = self.root / "changelog.d" / f"2026-11-02-{slug}.md"
                p.write_text(content)
                self.assertEqual(self.run_main("--check")[0], 1)
                p.unlink()

    def test_not_utf8(self):
        (self.root / "decisions.d" / "2026-11-02-bin.md").write_bytes(b"### T\n\n- \xff\n")
        code, out = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", out)

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_symlinked_fragment_is_refused(self):
        target = self.root / "elsewhere.md"
        target.write_text("### T\n\n- b\n")
        (self.root / "decisions.d" / "2026-11-02-link.md").symlink_to(target)
        code, out = self.run_main("--fold")
        self.assertEqual(code, 1)
        self.assertIn("not a regular file", out)
        self.assertEqual(self.read("decisions.md"), DECISIONS)

    def test_fold_refuses_when_any_fragment_is_bad(self):
        self.frag("decisions.d", "2026-11-02-good.md", "Good")
        (self.root / "changelog.d" / "Bad.md").write_text("### T\n\n- b\n")
        self.assertEqual(self.run_main("--fold")[0], 1)
        self.assertEqual(self.read("decisions.md"), DECISIONS)
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-02-good.md"])

    def test_missing_main_file_folds_nothing(self):
        (self.root / "CHANGELOG.md").unlink()
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        code, out = self.run_main("--fold")
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md: main file is missing", out)
        self.assertEqual(self.read("decisions.md"), DECISIONS)
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-a.md"])


class Preservation(FoldBase):
    def test_idempotent(self):
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        self.run_main("--fold")
        once = (self.read("decisions.md"), self.read("CHANGELOG.md"))
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertEqual((self.read("decisions.md"), self.read("CHANGELOG.md")), once)

    def test_refold_of_already_present_entry_does_not_duplicate(self):
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        self.run_main("--fold")
        once = self.read("CHANGELOG.md")
        self.frag("changelog.d", "2026-11-03-a.md", "A")  # a fold whose delete was lost
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"), once)
        self.assertEqual(self.remaining("changelog.d"), [])

    def test_no_fragments_leaves_files_byte_identical(self):
        crlf = DECISIONS.replace("\n", "\r\n").encode() + b"no trailing newline"
        (self.root / "decisions.md").write_bytes(crlf)
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertEqual((self.root / "decisions.md").read_bytes(), crlf)
        self.assertEqual(self.read("CHANGELOG.md"), CHANGELOG)

    def test_existing_content_preserved_outside_insertions(self):
        self.frag("decisions.d", "2026-11-01-mid.md", "Mid")
        self.frag("changelog.d", "2026-11-03-next.md", "Next")
        self.run_main("--fold")
        inserted = "## 2026-11-01\n\n### Mid\n\n- bullet\n\n"
        self.assertEqual(self.read("decisions.md").replace(inserted, "", 1), DECISIONS)
        self.assertTrue(self.read("CHANGELOG.md").startswith(CHANGELOG))

    def test_check_never_writes(self):
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.run_main("--check")
        self.assertEqual(self.read("decisions.md"), DECISIONS)
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-a.md"])


class Config(FoldBase):
    def write_config(self, data):
        path = self.root / "fold.json"
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return str(path)

    def test_config_file_logs(self):
        (self.root / "notes.md").write_text("# Notes\n")
        cfg = self.write_config({"logs": [{"dir": "notes.d", "main": "notes.md",
                                           "order": "oldest-first"}],
                                 "ignore": ["README.md", "TEMPLATE.md"]})
        self.frag("notes.d", "2026-11-03-a.md", "A")
        (self.root / "notes.d" / "TEMPLATE.md").write_text("anything")
        self.frag("decisions.d", "2026-11-03-untouched.md", "Untouched")
        code, out = self.run_main("--fold", "--config", cfg)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read("notes.md"), "# Notes\n\n## 2026-11-03\n\n### A\n\n- bullet\n")
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-untouched.md"])
        self.assertEqual(self.read("decisions.md"), DECISIONS)

    def test_log_flag_replaces_defaults(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "log.md").write_text("")
        self.frag("docs/log.d", "2026-11-03-a.md", "A")
        self.frag("decisions.d", "2026-11-03-untouched.md", "Untouched")
        code, out = self.run_main("--fold", "--log", "docs/log.d", "docs/log.md", "newest-first")
        self.assertEqual(code, 0, out)
        self.assertIn("### A", self.read("docs/log.md"))
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-untouched.md"])

    def test_bad_configs(self):
        cases = {
            "not-json": "{",
            "not-object": [],
            "empty-logs": {"logs": []},
            "bad-order": {"logs": [{"dir": "a.d", "main": "a.md", "order": "sideways"}]},
            "escape": {"logs": [{"dir": "../x.d", "main": "a.md"}]},
            "absolute": {"logs": [{"dir": "a.d", "main": "/etc/a.md"}]},
            "missing-main": {"logs": [{"dir": "a.d"}]},
            "duplicate": {"logs": [{"dir": "a.d", "main": "a.md"}, {"dir": "a.d", "main": "b.md"}]},
            "bad-ignore": {"ignore": "README.md"},
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                code, out = self.run_main("--check", "--config", self.write_config(data))
                self.assertEqual(code, 2, out)
                self.assertIn("config error", out)

    def test_bad_log_flag_order(self):
        code, _ = self.run_main("--check", "--log", "a.d", "a.md", "random")
        self.assertEqual(code, 2)


class ReviewFixes(FoldBase):
    def test_entry_that_is_a_prefix_of_an_existing_one_is_still_inserted(self):
        (self.root / "CHANGELOG.md").write_text("# Changelog\n\n## 2026-11-02\n\n### Fix\n\n- a\n- b\n")
        self.frag("changelog.d", "2026-11-02-fix.md", "Fix", "- a")
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertEqual(self.read("CHANGELOG.md"),
                         "# Changelog\n\n## 2026-11-02\n\n### Fix\n\n- a\n- b\n\n### Fix\n\n- a\n")
        self.assertEqual(self.remaining("changelog.d"), [])

    def test_exact_entry_with_trailing_spaces_counts_as_present(self):
        (self.root / "CHANGELOG.md").write_text("## 2026-11-02\n\n### Fix  \n\n- a \n\n### Next\n\n- n\n")
        before = self.read("CHANGELOG.md")
        self.frag("changelog.d", "2026-11-02-fix.md", "Fix", "- a")
        self.run_main("--fold")
        self.assertEqual(self.read("CHANGELOG.md"), before)
        self.assertEqual(self.remaining("changelog.d"), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_symlinked_fragment_folder_outside_root_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            victim = Path(outside) / "2026-11-02-x.md"
            victim.write_text("### X\n\n- b\n")
            for name in ("README.md",):
                (self.root / "decisions.d" / name).unlink()
            (self.root / "decisions.d").rmdir()
            (self.root / "decisions.d").symlink_to(outside, target_is_directory=True)
            code, out = self.run_main("--fold")
            self.assertEqual(code, 1)
            self.assertIn("symlink", out)
            self.assertTrue(victim.exists())
            self.assertEqual(self.read("decisions.md"), DECISIONS)

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_symlinked_main_file_is_refused(self):
        real = self.root / "real.md"
        real.write_text(CHANGELOG)
        (self.root / "CHANGELOG.md").unlink()
        (self.root / "CHANGELOG.md").symlink_to(real)
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        code, out = self.run_main("--fold")
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md: main file is a symlink", out)
        self.assertEqual(real.read_text(), CHANGELOG)

    def test_failed_temp_write_changes_nothing(self):
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        real = fold_logs.tempfile.mkstemp
        calls = []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise PermissionError("read-only")
            return real(*a, **kw)

        with mock.patch.object(fold_logs.tempfile, "mkstemp", side_effect=flaky):
            code, out = self.run_main("--fold")
        self.assertEqual(code, 1)
        self.assertIn("could not write a temp file", out)
        self.assertEqual((self.read("decisions.md"), self.read("CHANGELOG.md")), (DECISIONS, CHANGELOG))
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-a.md"])
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.endswith(".tmp")), [])

    def test_failed_replace_deletes_no_fragment_and_a_rerun_finishes(self):
        self.frag("decisions.d", "2026-11-03-a.md", "A")
        self.frag("changelog.d", "2026-11-03-a.md", "A")
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) == 2:
                raise PermissionError("denied")
            return real(src, dst)

        with mock.patch.object(fold_logs.os, "replace", side_effect=flaky):
            code, out = self.run_main("--fold")
        self.assertEqual(code, 1)
        self.assertIn("no fragment was deleted", out)
        self.assertEqual(self.remaining("decisions.d"), ["2026-11-03-a.md"])
        self.assertEqual(self.remaining("changelog.d"), ["2026-11-03-a.md"])
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.endswith(".tmp")), [])
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertEqual(self.read("decisions.md").count("### A"), 1)
        self.assertEqual(self.read("CHANGELOG.md").count("### A"), 1)

    def test_dotfiles_are_skipped(self):
        (self.root / "decisions.d" / ".gitkeep").write_text("")
        (self.root / "decisions.d" / ".DS_Store").write_bytes(b"\x00\x01")
        self.assertEqual(self.run_main("--check")[0], 0)
        self.assertEqual(self.run_main("--fold")[0], 0)
        self.assertTrue((self.root / "decisions.d" / ".gitkeep").exists())

    def test_date_heading_with_suffix_is_reused(self):
        (self.root / "decisions.md").write_text("# D\n\n## 2026-01-02 (Fri)\n\n### Old\n\n- o\n")
        self.frag("decisions.d", "2026-01-02-new.md", "New")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"),
                         "# D\n\n## 2026-01-02 (Fri)\n\n### New\n\n- bullet\n\n### Old\n\n- o\n")

    def test_crlf_main_file_stays_crlf(self):
        (self.root / "CHANGELOG.md").write_bytes(CHANGELOG.replace("\n", "\r\n").encode())
        (self.root / "decisions.md").write_bytes(DECISIONS.replace("\n", "\r\n").encode())
        self.frag("changelog.d", "2026-11-02-more.md", "More")
        self.frag("changelog.d", "2026-11-03-next.md", "Next")
        self.frag("decisions.d", "2026-11-01-mid.md", "Mid")
        self.assertEqual(self.run_main("--fold")[0], 0)
        for name in ("CHANGELOG.md", "decisions.md"):
            data = (self.root / name).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), name)
        self.assertTrue((self.root / "CHANGELOG.md").read_bytes().endswith(
            b"- z\r\n\r\n### More\r\n\r\n- bullet\r\n\r\n## 2026-11-03\r\n\r\n### Next\r\n\r\n- bullet\r\n"))
        self.assertEqual(self.run_main("--fold")[0], 0)

    def test_headings_inside_fenced_code_are_ignored(self):
        text = "# D\n\n## 2026-11-02\n\n### Example\n\n- see:\n\n```\n## 2026-11-05\n### Fake\n```\n"
        (self.root / "decisions.md").write_text(text)
        self.frag("decisions.d", "2026-11-05-real.md", "Real")
        self.run_main("--fold")
        self.assertEqual(self.read("decisions.md"),
                         text.replace("# D\n\n", "# D\n\n## 2026-11-05\n\n### Real\n\n- bullet\n\n", 1))

    def test_two_entries_in_one_fragment_are_refused(self):
        (self.root / "decisions.d" / "2026-11-02-two.md").write_text("### A\n\n- a\n\n### B\n\n- b\n")
        code, out = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("one '### ' entry per fragment", out)
        (self.root / "decisions.d" / "2026-11-02-two.md").write_text("### A\n\n- a\n\n```\n### not a title\n```\n")
        self.assertEqual(self.run_main("--check")[0], 0)


if __name__ == "__main__":
    unittest.main()
