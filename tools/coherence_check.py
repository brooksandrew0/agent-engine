#!/usr/bin/env python3
"""Find docs that contradict each other, from rules in a JSON config. Code only, no model.

A repo whose docs are its configuration record drifts when many agents write to it: a plan header
still says "proposed" after its install record, a status row still waits on answers a plan
records. Each rule here turns one such contradiction into a check with an ID. See
docs/patterns/coherence-check.md.

Usage:
    python3 -I tools/coherence_check.py --config FILE [--root DIR] [--json] [--today YYYY-MM-DD]
        [--fail-on error|warn|never]

Exit codes: 0 no finding at or above --fail-on (default: error, so warnings never fail),
1 at least one such finding, 2 bad usage or config, or fold_logs.py missing beside this file
for a log-fragments rule. Read-only: it never writes to the repo.

Config (JSON). tools/coherence.example.json is a full example. Paths and globs are relative to
--root; globs use pathlib rules ("docs/plans/**/*.md"). Every regex is case-insensitive. Keys
starting with "_" are comments and are ignored; any other unknown key is a config error.

    {
      "status": {                          how a doc states its status (all optional)
        "front_matter_key": "status",      a `status:` key in leading --- front matter, else
        "line": "^\\W*Status\\W*:\\W*(.*)$",  the first line matching this (group 1 is the status)
        "lines": 15,                       within the first N lines
        "title": "^#\\s.*\\((proposed|draft)\\)\\s*$"   else a title like "# Plan (proposed)"
      },
      "rules": [ {"type": "...", "id": "...", "level": "error|warn", ...}, ... ]
    }

Rule types ("id" defaults to the type; "level" defaults as shown):

    stale-status (error)  A doc's status matches "claims" (and not "unless"), but the record says
        otherwise: a heading matching "record_heading" in the doc, a row of a "tables" file that
        links the doc and matches "row_says", or, with "follow_links": true, a doc linked from the
        status text that has a "record_heading". Keys: files, claims, unless, record_heading,
        tables, row_says, follow_links.
    stale-section (error)  A heading matching "heading" has a heading matching "record_heading"
        inside its section (before the next heading of the same or a higher level). Keys: files,
        heading, record_heading.
    missing-status (warn)  A doc with no status at all. Keys: files, exclude (globs).
    stale-open-status (warn)  The status matches "open" (and not "unless") and the newest date in
        it (or in the first status lines, when the doc has no front matter) is more than
        "max_days" old. Keys: files, open, unless, max_days, exclude.
    front-matter (error)  Front matter with a status not in "allowed", a key in "required" that
        is empty (reported as warn), a superseded doc with no `superseded_by`, a
        `superseded_by` or `supersedes` pointing at a missing file, a `supersedes` the other doc
        doesn't point back to, or a past `review_by` (warn) on a doc whose status is not in
        "closed". Keys: files, allowed, required, closed.
    answered-row (error)  A row of a "tables" file whose last cell matches "asks" (and not "done")
        links a doc with a line matching "answered" that carries a date newer than any date in the
        row's last cell. Keys: tables, asks, done, answered.
    implemented-by (error)  A doc whose front matter status is in "not_built" lists, in its "key"
        (default implemented_by), a doc that is live: its front matter status is in "live", or it
        has a heading matching "record_heading". Keys: files, key, not_built, live, record_heading.
    log-fragments (error)  Fragments in "dirs" whose name or shape breaks the one-file-per-entry
        rules. It runs the per-fragment checks of tools/fold_logs.py (which must sit beside this
        file), not fold_logs' checks of main files, symlinked folders, or paths outside the root.
        Dotfiles are skipped. Keys: dirs, ignore.

Links are Markdown links to .md files, resolved from the linking file's folder (a leading "/"
means the root); a link that leaves the root is ignored. Table rows are lines starting with "|";
a table's header row and separator are skipped.
"""

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

LEVELS = ("error", "warn")
DATE = re.compile(r"\b(\d{4})-(\d\d)-(\d\d)\b")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
LINK = re.compile(r"\]\(([^)#\s]+\.md)(#[^)]*)?\)")
SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")
DEFAULT_STATUS = {
    "front_matter_key": "status",
    "line": r"^\W*Status\W*:\W*(.*)$",
    "lines": 15,
    "title": None,
}

# For each rule type: default level, required keys, optional keys with defaults, and which keys
# are regexes or glob lists.
RULES = {
    "stale-status": ("error", ("files", "claims"),
                     {"unless": None, "record_heading": None, "tables": [], "row_says": None,
                      "follow_links": False}),
    "stale-section": ("error", ("files", "heading", "record_heading"), {}),
    "missing-status": ("warn", ("files",), {"exclude": []}),
    "stale-open-status": ("warn", ("files", "open", "max_days"), {"unless": None, "exclude": []}),
    "front-matter": ("error", ("files",),
                     {"allowed": None, "required": [], "closed": ["superseded", "archived"]}),
    "answered-row": ("error", ("tables", "asks", "answered"), {"done": None}),
    "implemented-by": ("error", ("files", "not_built"),
                       {"key": "implemented_by", "live": [], "record_heading": None}),
    "log-fragments": ("error", ("dirs",), {"ignore": ["README.md"]}),
}
REGEX_KEYS = {"claims", "unless", "record_heading", "row_says", "heading", "open", "asks", "done",
              "answered"}
LIST_KEYS = {"files", "exclude", "tables", "allowed", "required", "closed", "not_built", "live",
             "dirs", "ignore"}
COMMON_KEYS = {"type", "id", "level"}


class ConfigError(Exception):
    pass


class SetupError(Exception):
    pass


class Finding:
    def __init__(self, level, check, path, line, msg):
        self.level, self.check, self.path, self.line, self.msg = level, check, path, line, msg

    def as_dict(self):
        return {"level": self.level, "check": self.check, "path": self.path, "line": self.line,
                "msg": self.msg}

    def text(self):
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.level.upper():5} {self.check:18} {loc}  {self.msg}"


# ---- config ----

def compile_re(value, where):
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a regex string")
    try:
        return re.compile(value, re.I)
    except re.error as exc:
        raise ConfigError(f"{where} is not a valid regex: {exc}")


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    for key in data:
        if not key.startswith("_") and key not in ("status", "rules"):
            raise ConfigError(f"unknown top-level key '{key}'")
    status = dict(DEFAULT_STATUS)
    raw_status = data.get("status", {})
    if not isinstance(raw_status, dict):
        raise ConfigError("'status' must be an object")
    for key, val in raw_status.items():
        if key.startswith("_"):
            continue
        if key not in DEFAULT_STATUS:
            raise ConfigError(f"status: unknown key '{key}'")
        status[key] = val
    if not isinstance(status["lines"], int) or isinstance(status["lines"], bool) or status["lines"] < 1:
        raise ConfigError("status.lines must be a positive integer")
    for key in ("line", "title"):
        if status[key] is not None:
            status[key] = compile_re(status[key], f"status.{key}")
    if not isinstance(status["front_matter_key"], (str, type(None))):
        raise ConfigError("status.front_matter_key must be a string or null")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ConfigError("'rules' must be a non-empty list")
    return status, [load_rule(r, n) for n, r in enumerate(rules, 1)]


def load_rule(raw, n):
    if not isinstance(raw, dict):
        raise ConfigError(f"rules[{n}] must be an object")
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in RULES:
        raise ConfigError(f"rules[{n}]: unknown type {kind!r}; one of {', '.join(sorted(RULES))}")
    level, required, optional = RULES[kind]
    rule = {"type": kind, "id": raw.get("id", kind), "level": raw.get("level", level)}
    if not isinstance(rule["id"], str) or not rule["id"]:
        raise ConfigError(f"rules[{n}]: id must be a non-empty string")
    where = f"rules[{n}] ({rule['id']})"
    if not isinstance(rule["level"], str) or rule["level"] not in LEVELS:
        raise ConfigError(f"{where}: level must be one of {', '.join(LEVELS)}")
    for key in raw:
        if key.startswith("_") or key in COMMON_KEYS:
            continue
        if key not in required and key not in optional:
            raise ConfigError(f"{where}: unknown key '{key}'")
    for key in required:
        if key not in raw:
            raise ConfigError(f"{where}: missing '{key}'")
    for key, default in optional.items():
        rule[key] = raw.get(key, default)
    for key in required:
        rule[key] = raw[key]
    for key in list(rule):
        val = rule[key]
        if key in REGEX_KEYS and (val is not None or key in required):
            rule[key] = compile_re(val, f"{where}.{key}")
        elif key in LIST_KEYS and (val is not None or key in required):
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise ConfigError(f"{where}.{key} must be a list of strings")
            if key in ("files", "exclude", "tables", "dirs"):
                for v in val:
                    check_rel(v, f"{where}.{key}")
    if kind == "stale-open-status":
        md = rule["max_days"]
        if not isinstance(md, int) or isinstance(md, bool) or md < 0:
            raise ConfigError(f"{where}.max_days must be a non-negative integer")
    if kind == "stale-status" and not isinstance(rule["follow_links"], bool):
        raise ConfigError(f"{where}.follow_links must be true or false")
    if kind == "implemented-by" and not isinstance(rule["key"], str):
        raise ConfigError(f"{where}.key must be a string")
    return rule


def check_rel(value, where):
    if not value or value.startswith("/") or ".." in Path(value).parts:
        raise ConfigError(f"{where}: paths must be relative and stay inside the root: {value!r}")


# ---- reading docs ----

def read_lines(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def front_matter(lines):
    """Simple YAML subset: `key: value` and `key: [a, b]` between leading --- lines, or None."""
    if not lines or lines[0].strip() != "---":
        return None
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            fm[key] = val.strip("'\"")
    return None  # no closing ---: not front matter


def as_list(value):
    if isinstance(value, list):
        return value
    return [value] if value else []


def status_of(lines, fm, cfg):
    """(status text, line number), or (None, 0)."""
    key = cfg["front_matter_key"]
    if fm is not None and key and fm.get(key):
        return str(fm[key]), 1
    start = 0
    if fm is not None:
        start = next(i for i, line in enumerate(lines) if i > 0 and line.strip() == "---") + 1
    if cfg["line"] is not None:
        for i, line in enumerate(lines[start:start + cfg["lines"]], start=start + 1):
            m = cfg["line"].match(line)
            if m:
                return (m.group(1) if m.groups() else m.group(0)), i
    if cfg["title"] is not None:
        for i, line in enumerate(lines[start:start + 3], start=start + 1):
            m = cfg["title"].match(line)
            if m:
                return (m.group(1) if m.groups() else m.group(0)), i
    return None, 0


def newest_date(text):
    best = None
    for y, m, d in DATE.findall(text or ""):
        try:
            day = dt.date(int(y), int(m), int(d))
        except ValueError:
            continue
        best = day if best is None or day > best else best
    return best


def headings(lines):
    """[(line number, level, title)]."""
    return [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines, start=1)
            if (m := HEADING.match(line))]


def first_record(lines, pattern):
    if pattern is None:
        return None
    for ln, _level, title in headings(lines):
        if pattern.search(title):
            return ln
    return None


class Repo:
    def __init__(self, root, status_cfg):
        self.root = root
        self.status_cfg = status_cfg
        self._lines = {}
        self._tables = {}

    def rel(self, path):
        return path.relative_to(self.root).as_posix()

    def lines(self, rel):
        if rel not in self._lines:
            self._lines[rel] = read_lines(self.root / rel)
        return self._lines[rel]

    def files(self, globs, exclude=()):
        out = set()
        for g in globs:
            for p in self.root.glob(g):
                if p.is_file() and not p.is_symlink():
                    out.add(self.rel(p))
        for g in exclude:
            out -= {self.rel(p) for p in self.root.glob(g)}
        return sorted(out)

    def resolve(self, base_rel, href):
        """A link target as a root-relative path, or None when it is external or leaves the root.
        base_rel None means relative to the root."""
        href = href.strip()
        if not href or "://" in href or href.startswith("mailto:"):
            return None
        if href.startswith("/") or base_rel is None:
            cand = self.root / href.lstrip("/")
        else:
            cand = self.root / Path(base_rel).parent / href
        try:
            return Path(os.path.normpath(cand)).relative_to(self.root).as_posix()
        except ValueError:
            return None

    def links(self, base_rel, text):
        out = []
        for href, _ in LINK.findall(text):
            t = self.resolve(base_rel, href)
            if t is not None:
                out.append(t)
        return out

    def table_rows(self, table_rel):
        """[(line number, text, last cell, set of linked root-relative paths)]."""
        if table_rel in self._tables:
            return self._tables[table_rel]
        lines = self.lines(table_rel)
        rows = []
        for i, line in enumerate(lines):
            if not line.lstrip().startswith("|") or SEPARATOR.match(line.strip()):
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if SEPARATOR.match(nxt):
                continue  # header row
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            rows.append((i + 1, line, cells[-1] if cells else "", set(self.links(table_rel, line))))
        self._tables[table_rel] = rows
        return rows

    def doc(self, rel):
        lines = self.lines(rel)
        fm = front_matter(lines)
        status, sline = status_of(lines, fm, self.status_cfg)
        return lines, fm, status, sline


# ---- rules ----

def rule_stale_status(repo, rule, add):
    for rel in repo.files(rule["files"]):
        lines, _fm, status, sline = repo.doc(rel)
        if not status:
            continue
        claim = rule["claims"].search(status)
        if not claim or (rule["unless"] and rule["unless"].search(status)):
            continue
        evidence = []
        ln = first_record(lines, rule["record_heading"])
        if ln:
            evidence.append(f"a record heading at line {ln}")
        if rule["row_says"] is not None:
            for table in rule["tables"]:
                hit = next((rn for rn, text, _c, targets in repo.table_rows(table)
                            if rel in targets and rule["row_says"].search(text)), None)
                if hit:
                    evidence.append(f"{table}:{hit} says otherwise")
        if rule["follow_links"]:
            for target in repo.links(rel, status):
                if target != rel and (repo.root / target).is_file():
                    tln = first_record(repo.lines(target), rule["record_heading"])
                    if tln:
                        evidence.append(f"the doc it links, {target}, has a record heading at line {tln}")
                        break
        if evidence:
            add(rel, sline, f"status says \"{claim.group(0)}\" but {'; '.join(evidence)}")


def rule_stale_section(repo, rule, add):
    for rel in repo.files(rule["files"]):
        heads = headings(repo.lines(rel))
        for idx, (ln, level, title) in enumerate(heads):
            if not rule["heading"].search(title):
                continue
            end = next((h[0] for h in heads[idx + 1:] if h[1] <= level), None)
            inside = [h for h in heads[idx + 1:] if (end is None or h[0] < end)
                      and rule["record_heading"].search(h[2])]
            if inside:
                add(rel, ln, f"heading says \"{rule['heading'].search(title).group(0)}\" but a record "
                             f"heading at line {inside[0][0]} is inside its section")


def rule_missing_status(repo, rule, add):
    for rel in repo.files(rule["files"], rule["exclude"]):
        if repo.doc(rel)[2] is None:
            add(rel, 0, "no status")


def rule_stale_open_status(repo, rule, add, today):
    cfg = repo.status_cfg
    for rel in repo.files(rule["files"], rule["exclude"]):
        lines, fm, status, sline = repo.doc(rel)
        if not status:
            continue
        hit = rule["open"].search(status)
        if not hit or (rule["unless"] and rule["unless"].search(status)):
            continue
        when = newest_date(status)
        if when is None and fm is None:
            when = newest_date("\n".join(lines[:cfg["lines"]]))
        if when is not None and (today - when).days > rule["max_days"]:
            add(rel, sline, f"status still open (\"{hit.group(0)}\") and its newest date is {when} "
                            f"({(today - when).days} days)")


def rule_front_matter(repo, rule, add, today):
    key = repo.status_cfg["front_matter_key"] or "status"
    closed = {c.lower() for c in rule["closed"]}
    for rel in repo.files(rule["files"]):
        fm = front_matter(repo.lines(rel))
        if fm is None:
            continue
        st = str(fm.get(key, "")).lower()
        if rule["allowed"] is not None and st and st not in {a.lower() for a in rule["allowed"]}:
            add(rel, 1, f"{key} \"{st}\" is not one of {sorted(rule['allowed'])}")
        for req in rule["required"]:
            if not fm.get(req):
                add(rel, 1, f"missing `{req}`", level="warn")

        sup_by = as_list(fm.get("superseded_by"))
        if st == "superseded" and not sup_by:
            add(rel, 1, "status superseded but no `superseded_by`")
        if sup_by:
            t, ok = link_target(repo, rel, sup_by[0])
            if t is not None and not ok:
                add(rel, 1, f"superseded_by points at a missing file: {sup_by[0]}")
            if st not in closed:
                add(rel, 1, f"has superseded_by but {key} is \"{st or 'none'}\"")
        for s in as_list(fm.get("supersedes")):
            t, ok = link_target(repo, rel, s)
            if t is None:
                continue
            if not ok:
                add(rel, 1, f"supersedes a missing file: {s}")
                continue
            back = as_list((front_matter(repo.lines(t)) or {}).get("superseded_by"))
            if not back or link_target(repo, t, back[0]) != (rel, True):
                add(rel, 1, f"supersedes {s}, but that file's superseded_by does not point back")
        rb = fm.get("review_by")
        if rb:
            when = newest_date(str(rb))
            if when is None:
                add(rel, 1, f"review_by is not a date: {rb}", level="warn")
            elif when < today and st not in closed:
                add(rel, 1, f"review_by {when} has passed ({(today - when).days} days)", level="warn")


def link_target(repo, base_rel, value):
    """(root-relative path, exists) for a front matter path: tried from the doc's folder, then
    from the root. (None, False) when it is external or leaves the root."""
    first = repo.resolve(base_rel, value)
    for t in (first, repo.resolve(None, value)):
        if t is not None and (repo.root / t).is_file():
            return t, True
    return first, False


def rule_answered_row(repo, rule, add):
    for table in rule["tables"]:
        for rn, _text, last, targets in repo.table_rows(table):
            if not rule["asks"].search(last) or (rule["done"] and rule["done"].search(last)):
                continue
            row_date = newest_date(last)
            for rel in sorted(targets):
                found = None
                for ln, line in enumerate(repo.lines(rel), start=1):
                    m = rule["answered"].search(line)
                    if not m:
                        continue
                    when = newest_date(line)
                    if when is None or (row_date is not None and row_date >= when):
                        continue
                    found = (ln, when)
                    break
                if found:
                    add(table, rn, f"row still waits on an answer, but {rel}:{found[0]} records it "
                                   f"({found[1]}); update the row's last cell")
                    break


def rule_implemented_by(repo, rule, add):
    key = repo.status_cfg["front_matter_key"] or "status"
    not_built = {s.lower() for s in rule["not_built"]}
    live = {s.lower() for s in rule["live"]}
    for rel in repo.files(rule["files"]):
        fm = front_matter(repo.lines(rel))
        if fm is None or str(fm.get(key, "")).lower() not in not_built:
            continue
        for t in as_list(fm.get(rule["key"])):
            trel, ok = link_target(repo, rel, t)
            if not ok:
                continue
            tlines = repo.lines(trel)
            tfm = front_matter(tlines) or {}
            why = None
            if str(tfm.get(key, "")).lower() in live:
                why = f"its {key} is {tfm[key]}"
            else:
                ln = first_record(tlines, rule["record_heading"])
                if ln:
                    why = f"it has a record heading at line {ln}"
            if why:
                add(rel, 1, f"{key} {fm[key]}, but {trel} in its {rule['key']} is live ({why})")
                break


FOLD_LOGS = Path(__file__).resolve().parent / "fold_logs.py"


def load_fold_logs(path=None):
    """tools/fold_logs.py, loaded by path (python3 -I does not put this folder on sys.path)."""
    path = Path(path or FOLD_LOGS)
    if not path.is_file():
        raise SetupError(f"the log-fragments rule needs fold_logs.py beside this script: {path} is missing")
    try:
        spec = importlib.util.spec_from_file_location("fold_logs", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # a broken fold_logs.py
        raise SetupError(f"cannot load {path}: {exc}")
    if not all(hasattr(mod, name) for name in ("fragment_paths", "check_fragment")):
        raise SetupError(f"{path} has no fragment_paths and check_fragment")
    return mod


def rule_log_fragments(repo, rule, add):
    fold_logs = load_fold_logs()
    for d in rule["dirs"]:
        for path in fold_logs.fragment_paths(repo.root / d, set(rule["ignore"])):
            rel = f"{d.rstrip('/')}/{path.name}"
            problems, _ = fold_logs.check_fragment(path, rel)
            for p in problems:
                m = re.match(re.escape(rel) + r"(?::(\d+))?: (.*)$", p, re.S)
                if m:
                    add(rel, int(m.group(1) or 0), m.group(2))
                else:
                    add(rel, 0, p)


def run(root, config, today):
    status_cfg, rules = config
    repo = Repo(Path(root).resolve(), status_cfg)
    findings = []
    for rule in rules:
        def add(path, line, msg, level=None, rule=rule):
            findings.append(Finding(level or rule["level"], rule["id"], path, line, msg))

        kind = rule["type"]
        if kind == "stale-status":
            rule_stale_status(repo, rule, add)
        elif kind == "stale-section":
            rule_stale_section(repo, rule, add)
        elif kind == "missing-status":
            rule_missing_status(repo, rule, add)
        elif kind == "stale-open-status":
            rule_stale_open_status(repo, rule, add, today)
        elif kind == "front-matter":
            rule_front_matter(repo, rule, add, today)
        elif kind == "answered-row":
            rule_answered_row(repo, rule, add)
        elif kind == "implemented-by":
            rule_implemented_by(repo, rule, add)
        elif kind == "log-fragments":
            rule_log_fragments(repo, rule, add)
    order = {"error": 0, "warn": 1}
    findings.sort(key=lambda f: (order[f.level], f.check, f.path, f.line))
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find docs that contradict each other.")
    ap.add_argument("--config", required=True, help="JSON rules (see the docstring)")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--fail-on", choices=("error", "warn", "never"), default="error")
    a = ap.parse_args(argv)
    try:
        config = load_config(a.config)
        today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except ValueError:
        print(f"config error: --today must be YYYY-MM-DD: {a.today}", file=sys.stderr)
        return 2
    root = Path(a.root)
    if not root.is_dir():
        print(f"config error: root is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        findings = run(root, config, today)
    except SetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    counts = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in LEVELS}
    if a.json:
        print(json.dumps({"today": today.isoformat(), "counts": counts,
                          "findings": [f.as_dict() for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f.text())
        print(f"coherence-check {today}: {counts['error']} error, {counts['warn']} warn")
    if a.fail_on == "never":
        return 0
    levels = ("error",) if a.fail_on == "error" else LEVELS
    return 1 if any(f.level in levels for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
