#!/usr/bin/env python3
"""Check or fold one-file-per-entry log fragments into their main log files.

Parallel PRs that all append to the same log file conflict on every merge. Instead, each new entry
is its own file in a fragment directory, and this script folds the fragments into the main file
later. See docs/patterns/one-file-per-log-entry.md.

Default logs (relative to --root):

    decisions.d/YYYY-MM-DD-<slug>.md  ->  decisions.md   newest first (new dates near the top)
    changelog.d/YYYY-MM-DD-<slug>.md  ->  CHANGELOG.md   oldest first (new dates at the end)

A fragment holds one entry exactly as it will appear in the main file: a "### Title" line, a
blank line, then at least one "- " bullet, and no other "### " line outside fenced code. No "#" or "## " headings: the date comes from the file name.
<slug> is lowercase letters, digits, and single hyphens. README.md in a fragment directory is
ignored.

Usage:
    python3 -I tools/fold_logs.py [--root DIR] [--check]   validate fragments (the default)
    python3 -I tools/fold_logs.py [--root DIR] --fold      fold every fragment, then delete it
    --config FILE      JSON in place of the default logs:
                           {"logs": [{"dir": "decisions.d", "main": "decisions.md",
                                      "order": "newest-first"},
                                     {"dir": "changelog.d", "main": "CHANGELOG.md",
                                      "order": "oldest-first"}],
                            "ignore": ["README.md"]}
    --log DIR MAIN ORDER   one log, repeatable; replaces the defaults and any --config logs

Folding puts each entry under a "## YYYY-MM-DD" heading, adding the heading when it is missing.
A heading with a suffix ("## 2026-01-02 (Fri)") counts for its date when there is no plain one.
Lines inside fenced code blocks are never read as headings. In a newest-first log, entries for a date that already has a heading go at the top of its
section; a new date goes before the first older dated heading, or before the first undated
heading after the dated ones (an "Earlier entries" section, say). In an oldest-first log, entries
go at the end of their date's section, and a new date goes after the last earlier one. Several
fragments on one day keep file-name order.

Safety: nothing is written unless every fragment passes the check and every main file exists.
Bytes outside the inserted entries are left unchanged (a CRLF main file gets CRLF entries). An
entry whose exact text is already under its date heading is not inserted twice, and a second run
does nothing. Each main file is written to a temp file beside it and swapped in with os.replace
only after every new file is ready; a fragment is deleted only after every swap succeeded and its
exact entry is in the new main file. Symlinked fragments, fragment folders, and main files are
refused, every path must resolve inside --root, and dotfiles (.gitkeep, .DS_Store) are skipped.

Exit codes: 0 fine, 1 a fragment or main file has a problem, or a write failed (nothing deleted),
2 bad usage or config. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath

NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
DATED_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ORDERS = ("newest-first", "oldest-first")
DEFAULT_LOGS = (
    ("decisions.d", "decisions.md", "newest-first"),
    ("changelog.d", "CHANGELOG.md", "oldest-first"),
)
DEFAULT_IGNORE = ("README.md",)
EXIT_PROBLEMS = 1
EXIT_USAGE = 2


class ConfigError(Exception):
    pass


class Fragment:
    def __init__(self, path, date, text):
        self.path = path
        self.date = date
        self.text = text  # normalized: LF line ends, exactly one trailing newline


def safe_rel(value, what):
    """A relative path inside the root, or ConfigError."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{what} must be a non-empty string")
    p = PurePosixPath(value.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        raise ConfigError(f"{what} must be a relative path inside the root: {value}")
    return str(p)


def load_config(path):
    """(logs, ignore) from a JSON config file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    logs = DEFAULT_LOGS
    if "logs" in data:
        if not isinstance(data["logs"], list) or not data["logs"]:
            raise ConfigError("config 'logs' must be a non-empty list")
        logs = []
        for n, item in enumerate(data["logs"], 1):
            if not isinstance(item, dict):
                raise ConfigError(f"logs[{n}] must be an object")
            logs.append((item.get("dir"), item.get("main"), item.get("order", "newest-first")))
    ignore = data.get("ignore", list(DEFAULT_IGNORE))
    if not isinstance(ignore, list) or not all(isinstance(i, str) for i in ignore):
        raise ConfigError("config 'ignore' must be a list of file names")
    return logs, tuple(ignore)


def validate_logs(logs):
    out, seen = [], set()
    for frag_dir, main, order in logs:
        frag_dir = safe_rel(frag_dir, "log dir")
        main = safe_rel(main, "log main file")
        if order not in ORDERS:
            raise ConfigError(f"order must be one of {', '.join(ORDERS)}: {order}")
        if frag_dir in seen or main in seen:
            raise ConfigError(f"each fragment dir and main file may appear once: {frag_dir}, {main}")
        seen.update((frag_dir, main))
        out.append((frag_dir, main, order))
    return out


def fragment_paths(frag_dir, ignore):
    if not frag_dir.is_dir():
        return []
    return sorted(p for p in frag_dir.iterdir() if p.name not in ignore and not p.name.startswith("."))


def inside(root, path):
    """True when path, fully resolved, is root or inside it (root already resolved)."""
    try:
        path.resolve().relative_to(root)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def path_problem(root, rel, what):
    """A problem string when root/rel is a symlink or resolves outside root, else None."""
    path = root / rel
    if path.is_symlink():
        return f"{rel}: {what} is a symlink; refused"
    if not inside(root, path):
        return f"{rel}: {what} resolves outside the root; refused"
    return None


def check_fragment(path, rel):
    """(problems, fragment). fragment is None when there are problems."""
    if path.is_symlink() or not path.is_file():
        return [f"{rel}: not a regular file"], None
    problems = []
    m = NAME_RE.match(path.name)
    if not m:
        problems.append(f"{rel}: name must match YYYY-MM-DD-<slug>.md (slug: a-z, 0-9, single hyphens)")
    else:
        try:
            datetime.date.fromisoformat(m.group(1))
        except ValueError:
            problems.append(f"{rel}: {m.group(1)} is not a real date")
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return problems + [f"{rel}: not readable UTF-8 text"], None
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines[0].startswith("### ") or not lines[0][4:].strip():
        problems.append(f"{rel}:1: first line must be '### <title>'")
    if len(lines) < 2 or lines[1].strip():
        problems.append(f"{rel}:2: second line must be blank")
    if not any(line.startswith("- ") for line in lines[2:]):
        problems.append(f"{rel}: no '- ' bullets after the title")
    fence = None
    for n, line in enumerate(lines, 1):
        fm = FENCE_RE.match(line)
        if fm:
            mark = fm.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None and n > 1 and line.startswith("### "):
            problems.append(f"{rel}:{n}: one '### ' entry per fragment; split it into two files")
    for n, line in enumerate(lines, 1):
        if re.match(r"^#{1,2}(\s|$)", line):
            problems.append(f"{rel}:{n}: no '#' or '## ' headings in a fragment; "
                            "the date comes from the file name")
    if problems:
        return problems, None
    text = raw.replace("\r\n", "\n").rstrip() + "\n"
    return [], Fragment(path, m.group(1), text)


def collect(root, logs, ignore):
    """(problems, {main: [Fragment]})."""
    problems, found = [], {}
    for frag_dir, main, _order in logs:
        frags = []
        bad_dir = path_problem(root, frag_dir, "fragment folder")
        if bad_dir:
            problems.append(bad_dir)
        else:
            for path in fragment_paths(root / frag_dir, ignore):
                rel = f"{frag_dir}/{path.name}"
                if not path.is_symlink() and not inside(root, path):
                    problems.append(f"{rel}: resolves outside the root; refused")
                    continue
                p, frag = check_fragment(path, rel)
                problems.extend(p)
                if frag:
                    frags.append(frag)
        main_path = root / main
        bad_main = path_problem(root, main, "main file")
        if bad_main:
            if frags or main_path.exists() or main_path.is_symlink():
                problems.append(bad_main)
        elif frags and not main_path.is_file():
            problems.append(f"{main}: main file is missing or not a regular file; create it first")
        found[main] = frags
    return problems, found


def headings(lines):
    """(line index, heading text, date or None) for each '## ' line outside fenced code."""
    out, fence = [], None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None and line.startswith("## "):
            text = line.rstrip("\r\n")
            dm = DATED_HEADING_RE.match(text)
            out.append((i, text, dm.group(1) if dm else None))
    return out


def section_end(lines, heads, start):
    """Index of the first '## ' heading after line start, or len(lines)."""
    for i, _t, _d in heads:
        if i > start:
            return i
    return len(lines)


def offset(lines, index):
    return sum(len(line) for line in lines[:index])


def norm_entry(text):
    """An entry compared by its exact text: LF line ends, no trailing whitespace on any line, no
    blank lines at either end."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


def section_entries(section_lines):
    """The '### ' entries of a date section (its lines after the heading), normalized. Lines in
    fenced code never start an entry."""
    entries, cur, fence = [], None, None
    for line in section_lines:
        m = FENCE_RE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
        elif fence is None and line.startswith("### "):
            if cur is not None:
                entries.append(cur)
            cur = []
        if cur is not None:
            cur.append(line)
    if cur is not None:
        entries.append(cur)
    return {norm_entry("".join(e)) for e in entries}


def date_sections(lines, heads, date):
    """Start indexes of the '## date' headings: plain ones if any, else ones with a suffix."""
    plain = [i for i, t, _d in heads if t.rstrip() == f"## {date}"]
    return plain or [i for i, _t, d in heads if d == date]


def entries_for(text, date):
    """Every normalized entry under any heading for date."""
    lines = text.splitlines(keepends=True)
    heads = headings(lines)
    found = set()
    for i, _t, d in heads:
        if d == date:
            found |= section_entries(lines[i + 1:section_end(lines, heads, i)])
    return found


def insert_block(text, pos, block, nl):
    """Insert block (ending with one nl) at char offset pos, separated by blank lines."""
    prefix, suffix = text[:pos], text[pos:]
    if not prefix or prefix.endswith("\n\n") or prefix.endswith("\r\n\r\n"):
        lead = ""
    elif prefix.endswith("\n"):
        lead = nl
    else:
        lead = nl + nl
    trail = "" if not suffix or suffix.startswith(("\n", "\r\n")) else nl
    return prefix + lead + block + trail + suffix


def fold_date(text, date, entries, order):
    """text with entries (each ending in one newline) placed under the '## date' heading."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    heads = headings(lines)
    existing = date_sections(lines, heads, date)
    if existing:
        start = existing[0] if order == "newest-first" else existing[-1]
        end = section_end(lines, heads, start)
        present = entries_for(text, date)
        entries = [e for e in entries if norm_entry(e) not in present]
        if not entries:
            return text
        block = "\n".join(entries).replace("\n", nl)
        if order == "newest-first":
            return insert_block(text, offset(lines, start + 1), block, nl)
        return insert_block(text, offset(lines, end), block, nl)

    block = (f"## {date}\n\n" + "\n".join(entries)).replace("\n", nl)
    dated = [(i, d) for i, _t, d in heads if d]
    if order == "newest-first":
        first_dated = dated[0][0] if dated else None
        for i, _t, d in heads:
            if (d and d < date) or (d is None and first_dated is not None and i > first_dated):
                return insert_block(text, offset(lines, i), block, nl)
        return insert_block(text, len(text), block, nl)
    earlier = [i for i, d in dated if d <= date]
    if earlier:
        return insert_block(text, offset(lines, section_end(lines, heads, earlier[-1])), block, nl)
    if dated:
        return insert_block(text, offset(lines, dated[0][0]), block, nl)
    return insert_block(text, len(text), block, nl)


def write_temp(path, data):
    """data in a temp file beside path (same mode), flushed and fsynced; returns its name."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o7777)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp


def report(problems):
    for p in problems:
        print(f"error: {p}", file=sys.stderr)


def check(root, logs, ignore):
    problems, found = collect(root, logs, ignore)
    if problems:
        report(problems)
        return EXIT_PROBLEMS
    print(f"{sum(len(v) for v in found.values())} fragment(s) OK.")
    return 0


def fold(root, logs, ignore):
    problems, found = collect(root, logs, ignore)
    if problems:
        report(problems)
        print("Nothing folded; fix the problems first.", file=sys.stderr)
        return EXIT_PROBLEMS
    # Work out, and verify, every new main file before writing anything.
    plans = []
    for _frag_dir, main, order in logs:
        frags = found[main]
        if not frags:
            continue
        main_path = root / main
        try:
            original = main_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report([f"{main}: cannot read as UTF-8 ({exc})"])
            print("Nothing folded.", file=sys.stderr)
            return EXIT_PROBLEMS
        text = original
        by_date = {}
        for frag in frags:  # already in file-name order
            by_date.setdefault(frag.date, []).append(frag)
        for date in sorted(by_date):
            text = fold_date(text, date, [f.text for f in by_date[date]], order)
        missing = [f for f in frags if norm_entry(f.text) not in entries_for(text, f.date)]
        if missing:
            report([f"{f.path.parent.name}/{f.path.name}: its entry would not be found in {main} "
                    "after the fold" for f in missing])
            print("Nothing folded.", file=sys.stderr)
            return EXIT_PROBLEMS
        plans.append((main, main_path, text if text != original else None, frags))
    temps = []
    try:
        for _main, main_path, text, _frags in plans:
            if text is not None:
                temps.append((write_temp(main_path, text.encode("utf-8")), main_path))
    except OSError as exc:
        for tmp, _p in temps:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        report([f"could not write a temp file: {exc}"])
        print("Nothing folded; no main file or fragment was changed.", file=sys.stderr)
        return EXIT_PROBLEMS
    done = 0
    try:
        for tmp, main_path in temps:
            os.replace(tmp, main_path)
            done += 1
    except OSError as exc:
        for tmp, _p in temps[done:]:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        report([f"could not replace a main file: {exc}"])
        print(f"{done} main file(s) were updated; no fragment was deleted. Run --fold again "
              "once the problem is fixed: entries already folded are not inserted twice.",
              file=sys.stderr)
        return EXIT_PROBLEMS
    total = 0
    for main, _main_path, _text, frags in plans:
        for frag in frags:
            try:
                frag.path.unlink()
            except OSError as exc:
                report([f"folded into {main} but could not delete {frag.path.name}: {exc}"])
                return EXIT_PROBLEMS
            print(f"folded {frag.path.parent.name}/{frag.path.name} into {main}")
            total += 1
    print(f"{total} fragment(s) folded.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate fragments (default)")
    mode.add_argument("--fold", action="store_true", help="fold fragments into the main files")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (default: cwd)")
    parser.add_argument("--config", type=Path, help="JSON config (see the docstring)")
    parser.add_argument("--log", nargs=3, action="append", metavar=("DIR", "MAIN", "ORDER"),
                        help="a fragment dir, its main file, and newest-first or oldest-first")
    args = parser.parse_args(argv)
    try:
        logs, ignore = DEFAULT_LOGS, DEFAULT_IGNORE
        if args.config:
            logs, ignore = load_config(args.config)
        if args.log:
            logs = [tuple(x) for x in args.log]
        logs = validate_logs(logs)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    root = args.root.resolve()
    if not root.is_dir():
        print(f"config error: root is not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE
    return fold(root, logs, ignore) if args.fold else check(root, logs, ignore)


if __name__ == "__main__":
    sys.exit(main())
