#!/usr/bin/env python3
"""Report where a build run's usage went, from Claude Code session transcripts. Read-only.

    python3 -I tools/session_usage.py COORDINATOR_ID [AGENT_ID ...] [--since T] [--until T]
                                      [--projects DIR]

Reads DIR/*/<COORDINATOR_ID>.jsonl (the coordinator's main thread) and
DIR/*/<COORDINATOR_ID>/subagents/*.jsonl (its subagents, with each one's .meta.json description).
DIR defaults to ~/.claude/projects, where Claude Code keeps its transcripts.

With no AGENT_ID, every subagent of the coordinator is counted. With AGENT_IDs, only those are:
each one matches a subagent file (agent-<id>.jsonl or <id>.jsonl) or a separate top-level
session (DIR/*/<id>.jsonl, counted as a builder, with its own subagents). An id that matches
nothing is listed as not found.

--since/--until take an ISO date or time (2026-11-07 or 2026-11-07T14:00, UTC) and keep only
assistant messages inside that window.

Assistant messages are de-duplicated by message.id across every file read for one report (a
streamed message is logged more than once; within a file the last copy wins). When a session's
subagent files are read, lines marked isSidechain in its main transcript are skipped, so subagent
work is not counted twice. A usage value that isn't a whole number counts as 0 and is reported on
a "skipped values" line. A subagent whose description has the word judge, security or review
(or reviews, reviewer, reviewing; not preview) is a reviewer; anything else is a builder. Shares use weighted tokens (input 1, output 5, cache read
0.1, cache write 1.25), which only rank where usage went: if your plan has usage windows, the
plan's own reading is the real measure, and it is account-wide, so it includes other work.

Exit codes: 0 report printed (even if a transcript was not found); 2 bad arguments.
Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WEIGHTS = {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")
ROLES = ("coordinator", "builder", "reviewer")
REVIEWER_RE = re.compile(r"\b(?:judges?|security|review(?:s|ed|er|ers|ing)?)\b", re.I)
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_PROJECTS = Path.home() / ".claude" / "projects"
NOTE = ("Weighted = input 1, output 5, cache read 0.1, cache write 1.25: for ranking only. "
        "A plan's own usage reading is the real measure, and it includes other work on the account.")


def parse_time(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_int(value):
    """A usage count as an int, or None when it isn't a whole number (counted as skipped)."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


USAGE_FIELDS = {"input": "input_tokens", "output": "output_tokens",
                "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}


def read_turns(path: Path, since: datetime | None = None, until: datetime | None = None,
               seen: set | None = None, skip_sidechain: bool = False) -> list:
    """One dict per distinct assistant message id, in first-seen order.

    `seen` holds the message ids already counted from other files of the same report: they are
    skipped here, and this file's ids are added. `skip_sidechain` drops lines marked isSidechain
    (subagent lines copied into a main transcript whose subagent files are read too).
    """
    turns: dict = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for n, line in enumerate(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") if isinstance(d, dict) else None
        if not isinstance(msg, dict) or d.get("type") != "assistant" or not isinstance(msg.get("usage"), dict):
            continue
        if skip_sidechain and d.get("isSidechain") is True:
            continue
        if since or until:
            try:
                ts = parse_time(d["timestamp"])
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if (since and ts < since) or (until and ts >= until):
                continue
        if msg.get("model") == "<synthetic>":  # placeholder entries, no real usage
            continue
        mid = msg.get("id")
        key = mid if isinstance(mid, str) and mid else f"{path}:{n}"
        if seen is not None and key in seen:
            continue
        u = msg["usage"]
        turn = {"model": msg.get("model") if isinstance(msg.get("model"), str) else "unknown", "skipped": 0}
        for k, field in USAGE_FIELDS.items():
            value = to_int(u.get(field))
            if value is None:
                turn["skipped"] += 1
                value = 0
            turn[k] = value
        turns[key] = turn  # re-assigning keeps the first position; the last copy's values win
    if seen is not None:
        seen.update(turns)
    return list(turns.values())


def weighted(t: dict) -> float:
    return sum(t[k] * w for k, w in WEIGHTS.items())


def summarize(name: str, role: str, turns: list) -> dict:
    ctx = [t["input"] + t["cache_read"] + t["cache_write"] for t in turns]
    out = {"name": name, "role": role, "turns": len(turns),
           "avg_ctx": sum(ctx) / len(ctx) if ctx else 0, "peak_ctx": max(ctx, default=0),
           "models": Counter(t["model"] for t in turns), "weighted": sum(weighted(t) for t in turns),
           "skipped": sum(t.get("skipped", 0) for t in turns)}
    out.update({k: sum(t[k] for t in turns) for k in TOKEN_KEYS})
    return out


def classify(description: str) -> str:
    return "reviewer" if REVIEWER_RE.search(description or "") else "builder"


def check_id(sid: str) -> str:
    if not ID_RE.match(sid):
        raise argparse.ArgumentTypeError(f"bad session id {sid!r}")
    return sid


def subagent_files(main: Path, sid: str) -> list:
    return sorted((main.parent / sid / "subagents").glob("*.jsonl"))


def summarize_subagent(sub: Path, since, until, seen=None) -> dict:
    desc = ""
    try:
        desc = json.loads(sub.with_suffix(".meta.json").read_text(encoding="utf-8")).get("description", "")
    except (OSError, ValueError, AttributeError):
        pass
    if not isinstance(desc, str):
        desc = ""
    return summarize(desc or sub.stem, classify(desc), read_turns(sub, since, until, seen))


def read_session(main: Path, sid: str, name: str, role: str, since, until, seen, wanted=None) -> list:
    """The session's subagents first (those in `wanted`, if given), then its main thread, which
    skips sidechain lines and ids already counted when any subagent file was read."""
    subs = []
    for sub in subagent_files(main, sid):
        if wanted:
            hit = next((a for a in wanted if sub.stem in (a, f"agent-{a}")), None)
            if hit is None:
                continue
            wanted[hit] = True
        subs.append(summarize_subagent(sub, since, until, seen))
    head = summarize(name, role, read_turns(main, since, until, seen, skip_sidechain=bool(subs)))
    return [head] + subs


def find_run(projects: Path, coordinator: str, agent_ids=(), since=None, until=None):
    """Return (agents, missing): per-agent summaries, and the ids that matched no transcript.
    A message id is counted once per report, whichever file it is first read from."""
    check_id(coordinator)
    for a in agent_ids:
        check_id(a)
    wanted = {a: False for a in agent_ids}
    seen: set = set()
    agents = []
    mains = sorted(projects.glob(f"*/{coordinator}.jsonl"))
    missing = [] if mains else [coordinator]
    for main in mains:
        agents += read_session(main, coordinator, "main thread", "coordinator", since, until, seen, wanted)
    for a in agent_ids:
        if a == coordinator:
            wanted[a] = True
            continue
        for main in sorted(projects.glob(f"*/{a}.jsonl")):
            wanted[a] = True
            agents += read_session(main, a, f"session {a}", "builder", since, until, seen)
    missing += [a for a, found in wanted.items() if not found]
    return agents, missing


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def report(coordinator: str, agents: list, missing=()) -> str:
    out = [f"== run {coordinator} =="]
    if missing:
        out.append("  not found: " + ", ".join(missing))
    if not agents:
        return "\n".join(out + ["  no transcript found"])
    total = sum(a["weighted"] for a in agents) or 1.0
    out.append("per role (share of weighted usage):")
    for role in ROLES:
        group = [a for a in agents if a["role"] == role]
        w = sum(a["weighted"] for a in group)
        tokens = ", ".join(f"{k.replace('_', ' ')} {fmt(sum(a[k] for a in group))}" for k in TOKEN_KEYS)
        out.append(f"  {role:<12} {100 * w / total:5.1f}%  ({plural(len(group), 'agent')}, "
                   f"{plural(sum(a['turns'] for a in group), 'turn')}; {tokens})")
    out.append("per agent:")
    for a in sorted(agents, key=lambda a: -a["weighted"]):
        models = ", ".join(f"{m} x{c}" for m, c in a["models"].most_common()) or "-"
        out.append(f"  [{a['role']}] {a['name'][:70]}: {plural(a['turns'], 'turn')}, "
                   f"avg ctx {fmt(a['avg_ctx'])}, peak ctx {fmt(a['peak_ctx'])}, "
                   f"{100 * a['weighted'] / total:.1f}%, models {models}")
    out.append(f"totals: {plural(sum(a['turns'] for a in agents), 'turn')}, "
               + ", ".join(f"{k.replace('_', ' ')} {fmt(sum(a[k] for a in agents))}" for k in TOKEN_KEYS)
               + f", weighted {fmt(sum(a['weighted'] for a in agents))}")
    mix = Counter()
    for a in agents:
        mix.update(a["models"])
    skipped = sum(a["skipped"] for a in agents)
    if skipped:
        out.append(f"skipped values: {plural(skipped, 'usage value')} not a whole number, counted as 0")
    out.append("model mix (turns): " + (", ".join(f"{m} {c}" for m, c in mix.most_common()) or "-"))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("coordinator", metavar="COORDINATOR_ID", type=check_id)
    ap.add_argument("agents", nargs="*", metavar="AGENT_ID", type=check_id,
                    help="limit to these subagents or extra sessions (default: every subagent)")
    ap.add_argument("--since", type=parse_time)
    ap.add_argument("--until", type=parse_time)
    ap.add_argument("--projects", type=Path, default=DEFAULT_PROJECTS,
                    help="transcript root (default: ~/.claude/projects)")
    args = ap.parse_args(argv)
    agents, missing = find_run(args.projects, args.coordinator, args.agents, args.since, args.until)
    print(report(args.coordinator, agents, missing), end="\n\n")
    print(NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
