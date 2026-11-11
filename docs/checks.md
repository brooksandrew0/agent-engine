# Checks

Three layers keep secrets and private material out of this repo.

| Layer | Where it runs | What it catches |
|---|---|---|
| GitHub Actions (`.github/workflows/checks.yml`) | Every pull request and every push to `main` | Secrets (gitleaks over the full history) and the unit tests. Read-only token, no secrets, and pull requests from forks get no write access. |
| `tools/deny_scan.py` | The author's machine, before every push (opt-in hook; `git push --no-verify` skips it) | Private terms (names, places, hosts, addresses) from a list kept outside the repo, in staged files and in the commits being pushed. |
| Human read-through | Before anything is published | Everything else. |

The engine itself uses a PR verifier on a home server instead of hosted runners (see
[the design](design.md) and [humans merge](patterns/humans-merge.md)). This public repo doesn't:
its PRs can come from anyone, so they run on GitHub's runners and never on a machine of mine.

## Running the checks

```sh
git config core.hooksPath .githooks   # once per clone: runs the checks before every push
python3 -I tools/ci_local.py           # tests, deny scan, gitleaks if installed
python3 -I tools/ci_local.py --history # also every commit, ref, and tag
```

The hook first runs `deny_scan.py --pre-push`, which scans each commit being pushed that no
remote-tracking ref already has: author, committer, message, and full patch. Then it runs
`ci_local.py`, which scans git's index (staged content, not files on disk; a symlink's target path).

`ci_local.py` exits 0 when everything passed, 1 when something failed, and 2 when nothing failed
but a check was skipped because its tool isn't installed. Exit 2 is not a pass.

## The deny list

`~/.config/agent-engine/deny.txt`, or the path in `AGENT_ENGINE_DENY`. One entry per line:
a plain entry matches as whole words, ignoring case and accent encoding, with any whitespace
(a line break too) between its words; plurals don't match, so list them. `re:` starts a regex; `#`
starts a comment. The scan fails closed when the list is missing, empty, or has a bad regex (exit
3), or when a git command fails (exit 4).

Not caught: text that is encoded (base64, URL-encoded), compressed, or inside images and PDFs.
The read-through covers those.

Findings name the file, the line, and the entry's line number in the list, never the term (a
matched part of a file name shows as `[list line N]`), so the output is safe to paste.

Why the list isn't in the repo, even hashed: anyone could hash a guess (a name, a town) and
confirm it against the list.

## How this repo was published

The working repo stays private. This one was made from it as a single fresh commit, from an
allowlist of files, so no working history, pull request, or internal plan came along. Before
publishing, the export passed both private-term lists, an attacker's-eye security review, and the
`STARTER.md` eval in [`evals/starter/`](../evals/starter/).
