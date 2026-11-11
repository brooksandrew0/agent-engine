# Measure by plan share, not dollars

All my agents share one flat-rate Claude subscription. What runs out is not money but the
subscription's usage windows: a 5-hour window and a weekly one. So that is what I measure, every
model run is logged to one ledger, and one rule decides when background work waits.

## The problem

Early on, the brain keeper ran on a daily budget in API-equivalent dollars ($15 a day, set on
2026-10-31). Nothing is billed per call on a subscription, so the number described a cost I never
pay, and it said nothing about the thing that actually stops work: hitting a usage window. I said
so at the time: dollars were a useless metric for me, and fixed caps felt like guessing. What I
care about is the share of my plan.

## What I did

**Read the windows.** On 2026-10-31 I found that a headless Claude Code run with streaming JSON
output reports, once per run, how full the 5-hour and weekly windows are, as fractions. That field
isn't in the documentation, so the code reads it defensively.

**One ledger of every model run** (live since 2026-11-01). Each run on the server adds one JSON
line: role, lane, model, turns, tokens, the plan reading, counts of what it produced (never text),
and for dispatched jobs an outcome code. API-equivalent dollars stay in the line for comparison
only. The ledger is append-only and root-owned. A run never writes it directly: it drops its line
into its own user's spool folder, and a root collector moves lines every 2 minutes and stamps the
writer from the folder's owner, so one role can't log as another. Plan readings are trusted only from two named roles.

**One pause rule, one owner** (since 2026-11-05). Even pace is the share of the week already gone.
Background work waits when weekly use runs more than 5 points ahead of even pace, or the 5-hour
window passes 70%. My own requests, urgent items, reports, and probes never wait. The rule lives in
one function, with its two numbers in one config file. The brain keeper pauses its bulk lanes on
it, and the job dispatcher holds every start on it. The ledger's own governor only logs what it
would have decided.

**Build runs report too.** Big build sessions on my laptop are outside the server ledger, so each
one states an estimate as a share of the weekly plan and ends with a usage report from its own
transcripts ([thin coordinator](thin-coordinator.md)).

Dollar limits still exist, as runaway guards only.

## The tradeoff

- **Readings are account-wide.** One reading covers everything on my account, including my own
  sessions and other jobs running in parallel. A role's own share can't be read directly; it is
  estimated from its runs, time, and tokens. A before-and-after delta during a run means little
  when other work runs at the same time.
- **An undocumented field.** If it changes, the rule goes blind. The callers choose what blind
  means: the brain keeper fails open (nothing pauses), the dispatcher fails closed (nothing
  starts).
- **The governor still doesn't govern.** Whether the ledger's governor may pause runs itself was
  set for a usage review on 2026-11-07. My records still list it as open.
- **The server and the laptop aren't measured together yet.** That is deferred to a system-wide
  optimization once the engine is functionally settled.

## What broke

- **Three copies of the rule.** Until 2026-11-05 the brain keeper, the dispatcher, and the ledger
  each had their own copy. The brain keeper's code defaulted to a 50% 5-hour line (its live config
  set 70%). The dispatcher hard-coded its numbers and held at exactly 70% where the others didn't.
  A system review found it, and the fix was one function that all three call.
- **The most expensive runs logged nothing.** The 2026-11-03 system review found that dispatched
  jobs recorded no usage at all. They have since 2026-11-04.
- **The rule didn't cover the worst week.** On 2026-11-06 one build run from my laptop reached 83%
  of the weekly plan with three days left. The server rule never saw it, because laptop sessions
  aren't in the ledger. That is why build runs now carry their own estimate, stop line, and report.

## Use it yourself

1. Find out what actually limits you (windows, quotas, rate limits) and measure in those units.
2. Log every model run as one structured line, written through a path that proves who wrote it.
3. Keep content out of the log: counts and codes, never text.
4. Write the pause rule once, in one place, and make every caller ask it.
5. Decide for each caller what happens when the reading is missing, and write it down.
