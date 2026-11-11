"""Tests for tools/session_usage.py. Transcripts are synthetic JSONL files in temp dirs."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import session_usage as su  # noqa: E402


def msg(mid, ts, model="model-a", i=1, o=10, cr=0, cw=0):
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {
        "id": mid, "model": model, "usage": {"input_tokens": i, "output_tokens": o,
                                             "cache_read_input_tokens": cr,
                                             "cache_creation_input_tokens": cw}}})


def build(root: Path):
    d = root / "proj"
    sub = d / "S1" / "subagents"
    sub.mkdir(parents=True)
    (d / "S1.jsonl").write_text("\n".join([
        msg("a", "2026-11-07T10:00:00Z", o=5, cr=1000),
        msg("a", "2026-11-07T10:00:01Z", o=20, cr=1000),  # streamed duplicate: last copy wins
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        "not json",
        "[1, 2]",
        msg("z", "2026-11-07T10:00:02Z", model="<synthetic>", o=999),
        msg("b", "2026-11-08T10:00:00Z", model="model-b", o=10, cr=3000, cw=200),
    ]))
    (sub / "agent-b1.jsonl").write_text(msg("c", "2026-11-07T11:00:00Z", i=100, o=100))
    (sub / "agent-b1.meta.json").write_text(json.dumps({"description": "Build the thing"}))
    (sub / "agent-r1.jsonl").write_text(msg("d", "2026-11-07T12:00:00Z", i=50, o=40))
    (sub / "agent-r1.meta.json").write_text(json.dumps({"description": "Second judge pass"}))
    (sub / "agent-x1.jsonl").write_text(msg("e", "2026-11-07T12:00:00Z"))  # no meta file
    (sub / "agent-y1.jsonl").write_text(msg("f", "2026-11-07T12:00:00Z"))
    (sub / "agent-y1.meta.json").write_text("{broken")
    other = root / "other-proj"
    other.mkdir()
    (other / "S2.jsonl").write_text(msg("g", "2026-11-07T13:00:00Z", i=7, o=3))
    return root


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_names(self, *ids, **kw):
        agents, missing = su.find_run(self.root, "S1", ids, **kw)
        return {x["name"]: x for x in agents}, missing

    def test_dedupe_and_totals(self):
        a, missing = self.run_names()
        self.assertEqual(missing, [])
        main = a["main thread"]
        self.assertEqual((main["turns"], main["output"], main["cache_read"], main["cache_write"]),
                         (2, 30, 4000, 200))
        self.assertEqual(main["peak_ctx"], 3201)
        self.assertEqual(main["avg_ctx"], (1001 + 3201) / 2)
        self.assertEqual(main["models"]["model-b"], 1)
        self.assertNotIn("<synthetic>", main["models"])

    def test_roles(self):
        a, _ = self.run_names()
        roles = {name: x["role"] for name, x in a.items()}
        self.assertEqual(roles, {"main thread": "coordinator", "Build the thing": "builder",
                                 "Second judge pass": "reviewer", "agent-x1": "builder",
                                 "agent-y1": "builder"})
        for d in ("security review", "Review PR", "judge"):
            self.assertEqual(su.classify(d), "reviewer")
        self.assertEqual(su.classify(""), "builder")

    def test_weights(self):
        t = {"input": 10, "output": 10, "cache_read": 100, "cache_write": 8, "model": "m"}
        self.assertEqual(su.weighted(t), 10 + 50 + 10 + 10)

    def test_window(self):
        since, until = su.parse_time("2026-11-07"), su.parse_time("2026-11-08")
        a, _ = self.run_names(since=since, until=until)
        self.assertEqual(a["main thread"]["turns"], 1)
        a, _ = self.run_names(since=until)
        self.assertEqual(a["main thread"]["turns"], 1)
        self.assertEqual(a["Build the thing"]["turns"], 0)

    def test_agent_filter(self):
        a, missing = self.run_names("b1", "agent-r1")
        self.assertEqual(set(a), {"main thread", "Build the thing", "Second judge pass"})
        self.assertEqual(missing, [])

    def test_extra_session_and_missing(self):
        a, missing = self.run_names("S2", "nope")
        self.assertIn("session S2", a)
        self.assertEqual(a["session S2"]["role"], "builder")
        self.assertEqual(a["session S2"]["input"], 7)
        self.assertEqual(missing, ["nope"])
        self.assertNotIn("Build the thing", a)  # ids given: only those are counted

    def test_missing_coordinator(self):
        agents, missing = su.find_run(self.root, "NOPE")
        self.assertEqual((agents, missing), ([], ["NOPE"]))
        self.assertIn("no transcript found", su.report("NOPE", agents, missing))

    def test_report_and_cli(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = su.main(["S1", "--projects", str(self.root)])
        out = buf.getvalue()
        self.assertEqual(code, 0)
        for s in ("per role", "coordinator", "builder", "reviewer", "peak ctx", "model mix",
                  "totals: 6 turns", "cache read 4,000", "for ranking only", "other work"):
            self.assertIn(s, out)
        shares = [float(line.split("%")[0].split()[-1]) for line in out.splitlines()
                  if line.startswith("  ") and line.split()[0] in su.ROLES]
        self.assertEqual(len(shares), 3)
        self.assertAlmostEqual(sum(shares), 100.0, delta=0.2)

    def test_bad_id(self):
        with self.assertRaises(Exception):
            su.find_run(self.root, "../x")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            su.main(["S1", "a/b", "--projects", str(self.root)])
        self.assertEqual(cm.exception.code, 2)

    def test_sidechain_and_cross_file_dedupe(self):
        d = self.root / "proj"
        sub = d / "S3" / "subagents"
        sub.mkdir(parents=True)
        side = json.loads(msg("s1", "2026-11-07T10:00:00Z", i=500, o=500))
        side["isSidechain"] = True
        side2 = json.loads(msg("s2", "2026-11-07T10:00:00Z", i=40))
        side2["isSidechain"] = True
        (d / "S3.jsonl").write_text("\n".join([
            msg("m1", "2026-11-07T10:00:00Z", i=1), json.dumps(side), json.dumps(side2),
            msg("dup", "2026-11-07T10:00:00Z", i=9)]))
        (sub / "agent-k.jsonl").write_text("\n".join([
            msg("s1", "2026-11-07T10:00:00Z", i=500, o=500),
            msg("dup", "2026-11-07T10:00:00Z", i=9)]))
        agents, _ = su.find_run(self.root, "S3")
        a = {x["name"]: x for x in agents}
        self.assertEqual(a["main thread"]["turns"], 1)  # m1 only: sidechain lines and dup skipped
        self.assertEqual(a["agent-k"]["turns"], 2)
        self.assertEqual(sum(x["turns"] for x in agents), 3)
        # no subagent file read: sidechain lines stay with the main thread
        (sub / "agent-k.jsonl").unlink()
        a = {x["name"]: x for x in su.find_run(self.root, "S3")[0]}
        self.assertEqual(a["main thread"]["turns"], 4)

    def test_non_numeric_usage(self):
        line = json.loads(msg("n1", "2026-11-07T10:00:00Z", i=5))
        line["message"]["usage"].update({"output_tokens": "lots", "cache_read_input_tokens": [1],
                                         "cache_creation_input_tokens": True})
        d = self.root / "proj"
        (d / "S4.jsonl").write_text(json.dumps(line) + "\n" + msg("n2", "2026-11-07T10:00:00Z", o="7"))
        agents, _ = su.find_run(self.root, "S4")
        self.assertEqual((agents[0]["input"], agents[0]["output"], agents[0]["skipped"]), (6, 7, 3))
        self.assertIn("skipped values: 3 usage values", su.report("S4", agents))
        self.assertNotIn("skipped values", su.report("S1", su.find_run(self.root, "S1")[0]))

    def test_reviewer_whole_words(self):
        for d in ("Preview the site", "Reviewless", "judgement call"):
            self.assertEqual(su.classify(d), "builder", d)
        for d in ("Code reviewer pass", "Reviewing the PR", "judges panel", "security-scan"):
            self.assertEqual(su.classify(d), "reviewer", d)

    def test_default_root(self):
        self.assertEqual(su.DEFAULT_PROJECTS, Path.home() / ".claude" / "projects")


if __name__ == "__main__":
    unittest.main()
