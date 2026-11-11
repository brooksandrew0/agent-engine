# One file per log entry

When many agents open PRs at once, any file that every PR edits becomes a conflict factory. I
replaced edits to the two shared log files with one new file per entry, folded into the main files
later by a script.

## The problem

The repo keeps two logs: a decision log (newest entry first, at the top) and a changelog (oldest
first, entries added at the end). The repo's rules say every meaningful change records both, so
every PR edited the top of one file and the end of the other.

On 2026-11-02, seven of eight open PRs conflicted with `main`, and the only conflicts were in those
two files. Each merge broke the rest. Resolving them meant another round of merges from `main` into
each branch, another push, and another wait for checks, for changes that never overlapped in
substance.

## What I did

- **One file per entry.** A new decision is a new file, `decisions.d/YYYY-MM-DD-<slug>.md`; a
  changelog entry is `changelog.d/YYYY-MM-DD-<slug>.md`. The file holds the entry as it would
  appear in the main file: a `### Title` line, a blank line, then the bullets. No date heading: the
  date comes from the file name. Two PRs never write the same new file, so they never conflict.
- **A fold script.** `fold-logs.py --check` validates fragment names and shapes. `--fold` moves
  each fragment into its main file under the right date heading (decisions newest first, changelog
  at the end) and deletes it. It leaves every existing byte outside the inserted entries unchanged,
  and a second run does nothing.
- **The check runs before every push and on every PR.** The local check runner and the PR verifier
  both run `--check`, so a malformed fragment turns the PR red.

The same day I set the merge method around it: branches are updated by merging `main` in, never
rebased or force-pushed, and before an agent gives me a merge order it simulates the whole
sequence of merges and runs the tests on the combined tree. That evening, right after the change
merged, I merged the next run of PRs one after another with no conflicts.

## The tradeoff

- **The record lives in two places until folded.** Readers have to read the main file and its
  fragment directory together. The rule says so, and agents search both, but a reader who opens
  only the main file sees an old record.
- **Someone has to fold.** The fold is a separate PR, and it must not collide with open PRs
  itself. The planned design skips any fragment an open PR changes or links to, records what it
  skipped, and has the verifier rerun the fold on the base commit and require a byte-for-byte match,
  so a fold PR can't slip in a changed entry.
- **It solves one kind of conflict.** Two PRs that change the same doc or the same status row still
  conflict. This pattern only removes the conflicts that came from shared append points.

## What broke

The fold has never run. Both main files were last changed on 2026-11-02, the day fragments started.
On 2026-11-10 I counted 140 decision fragments and 213 changelog fragments waiting in their
directories.

The fold had an owner on paper twice. It was first assigned to a nightly docs job that was never
installed. It then moved to a weekly fold PR owned by the drift loop's fifth build step, which
isn't built yet. Until then, the rule is that a worker session folds on request in its own PR, and
nobody has asked. The cost so far is small, because agents search both places, but it is exactly
the kind of loose end the [coherence check](coherence-check.md) exists to catch, and it doesn't
catch this one.

A smaller miss: the check was meant to run as its own GitHub Actions step. That needed a workflow
change I chose not to make, so the check lives in the local runner and the PR verifier instead.

## Use it yourself

1. Find every file that most PRs touch at the same spot (logs, changelogs, indexes, registries).
2. Replace each append point with a directory of one-file-per-entry fragments named by date and
   slug, holding the entry exactly as it will appear.
3. Write a fold script that is idempotent and touches nothing outside the inserted entries, plus a
   check mode, and run the check before every push and on every PR.
4. Give the fold a real owner and a schedule from day one, and make the fold skip fragments that
   open PRs touch.
5. Until folds run, tell readers in writing to read the main file and the fragments together.
