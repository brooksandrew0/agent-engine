#!/usr/bin/env python3
"""Scan this repo for private terms before anything is pushed.

The term list lives outside the repo, so publishing the repo never publishes the list. Findings name
where a match is and the term's line number in the list, never the term itself (a matched part of a
file name is shown as [list line N]), so the output is safe to paste into a PR.

List format (one entry per line):
    # comment                  ignored, as are blank lines
    Some Name                  whole words, case-insensitive; any whitespace (a line break too)
                               may sit between the words. Plurals don't match: list them.
    re:<python regex>          case-insensitive regex, for IPs, ID patterns, and the like

What is scanned:
    (default)        every entry in git's index: its path and its staged content (a symlink's target)
    --history        also every commit on every ref (author, committer, message, full patch, merges
                     against each parent) and every ref name, tagger, and tag message
    --pre-push       read git's pre-push lines on stdin and scan the commits being pushed that no
                     remote-tracking ref has yet (used by .githooks/pre-push)

Exit codes: 0 clean, 1 findings, 3 the list is missing, empty, or unreadable (fails closed),
4 a git command failed (fails closed).
"""

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

DEFAULT_LIST = Path.home() / ".config" / "agent-engine" / "deny.txt"
ENV_VAR = "AGENT_ENGINE_DENY"
EXIT_FINDINGS = 1
EXIT_NO_LIST = 3
EXIT_GIT = 4
ZERO_SHA = re.compile(r"^0+$")
GIT_C = ["-c", "core.quotePath=false"]
SHOW_FORMAT = "--format=author %an <%ae>%ncommitter %cn <%ce>%n%B"


class GitError(Exception):
    pass


class Term:
    def __init__(self, number, pattern):
        self.number = number  # line number in the list, shown instead of the term
        self.pattern = pattern


def norm(text):
    return unicodedata.normalize("NFC", text)


def list_path():
    value = os.environ.get(ENV_VAR)
    return Path(value).expanduser() if value else DEFAULT_LIST


def plain_pattern(entry):
    words = [re.escape(norm(w)) for w in entry.split()]
    return r"(?<![\w])" + r"\s+".join(words) + r"(?![\w])"


def load_terms(path):
    """Read the list. Returns (terms, error). An error means the scan must fail closed."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [], f"deny list not found at {path} (set {ENV_VAR} or create it)"
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"deny list at {path} can't be read: {exc.__class__.__name__}"
    terms = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            source = norm(line[3:])
            if not source:
                return [], f"deny list line {number}: empty regex"
        else:
            source = plain_pattern(line)
        try:
            terms.append(Term(number, re.compile(source, re.IGNORECASE)))
        except re.error:
            return [], f"deny list line {number}: invalid regex"
    if not terms:
        return [], f"deny list at {path} has no entries"
    return terms, None


def decode(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8", "replace")
    return norm(text)


def scan_text(terms, text):
    """Yield (line number, term number) for every match, across line breaks."""
    for term in terms:
        for match in term.pattern.finditer(text):
            yield text.count("\n", 0, match.start()) + 1, term.number


def redact(terms, text):
    for term in terms:
        text = term.pattern.sub(f"[list line {term.number}]", text)
    return text


def git(repo, *args, stdin=None):
    try:
        proc = subprocess.run(["git", *GIT_C, "-C", str(repo), *args], input=stdin,
                              capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitError(f"git {args[0]} failed") from exc
    return proc.stdout


def index_entries(repo):
    """(path, blob sha) for every entry in the index."""
    out = git(repo, "ls-files", "-s", "-z").decode("utf-8", "surrogateescape")
    entries = []
    for record in filter(None, out.split("\0")):
        meta, path = record.split("\t", 1)
        mode, sha, _stage = meta.split()
        if mode != "160000":  # a submodule has no blob here
            entries.append((path, sha))
    return entries


def read_blobs(repo, shas):
    """Blob contents by sha, read from git, not from disk."""
    if not shas:
        return {}
    out = git(repo, "cat-file", "--batch", stdin="".join(s + "\n" for s in shas).encode())
    blobs, pos = {}, 0
    for sha in shas:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        size = int(header[2])
        blobs[sha] = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def scan_index(terms, repo):
    findings = []
    entries = index_entries(repo)
    blobs = read_blobs(repo, sorted({sha for _, sha in entries}))
    for path, sha in entries:
        shown = redact(terms, norm(path))
        for _, number in scan_text(terms, norm(path)):
            findings.append(f"{shown}: file name matches list line {number}")
        for lineno, number in scan_text(terms, decode(blobs[sha])):
            findings.append(f"{shown}:{lineno}: matches list line {number}")
    return findings


def scan_commits(terms, repo, rev_args):
    findings = []
    shas = git(repo, "rev-list", *rev_args).decode().split()
    for sha in shas:
        body = git(repo, "show", "-m", "--text", "--patch", "--no-color", "--no-ext-diff",
                   "--no-textconv", SHOW_FORMAT, sha)
        for lineno, number in scan_text(terms, decode(body)):
            findings.append(f"commit {sha[:12]} (line {lineno} of its header, message, and patch): "
                            f"matches list line {number}")
    return findings


def scan_refs(terms, repo):
    out = git(repo, "for-each-ref",
              "--format=%(refname)%0a%(taggername) %(taggeremail)%0a%(contents)%0a")
    return [f"ref names and tags (line {lineno}): matches list line {number}"
            for lineno, number in scan_text(terms, decode(out))]


def pre_push_revs(lines):
    """rev-list args for the commits a push would send that no remote-tracking ref has."""
    tips = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        local_sha = parts[1]
        if ZERO_SHA.match(local_sha):  # a delete sends nothing
            continue
        tips.append(local_sha)
    return tips + ["--not", "--remotes"] if tips else []


def main(argv=None, stdin=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", action="store_true", help="also scan every commit and ref")
    parser.add_argument("--pre-push", action="store_true", help="scan commits being pushed (stdin)")
    parser.add_argument("--repo", default=".", help="repo to scan (default: current directory)")
    args = parser.parse_args(argv)

    path = list_path()
    terms, error = load_terms(path)
    if error:
        print(f"deny-scan: FAIL (closed): {error}", file=sys.stderr)
        return EXIT_NO_LIST

    try:
        findings = scan_index(terms, args.repo)
        if args.history:
            findings += scan_commits(terms, args.repo, ["--all"]) + scan_refs(terms, args.repo)
        if args.pre_push:
            revs = pre_push_revs((stdin or sys.stdin).read().splitlines())
            if revs:
                findings += scan_commits(terms, args.repo, revs)
    except GitError as exc:
        print(f"deny-scan: FAIL (closed): {exc}", file=sys.stderr)
        return EXIT_GIT

    for line in findings:
        print(f"deny-scan: {line}")
    if findings:
        print(f"deny-scan: FAIL: {len(findings)} finding(s) against {len(terms)} terms", file=sys.stderr)
        return EXIT_FINDINGS
    scope = "index, history, and refs" if args.history else "index"
    if args.pre_push:
        scope += ", and the commits being pushed"
    print(f"deny-scan: ok ({len(terms)} terms, {scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
