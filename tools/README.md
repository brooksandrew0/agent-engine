# Tools

Standalone Python scripts (standard library only, Python 3.9 or later). Each one's docstring has
its usage and exit codes; run any of them with `python3 -I tools/<name>.py --help`. Tests are in
`tests/`: `python3 -I -m unittest discover -s tests -t .`

| Tool | What it does | Pattern |
|---|---|---|
| [`fold_logs.py`](fold_logs.py) | Checks and folds one-file-per-entry log fragments (`decisions.d/`, `changelog.d/`) into their main files, atomically, refusing everything if any fragment is bad | [One file per log entry](../docs/patterns/one-file-per-log-entry.md) |
| [`coherence_check.py`](coherence_check.py) | Flags docs that contradict each other, from rules in a JSON config ([example](coherence.example.json)) | [Coherence check](../docs/patterns/coherence-check.md) |
| [`session_usage.py`](session_usage.py) | Reports what a Claude Code coordinator session and its builders and reviewers used, by role, from local transcripts | [Thin coordinator](../docs/patterns/thin-coordinator.md) |
| [`ci_local.py`](ci_local.py) | Runs a repo's checks locally from a JSON list, with exit 2 for "a tool was missing" (not a pass) | [Checks](../docs/checks.md) |
| [`deny_scan.py`](deny_scan.py) | Scans staged files, pushed commits, or full history for private terms from a list kept outside the repo, without printing the terms | [Checks](../docs/checks.md) |
