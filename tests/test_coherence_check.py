"""Tests for tools/coherence_check.py. Each case builds a small fake repo in a temp dir and runs
the rules from tools/coherence.example.json (or a small config of its own) against it."""

import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import coherence_check as cc  # noqa: E402

EXAMPLE = TOOLS / "coherence.example.json"
TODAY = dt.date(2026, 11, 2)
STATUS = "# Status\n\n| Item | State | Waiting on |\n| --- | --- | --- |\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write("docs/status.md", STATUS)
        self.config = cc.load_config(EXAMPLE)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def row(self, text):
        p = self.root / "docs/status.md"
        p.write_text(p.read_text() + text + "\n")

    def run_check(self, check=None, config=None):
        found = cc.run(self.root, config or self.config, TODAY)
        return [f for f in found if check is None or f.check == check]

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cc.main([*args, "--root", str(self.root), "--today", TODAY.isoformat()])
        return code, out.getvalue()


class StaleHeader(Base):
    def test_not_installed_with_install_record(self):
        self.write("docs/services/a.md", "# A\n\nStatus: not installed\n\n## Install record (2026-10-01)\n")
        f = self.run_check("stale-header")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0].path, f[0].line, f[0].level), ("docs/services/a.md", 3, "error"))
        self.assertIn("record heading at line 5", f[0].msg)

    def test_status_row_says_installed(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed 2026-10-30\n")
        self.row("| [P](plans/p.md) | Installed on 2026-11-01 | none |")
        f = self.run_check("stale-header")
        self.assertEqual(len(f), 1)
        self.assertIn("docs/status.md:5", f[0].msg)

    def test_row_saying_nothing_installed_is_not_evidence(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed 2026-10-30\n")
        self.row("| [P](plans/p.md) | nothing installed | the owner |")
        self.assertEqual(self.run_check("stale-header"), [])

    def test_header_that_admits_install_is_left_alone(self):
        self.write("docs/services/a.md", "# A\n\nStatus: installed on 2026-10-01, step 2 not built\n\n"
                   "## Install record\n")
        self.assertEqual(self.run_check("stale-header"), [])

    def test_plan_linking_installed_service(self):
        self.write("docs/services/s.md", "# S\n\nStatus: live\n\n## Install record\n")
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed; see [S](../services/s.md)\n")
        f = self.run_check("stale-header")
        self.assertEqual([x.path for x in f], ["docs/plans/p.md"])
        self.assertIn("docs/services/s.md", f[0].msg)

    def test_link_outside_root_is_ignored(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed; see [X](../../../../x.md)\n")
        self.assertEqual(self.run_check("stale-header"), [])

    def test_front_matter_status_counts(self):
        self.write("docs/plans/p.md", "---\nstatus: proposed\nowner: me\n---\n# P\n\n## Install record\n")
        self.assertEqual(len(self.run_check("stale-header")), 1)

    def test_title_status_counts(self):
        self.write("docs/plans/p.md", "# P (proposed)\n\n## Install record\n")
        self.assertEqual(len(self.run_check("stale-header")), 1)


class StaleSection(Base):
    def test_install_record_inside_not_installed_section(self):
        self.write("docs/x.md", "# X\n\n## Part two (not installed)\n\ntext\n\n### Install record\n")
        f = self.run_check("stale-section")
        self.assertEqual([(x.path, x.line) for x in f], [("docs/x.md", 3)])

    def test_install_record_in_next_section_is_fine(self):
        self.write("docs/x.md", "# X\n\n## Part two (not installed)\n\n## Install record\n")
        self.assertEqual(self.run_check("stale-section"), [])


class Statuses(Base):
    def test_plan_without_status_is_a_warning(self):
        self.write("docs/plans/p.md", "# P\n\nJust text.\n")
        self.write("docs/plans/README.md", "# Plans\n")
        f = self.run_check("no-status")
        self.assertEqual([(x.path, x.level) for x in f], [("docs/plans/p.md", "warn")])

    def test_service_without_status_is_not_flagged(self):
        self.write("docs/services/s.md", "# S\n")
        self.assertEqual(self.run_check("no-status"), [])

    def test_old_open_status(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed 2026-10-01\n")
        f = self.run_check("stale-open-status")
        self.assertEqual(len(f), 1)
        self.assertIn("32 days", f[0].msg)

    def test_recent_open_status(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: proposed 2026-10-20\n")
        self.assertEqual(self.run_check("stale-open-status"), [])

    def test_date_near_the_top_counts_without_front_matter(self):
        self.write("docs/plans/p.md", "# P\n\nWritten 2026-09-01.\n\nStatus: draft\n")
        self.assertEqual(len(self.run_check("stale-open-status")), 1)


class FrontMatter(Base):
    def fm(self, rel, body):
        self.write(rel, f"---\n{body}\n---\n# Doc\n")

    def test_complete_front_matter_is_clean(self):
        self.fm("docs/plans/p.md", "status: accepted\nowner: me\nreview_by: 2026-12-01")
        self.assertEqual(self.run_check("front-matter"), [])

    def test_unknown_status_and_missing_owner(self):
        self.fm("docs/plans/p.md", "status: maybe")
        f = self.run_check("front-matter")
        self.assertEqual(sorted(x.level for x in f), ["error", "warn"])

    def test_review_by_past_is_a_warning_unless_closed(self):
        self.fm("docs/plans/p.md", "status: accepted\nowner: me\nreview_by: 2026-10-01")
        self.fm("docs/plans/q.md", "status: archived\nowner: me\nreview_by: 2026-10-01")
        f = self.run_check("front-matter")
        self.assertEqual([(x.path, x.level) for x in f], [("docs/plans/p.md", "warn")])

    def test_superseded_without_pointer(self):
        self.fm("docs/plans/p.md", "status: superseded\nowner: me")
        self.assertIn("no `superseded_by`", self.run_check("front-matter")[0].msg)

    def test_good_supersedes_chain(self):
        self.fm("docs/plans/old.md", "status: superseded\nowner: me\nsuperseded_by: new.md")
        self.fm("docs/plans/new.md", "status: accepted\nowner: me\nsupersedes: [old.md]")
        self.assertEqual(self.run_check("front-matter"), [])

    def test_root_relative_pointer(self):
        self.fm("docs/plans/old.md", "status: superseded\nowner: me\nsuperseded_by: docs/plans/new.md")
        self.fm("docs/plans/new.md", "status: accepted\nowner: me\nsupersedes: [docs/plans/old.md]")
        self.assertEqual(self.run_check("front-matter"), [])

    def test_one_way_supersedes(self):
        self.fm("docs/plans/old.md", "status: archived\nowner: me")
        self.fm("docs/plans/new.md", "status: accepted\nowner: me\nsupersedes: old.md")
        self.assertIn("does not point back", self.run_check("front-matter")[0].msg)

    def test_pointer_to_missing_file_and_live_status(self):
        self.fm("docs/plans/p.md", "status: live\nowner: me\nsuperseded_by: gone.md")
        msgs = " | ".join(x.msg for x in self.run_check("front-matter"))
        self.assertIn("missing file", msgs)
        self.assertIn("status is \"live\"", msgs)

    def test_unclosed_front_matter_is_not_front_matter(self):
        self.write("docs/plans/p.md", "---\nstatus: maybe\n# P\n\nStatus: accepted\n")
        self.assertEqual(self.run_check("front-matter"), [])


class AnsweredRow(Base):
    def setUp(self):
        super().setUp()
        self.write("docs/plans/p.md", "# P\n\nStatus: accepted\n\n**Answered 2026-10-30:** yes to all.\n")

    def test_row_still_asking_is_flagged(self):
        self.row("| [P](plans/p.md) | built | owner to answer the questions |")
        f = self.run_check("status-row-answered")
        self.assertEqual([(x.path, x.line) for x in f], [("docs/status.md", 5)])
        self.assertIn("docs/plans/p.md:5", f[0].msg)

    def test_updated_row_passes(self):
        self.row("| [P](plans/p.md) | built | none |")
        self.assertEqual(self.run_check("status-row-answered"), [])

    def test_newer_round_of_questions_passes(self):
        self.row("| [P](plans/p.md) | built | new questions 2026-11-01 |")
        self.assertEqual(self.run_check("status-row-answered"), [])

    def test_unlinked_doc_is_not_read(self):
        self.row("| P | built | answer the questions |")
        self.assertEqual(self.run_check("status-row-answered"), [])

    def test_answer_mid_line_does_not_count(self):
        self.write("docs/plans/p.md", "# P\n\nStatus: accepted\n\nSee **Answered 2026-10-30** below.\n")
        self.row("| [P](plans/p.md) | built | answer the questions |")
        self.assertEqual(self.run_check("status-row-answered"), [])

    def test_header_row_is_skipped(self):
        self.write("docs/status.md", "| [P](plans/p.md) | answer |\n| --- | --- |\n")
        self.assertEqual(self.run_check("status-row-answered"), [])


class ImplementedBy(Base):
    def test_plan_not_built_while_its_service_is_live(self):
        self.write("docs/services/s.md", "---\nstatus: live\nowner: me\n---\n# S\n")
        self.write("docs/plans/p.md", "---\nstatus: proposed\nowner: me\nimplemented_by: [../services/s.md]\n"
                   "---\n# P\n")
        f = self.run_check("implemented-by")
        self.assertEqual(len(f), 1)
        self.assertIn("docs/services/s.md", f[0].msg)

    def test_install_record_counts_and_built_plan_passes(self):
        self.write("docs/services/s.md", "# S\n\n## Install record\n")
        self.write("docs/plans/p.md", "---\nstatus: accepted\nowner: me\nimplemented_by: docs/services/s.md\n"
                   "---\n# P\n")
        self.write("docs/plans/q.md", "---\nstatus: built\nowner: me\nimplemented_by: docs/services/s.md\n"
                   "---\n# Q\n")
        self.assertEqual([x.path for x in self.run_check("implemented-by")], ["docs/plans/p.md"])

    def test_target_not_live_passes(self):
        self.write("docs/services/s.md", "---\nstatus: accepted\nowner: me\n---\n# S\n")
        self.write("docs/plans/p.md", "---\nstatus: proposed\nowner: me\nimplemented_by: [../services/s.md]\n"
                   "---\n# P\n")
        self.assertEqual(self.run_check("implemented-by"), [])


class LogFragments(Base):
    def test_good_fragments_and_readme_pass(self):
        self.write("decisions.d/README.md", "# How\n\n## anything\n")
        self.write("decisions.d/2026-11-02-a.md", "### A\n\n- b\n")
        self.assertEqual(self.run_check("log-fragment"), [])

    def test_bad_fragments(self):
        self.write("changelog.d/2026-13-40-x.md", "### A\n\n- b\n")
        self.write("changelog.d/2026-11-02-y.md", "### A\n\n## 2026-11-02\n\n- b\n")
        f = self.run_check("log-fragment")
        by_path = {(x.path, x.line): x.msg for x in f}
        self.assertIn("2026-13-40 is not a real date", by_path[("changelog.d/2026-13-40-x.md", 0)])
        self.assertIn(("changelog.d/2026-11-02-y.md", 3), by_path)


class Cli(Base):
    def test_clean_repo_exits_zero(self):
        code, out = self.cli("--config", str(EXAMPLE))
        self.assertEqual(code, 0, out)
        self.assertIn("0 error, 0 warn", out)

    def test_warnings_do_not_fail_unless_asked(self):
        self.write("docs/plans/p.md", "# P\n")
        self.assertEqual(self.cli("--config", str(EXAMPLE))[0], 0)
        self.assertEqual(self.cli("--config", str(EXAMPLE), "--fail-on", "warn")[0], 1)

    def test_errors_fail_and_json(self):
        self.write("docs/services/a.md", "# A\n\nStatus: not installed\n\n## Install record\n")
        code, out = self.cli("--config", str(EXAMPLE), "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["counts"]["error"], 1)
        self.assertEqual(data["findings"][0]["check"], "stale-header")
        self.assertEqual(self.cli("--config", str(EXAMPLE), "--fail-on", "never")[0], 0)

    def test_custom_level_and_id(self):
        cfg = self.root / "c.json"
        cfg.write_text(json.dumps({"rules": [{"type": "missing-status", "id": "needs-status",
                                              "level": "error", "files": ["notes/*.md"]}]}))
        self.write("notes/n.md", "# N\n")
        code, out = self.cli("--config", str(cfg))
        self.assertEqual(code, 1)
        self.assertIn("needs-status", out)

    def test_bad_configs(self):
        cases = {
            "not-json": "{",
            "no-rules": {"rules": []},
            "unknown-type": {"rules": [{"type": "nope"}]},
            "missing-key": {"rules": [{"type": "stale-section", "files": ["*.md"]}]},
            "unknown-key": {"rules": [{"type": "missing-status", "files": ["*.md"], "fils": []}]},
            "bad-regex": {"rules": [{"type": "stale-section", "files": ["*.md"], "heading": "(",
                                     "record_heading": "x"}]},
            "bad-level": {"rules": [{"type": "missing-status", "files": ["*.md"], "level": "info"}]},
            "escaping-glob": {"rules": [{"type": "missing-status", "files": ["../*.md"]}]},
            "bad-max-days": {"rules": [{"type": "stale-open-status", "files": ["*.md"], "open": "x",
                                        "max_days": "3"}]},
            "bad-status-key": {"status": {"lnie": "x"}, "rules": [{"type": "missing-status",
                                                                  "files": ["*.md"]}]},
            "list-type": {"rules": [{"type": ["x"]}]},
            "list-id": {"rules": [{"type": "missing-status", "id": ["x"], "files": ["*.md"]}]},
            "list-level": {"rules": [{"type": "missing-status", "level": ["error"], "files": ["*.md"]}]},
            "string-files": {"rules": [{"type": "missing-status", "files": "*.md"}]},
            "null-files": {"rules": [{"type": "missing-status", "files": None}]},
            "null-regex": {"rules": [{"type": "stale-section", "files": ["*.md"], "heading": None,
                                      "record_heading": "x"}]},
            "string-follow": {"rules": [{"type": "stale-status", "files": ["*.md"], "claims": "x",
                                         "follow_links": "yes"}]},
            "number-tables": {"rules": [{"type": "answered-row", "tables": 3, "asks": "x",
                                         "answered": "y"}]},
            "list-key": {"rules": [{"type": "implemented-by", "files": ["*.md"], "not_built": ["p"],
                                    "key": ["k"]}]},
            "status-not-object": {"status": [], "rules": [{"type": "missing-status", "files": ["*.md"]}]},
            "status-lines-bool": {"status": {"lines": True}, "rules": [{"type": "missing-status",
                                                                      "files": ["*.md"]}]},
            "status-line-list": {"status": {"line": ["x"]}, "rules": [{"type": "missing-status",
                                                                     "files": ["*.md"]}]},
            "rule-not-object": {"rules": ["missing-status"]},
            "unknown-top-key": {"rulez": [], "rules": [{"type": "missing-status", "files": ["*.md"]}]},
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                cfg = self.root / f"{name}.json"
                cfg.write_text(data if isinstance(data, str) else json.dumps(data))
                code, out = self.cli("--config", str(cfg))
                self.assertEqual(code, 2, out)
                self.assertIn("config error", out)

    def test_never_writes(self):
        self.write("docs/services/a.md", "# A\n\nStatus: not installed\n\n## Install record\n")
        before = sorted((p, p.read_bytes()) for p in self.root.rglob("*") if p.is_file())
        self.cli("--config", str(EXAMPLE))
        after = sorted((p, p.read_bytes()) for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


class ReviewFixes(Base):
    def test_missing_fold_logs_is_a_clear_setup_error(self):
        self.write("decisions.d/2026-11-02-a.md", "### A\n\n- b\n")
        with mock.patch.object(cc, "FOLD_LOGS", self.root / "nowhere" / "fold_logs.py"):
            code, out = self.cli("--config", str(EXAMPLE))
        self.assertEqual(code, 2)
        self.assertIn("setup error", out)
        self.assertIn("fold_logs.py", out)

    def test_dotfiles_in_fragment_dirs_are_skipped(self):
        self.write("decisions.d/.gitkeep", "")
        self.write("decisions.d/.DS_Store", "junk")
        self.assertEqual(self.run_check("log-fragment"), [])


if __name__ == "__main__":
    unittest.main()
