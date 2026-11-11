"""Tests for tools/deny_scan.py. Every term here is made up."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import deny_scan  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args, env=None):
    full = {**os.environ, **GIT_ENV, **(env or {})}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          env=full).stdout.decode()


class Repo:
    """A throwaway git repo plus a deny list outside it."""

    def __init__(self, terms, raw=None):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.path = base / "repo"
        self.path.mkdir()
        git(self.path, "init", "-q")
        git(self.path, "symbolic-ref", "HEAD", "refs/heads/main")  # git before 2.28 has no init -b
        self.deny = base / "deny.txt"
        if raw is not None:
            self.deny.write_bytes(raw)
        elif terms is not None:
            self.deny.write_text(terms, encoding="utf-8")

    def write(self, name, text, commit=True, message="add", env=None):
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text, encoding="utf-8")
        git(self.path, "add", name)
        if commit:
            git(self.path, "commit", "-q", "-m", message, env=env)

    def scan(self, *extra, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old = os.environ.get(deny_scan.ENV_VAR)
        os.environ[deny_scan.ENV_VAR] = str(self.deny)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = deny_scan.main(["--repo", str(self.path), *extra],
                                      stdin=io.StringIO(stdin) if stdin is not None else None)
        finally:
            if old is None:
                del os.environ[deny_scan.ENV_VAR]
            else:
                os.environ[deny_scan.ENV_VAR] = old
        return code, out.getvalue() + err.getvalue()

    def close(self):
        self._tmp.cleanup()


class DenyScanTests(unittest.TestCase):
    def make(self, terms, raw=None):
        repo = Repo(terms, raw)
        self.addCleanup(repo.close)
        return repo

    # Matching

    def test_clean_index_passes(self):
        repo = self.make("Zorblat\n")
        repo.write("a.md", "nothing private here\n")
        code, out = repo.scan()
        self.assertEqual(code, 0, out)

    def test_match_fails_and_hides_the_term(self):
        repo = self.make("# people\nZorblat Quix\n")
        repo.write("docs/a.md", "line one\nmet zorblat quix today\n")
        code, out = repo.scan()
        self.assertEqual(code, deny_scan.EXIT_FINDINGS)
        self.assertIn("docs/a.md:2: matches list line 2", out)
        self.assertNotIn("orblat", out.lower())

    def test_whole_word_only(self):
        repo = self.make("Quix\n")
        repo.write("a.md", "quixotic is fine\n")
        self.assertEqual(repo.scan()[0], 0)
        repo.write("b.md", "but (quix) is not\n")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    def test_words_split_across_lines_or_spaces(self):
        repo = self.make("Zorblat Quix\n")
        repo.write("a.md", "one\nwe met Zorblat\nQuix there\n")
        code, out = repo.scan()
        self.assertEqual(code, deny_scan.EXIT_FINDINGS)
        self.assertIn("a.md:2:", out)
        repo.write("b.md", "zorblat \t  quix\n")
        self.assertIn("b.md:1:", repo.scan()[1])

    def test_regex_entry(self):
        repo = self.make(r"re:\b10\.77\.\d+\.\d+\b" + "\n")
        repo.write("a.md", "host at 10.77.3.4\n")
        code, out = repo.scan()
        self.assertEqual(code, deny_scan.EXIT_FINDINGS)
        self.assertNotIn("10.77", out)

    def test_accents_match_either_form(self):
        repo = self.make("José\n")  # composed
        repo.write("a.md", "met José today\n")  # decomposed
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    def test_utf16_file(self):
        repo = self.make("zorblat\n")
        repo.write("a.txt", "hello zorblat\n".encode("utf-16"))
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    # What the index scan reads

    def test_file_name_is_scanned_and_redacted(self):
        repo = self.make("zorblat\n")
        repo.write("notes/zorblat-setup.md", "clean body\n")
        code, out = repo.scan()
        self.assertEqual(code, deny_scan.EXIT_FINDINGS)
        self.assertIn("notes/[list line 1]-setup.md: file name matches list line 1", out)
        self.assertNotIn("zorblat", out.lower())

    def test_content_finding_redacts_the_file_name_too(self):
        repo = self.make("zorblat\n")
        repo.write("zorblat.md", "zorblat\n")
        self.assertNotIn("zorblat", repo.scan()[1].lower())

    def test_staged_content_not_disk(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "zorblat\n", commit=False)
        (repo.path / "a.md").write_text("clean on disk\n", encoding="utf-8")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    def test_file_deleted_on_disk_is_still_scanned(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "zorblat\n")
        (repo.path / "a.md").unlink()
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    def test_symlink_target_path_is_scanned(self):
        repo = self.make("zorblat\n")
        os.symlink("/home/zorblat/notes", repo.path / "link")
        git(repo.path, "add", "link")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    # Fail closed

    def test_missing_list_fails_closed(self):
        repo = self.make(None)
        repo.write("a.md", "anything\n")
        code, out = repo.scan()
        self.assertEqual(code, deny_scan.EXIT_NO_LIST)
        self.assertIn("FAIL (closed)", out)

    def test_empty_list_fails_closed(self):
        repo = self.make("# only a comment\n\n")
        repo.write("a.md", "anything\n")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_NO_LIST)

    def test_bad_regex_fails_closed(self):
        repo = self.make("re:(unclosed\n")
        repo.write("a.md", "anything\n")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_NO_LIST)

    def test_list_with_byte_order_mark(self):
        repo = self.make(None, raw="﻿zorblat\n".encode("utf-8"))
        repo.write("a.md", "zorblat\n")
        self.assertEqual(repo.scan()[0], deny_scan.EXIT_FINDINGS)

    def test_not_a_repo_fails_closed(self):
        repo = self.make("zorblat\n")
        os.environ[deny_scan.ENV_VAR] = str(repo.deny)
        self.addCleanup(os.environ.pop, deny_scan.ENV_VAR, None)
        with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deny_scan.main(["--repo", empty]), deny_scan.EXIT_GIT)

    # History

    def test_history_finds_a_removed_term(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "zorblat was here\n")
        repo.write("a.md", "cleaned up\n", message="clean")
        self.assertEqual(repo.scan()[0], 0)
        code, out = repo.scan("--history")
        self.assertEqual(code, deny_scan.EXIT_FINDINGS)
        self.assertIn("commit ", out)

    def test_history_scans_commit_messages(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "clean\n", message="fix the zorblat box")
        self.assertEqual(repo.scan()[0], 0)
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    def test_history_scans_committer(self):
        repo = self.make("zorblat.example\n")
        repo.write("a.md", "clean\n", env={"GIT_COMMITTER_EMAIL": "me@zorblat.example"})
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    def test_history_scans_other_branches(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "clean\n")
        git(repo.path, "checkout", "-q", "-b", "side")
        repo.write("b.md", "zorblat\n")
        git(repo.path, "checkout", "-q", "main")
        self.assertEqual(repo.scan()[0], 0)
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    def test_history_ignores_binary_attribute(self):
        repo = self.make("zorblat\n")
        repo.write(".gitattributes", "*.md binary\n")
        repo.write("a.md", "zorblat\n")
        repo.write("a.md", "clean\n", message="clean")
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    def test_history_non_ascii_file_name(self):
        repo = self.make("José Quix\n")
        repo.write("José Quix/a.md", "clean\n")
        git(repo.path, "rm", "-q", "-r", "José Quix")
        git(repo.path, "commit", "-q", "-m", "remove", env=None)
        self.assertEqual(repo.scan()[0], 0)
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    def test_history_scans_tag_messages_and_ref_names(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "clean\n")
        git(repo.path, "tag", "-a", "v1", "-m", "for zorblat")
        self.assertEqual(repo.scan("--history")[0], deny_scan.EXIT_FINDINGS)
        repo2 = self.make("zorblat\n")
        repo2.write("a.md", "clean\n")
        git(repo2.path, "branch", "zorblat-work")
        self.assertEqual(repo2.scan("--history")[0], deny_scan.EXIT_FINDINGS)

    # Pre-push

    def test_pre_push_scans_commits_being_pushed(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "zorblat\n")
        repo.write("a.md", "clean\n", message="clean")
        head = git(repo.path, "rev-parse", "HEAD").strip()
        line = f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"
        self.assertEqual(repo.scan()[0], 0)
        self.assertEqual(repo.scan("--pre-push", stdin=line)[0], deny_scan.EXIT_FINDINGS)

    def test_pre_push_skips_commits_the_remote_has(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "zorblat\n")
        repo.write("a.md", "clean\n", message="clean")
        old = git(repo.path, "rev-parse", "HEAD").strip()
        git(repo.path, "update-ref", "refs/remotes/origin/main", old)
        repo.write("b.md", "new and clean\n")
        head = git(repo.path, "rev-parse", "HEAD").strip()
        line = f"refs/heads/main {head} refs/heads/main {old}\n"
        self.assertEqual(repo.scan("--pre-push", stdin=line)[0], 0)

    def test_pre_push_delete_sends_nothing(self):
        repo = self.make("zorblat\n")
        repo.write("a.md", "clean\n")
        line = f"(delete) {'0' * 40} refs/heads/old {'1' * 40}\n"
        self.assertEqual(repo.scan("--pre-push", stdin=line)[0], 0)


if __name__ == "__main__":
    unittest.main()
