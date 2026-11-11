"""Tests for tools/ci_local.py. Checks are small Python one-liners run in temp dirs; nothing here
needs gitleaks or the deny list, and the built-in set is inspected, never run."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ci_local  # noqa: E402

PY = "{python}"


def ok(name, **extra):
    return {"name": name, "command": [PY, "-c", "pass"], **extra}


def bad(name):
    return {"name": name, "command": [PY, "-c", "raise SystemExit(3)"]}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_quiet(self, fn, *args, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(*args, **kw)
        return code, out.getvalue(), err.getvalue()

    def write_config(self, data, name="ci_local.json"):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class BuiltinTests(Base):
    def test_no_config_uses_builtin_set(self):
        checks = ci_local.load_checks(self.root)
        self.assertEqual([c["name"] for c in checks], ["tests", "deny-scan", "gitleaks"])
        self.assertEqual(ci_local.validate(checks), checks)

    def test_builtin_commands_unchanged(self):
        by = {c["name"]: c for c in ci_local.builtin_checks()}
        root = Path("/r")
        self.assertEqual(ci_local.expand(by["tests"]["command"], root),
                         [sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "."])
        deny = str(Path(ci_local.__file__).resolve().parent / "deny_scan.py")
        self.assertEqual(ci_local.expand(by["deny-scan"]["command"], root),
                         [sys.executable, "-I", deny, "--repo", str(root)])
        self.assertEqual(ci_local.expand(by["deny-scan"]["history_command"], root)[-1], "--history")
        self.assertEqual(by["gitleaks"]["requires"], "gitleaks")
        self.assertEqual(by["gitleaks"]["command"][1], "dir")
        self.assertEqual(by["gitleaks"]["history_command"][1], "git")

    def test_builtin_gitleaks_skips_when_missing(self):
        gl = ci_local.builtin_checks()[2]
        with mock.patch.object(ci_local.shutil, "which", return_value=None):
            code, out, _ = self.run_quiet(ci_local.run_checks, [gl], self.root)
        self.assertEqual(code, 2)
        self.assertIn("gitleaks: skipped", out)

    def test_builtin_deny_scan_found_from_this_file_with_other_root(self):
        # --root elsewhere, no config: the deny scan path must not depend on the root
        deny = ci_local.builtin_checks()[1]["command"][2]
        self.assertTrue(Path(deny).is_absolute())
        self.assertTrue(Path(deny).is_file())
        self.assertFalse(str(deny).startswith(str(self.root)))

    def test_first_line_names_builtin_set(self):
        with mock.patch.object(ci_local, "run_checks", return_value=0):
            code, out, _ = self.run_quiet(ci_local.main, ["--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue(out.splitlines()[0].startswith("== config: built-in set"))

    def test_this_repo_has_builtin_or_valid_config(self):
        ci_local.load_checks(ci_local.ROOT)  # raises ConfigError if a config is there and broken


class RunTests(Base):
    def test_all_pass(self):
        code, out, _ = self.run_quiet(ci_local.run_checks, [ok("a"), ok("b")], self.root)
        self.assertEqual(code, 0)
        self.assertIn("a: pass  b: pass", out)

    def test_fail_beats_skip(self):
        checks = [ok("a"), bad("b"), ok("c", requires="no-such-tool-xyz")]
        code, out, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 1)
        self.assertIn("b: FAIL", out)
        self.assertIn("c: skipped", out)

    def test_skip_only_is_2(self):
        checks = [ok("a"), ok("c", requires="no-such-tool-xyz")]
        code, out, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 2)
        self.assertIn("no-such-tool-xyz not installed", out)

    def test_requires_present_runs(self):
        checks = [ok("a", requires=Path(sys.executable).name)]
        with mock.patch.object(ci_local.shutil, "which", return_value=sys.executable):
            code, _, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 0)

    def test_missing_command_fails(self):
        checks = [{"name": "x", "command": ["no-such-command-xyz"]}]
        code, out, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 1)
        self.assertIn("can't run", out)

    def test_runs_in_root_with_placeholders(self):
        marker = "import os, sys; open(os.path.join(sys.argv[1], 'seen'), 'w').write(os.getcwd())"
        checks = [{"name": "w", "command": [PY, "-c", marker, "{root}"]}]
        code, _, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 0)
        self.assertEqual(Path((self.root / "seen").read_text()).resolve(), self.root.resolve())

    def test_placeholders_inside_arguments_and_empty_args(self):
        code_ = ("import sys; assert sys.argv[1] == '', sys.argv; "
                 "assert sys.argv[2] == '--repo=' + sys.argv[3], sys.argv")
        checks = [{"name": "p", "command": [PY, "-c", code_, "", "--repo={root}", "{root}"]}]
        code, _, _ = self.run_quiet(ci_local.run_checks, checks, self.root)
        self.assertEqual(code, 0)
        self.assertEqual(ci_local.expand(["x{python}y", "a{root}b{root}"], Path("/r")),
                         [f"x{sys.executable}y", "a/rb/r"])

    def test_history_command(self):
        check = {"name": "h", "command": [PY, "-c", "pass"],
                 "history_command": [PY, "-c", "raise SystemExit(1)"]}
        self.assertEqual(self.run_quiet(ci_local.run_checks, [check], self.root)[0], 0)
        self.assertEqual(self.run_quiet(ci_local.run_checks, [check], self.root, history=True)[0], 1)
        # without history_command, --history runs the normal command
        self.assertEqual(self.run_quiet(ci_local.run_checks, [ok("n")], self.root, history=True)[0], 0)


class ConfigTests(Base):
    def test_default_config_file_at_root(self):
        self.write_config({"checks": [ok("only")]})
        self.assertEqual([c["name"] for c in ci_local.load_checks(self.root)], ["only"])

    def test_list_form(self):
        path = self.write_config([ok("a"), bad("b")], name="other.json")
        self.assertEqual(len(ci_local.load_checks(self.root, path)), 2)

    def test_main_with_config(self):
        path = self.write_config([ok("a"), ok("b", requires="no-such-tool-xyz")], name="c.json")
        code, out, _ = self.run_quiet(ci_local.main, ["--root", str(self.root), "--config", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("a: pass", out)
        self.assertEqual(out.splitlines()[0], f"== config: {path}")

    def test_main_default_config(self):
        self.write_config([bad("x")])
        code, out, _ = self.run_quiet(ci_local.main, ["--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("x: FAIL", out)
        self.assertEqual(out.splitlines()[0], f"== config: {self.root.resolve() / 'ci_local.json'}")

    def test_missing_explicit_config(self):
        code, _, err = self.run_quiet(ci_local.main, ["--root", str(self.root),
                                                      "--config", str(self.root / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("can't read", err)

    def test_invalid_json(self):
        (self.root / "ci_local.json").write_text("{not json", encoding="utf-8")
        code, _, err = self.run_quiet(ci_local.main, ["--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)

    def test_validation_errors(self):
        cases = [
            ({}, "top level"),
            ({"checks": []}, "no checks"),
            ([], "no checks"),
            (["x"], "not an object"),
            ([{"command": [PY]}], "'name'"),
            ([{"name": "a"}], "'command'"),
            ([{"name": "a", "command": "echo hi"}], "'command'"),
            ([{"name": "a", "command": []}], "'command'"),
            ([{"name": "a", "command": [PY, 3]}], "'command'"),
            ([{"name": "a", "command": ["", "x"]}], "program name first"),
            ([ok("a"), ok("a")], "twice"),
            ([ok("a", requires="")], "'requires'"),
            ([ok("a", requires=["x"])], "'requires'"),
            ([ok("a", history_command=[])], "'history_command'"),
            ([ok("a", extra=1)], "unknown key"),
        ]
        for data, needle in cases:
            with self.subTest(data=data):
                with self.assertRaises(ci_local.ConfigError) as cm:
                    ci_local.validate(data)
                self.assertIn(needle, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
