# A coherence check for docs

Agents treat the repo's docs as the truth, so a stale doc misleads the next session. I run a
code-only check that finds docs contradicting each other, and it fails the PR the same way a broken
test does.

## The problem

In this repo the docs are the configuration record: a plan has a status header, a service doc has
install records, and a status page has one row per system with what it waits on. With many agents
writing PRs, those copies drift. A plan header still says "proposed" after its own install record.
A status row still waits on my answers after the plan records them. A heading says "not installed"
above the install record for that very thing.

On 2026-11-02 a one-time review of the repo listed 109 loose-end findings: hanging threads,
unclosed loops, stale statuses, and leftovers of earlier approaches. I asked for a fix to the
system, not one cleanup.

## What I did

A checker in plain code: no model, standard library only, read-only. Each finding has a check ID.
The rules are about my repo's own conventions:

- **Stale header:** a doc's status says not installed or proposed, but the doc has an install
  record, or a status row that links to it says it is live.
- **Stale section:** a section heading says "not installed" with an install record inside it.
- **No status, or an open status gone stale:** a plan with no status, or still "proposed" past a
  set number of days.
- **Broken front matter:** an unknown status value, a supersedes link to a missing file or one
  that only points one way, a past review date, a missing owner.
- **Answered but still waiting:** a status row still waits on me to answer or decide, while a doc
  it links records the answers with a date.
- **Bad log fragments:** the [one-file-per-entry](one-file-per-log-entry.md) rules.

It runs in two places:

- **Every PR.** The local check runner and the PR verifier run it on the whole tree and fail on any
  error.
- **Every morning.** A root step runs it on `main` and the [daily brief](one-daily-brief.md) shows
  a short Loose ends section, written by code only. The model that writes the brief's top never
  sees it.

Two rules run only in the morning step, because they need GitHub lookups: a status row still
waiting on a PR that has merged, and a plan that says "not built" while a doc it names as its
implementation is live. Findings carry a fingerprint, so they become tracked items that close
when the doc is fixed.

## The tradeoff

- **It only knows my conventions.** It reads status lines, install record headings, and "Answered"
  lines by pattern. A contradiction in plain prose passes. Every new convention needs a rule.
- **It checks the whole tree.** A PR can go red on stale text it didn't touch, and the fix lands in
  that PR. That is the point.
- **It catches drift, not wrong facts.** If two docs agree on something false, it has nothing to
  say. The live system is still the authority; the repo's rule is to inspect it first when the
  docs and reality differ.

## What broke

The check itself went stale. On 2026-11-05 I asked why stale entries kept appearing ("It seems
constant"). The answer: only the first step of the plan had been built. Nothing ran the checker,
though the repo's agent instructions and the CI doc both said a nightly run existed. The docs
describing the coherence check were themselves incoherent. On `main` it found four stale headers
that day, and it had no rule for the stale "waiting on" cells I had just run into.

The fix that day: errors fail the local runner and so the PR verifier, the morning step runs it,
and a new rule catches answered rows that still wait.

The first version, on 2026-11-02, reported five errors and two warnings on `main`. One was a
heading that still said "not installed" above its own install record, a hundred lines further down
the same doc.

## Use it yourself

1. Decide where each kind of fact lives (status in one header, install state in one record) and
   write that down.
2. List the contradictions you have actually seen, and turn each into a narrow rule with an ID.
3. Run it in code, with no model, so it's cheap enough to run on every PR.
4. Fail PRs on errors, and show the rest somewhere you read daily.
5. Check that whatever you say runs it really runs it. Mine didn't, from 2026-11-02 to 2026-11-05.
