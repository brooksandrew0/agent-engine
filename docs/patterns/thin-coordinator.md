# Thin coordinator, bounded builders

A multi-step build costs roughly turns times context size. So I keep the thread that runs a build
small, put a ceiling on each builder, and make every run state an estimate before it starts and
report what it used when it ends.

## The problem

I build most of the engine in staged runs from my laptop: one coordinator session hands each step
to a builder subagent, and reviewer subagents check the work ([design](../design.md)). It was
eating my plan. On 2026-11-06 one engine run reached 83% of my weekly
plan with three days left in the week. On 2026-11-07 two build sessions took about 80% of that
day's laptop usage.

I read that day's transcripts to see where it went. Shares are by weighted tokens, used only to
rank:

| Where | Share (2026-11-07) | Why |
|---|---|---|
| Builder subagents | about 45% | 130 to 210 turns each, at 200k to 320k tokens of context per turn |
| Coordinators | about 22% | one coordinator thread averaged 470k context (peak 755k) over 290 turns |
| Reviews | about 20% | about 30 passes at 80k to 160k context each |
| Other sessions | about 13% | |

Cache reads were 67% of the weighted tokens. Every turn re-reads the whole context, so writing
code is cheap and long threads that keep going are expensive.

## What I did

I accepted a set of rules on 2026-11-07 and kept the staged structure.

- **The coordinator sees summaries only.** Each subagent returns at most 300 words; the full report
  goes to a file or the PR body. The coordinator never reads diffs, full reports, or long docs.
- **A fresh coordinator per stage.** At each step boundary, or once its context passes 150k, the
  coordinator writes a hand-off (steps done, PRs, open findings, next step) into the PR body or the
  status page, and the run continues in a new session. A 470k thread costs about three to five
  times as much per turn as a 100k to 150k one.
- **Bounded builders.** The brief names what to read: the design section, the files to change, and
  the docs that constrain them, never "read the repo's docs". The two big log files are searched
  for the topic, not read whole, which cuts about 50k tokens from every agent's start. One step is
  one PR of at most about 1,500 changed lines and a budget of about 100 turns. At the limit the
  builder stops, commits what it has, says what is and isn't tested, and never calls a partial
  step done. Records and docs steps use a cheaper model.
- **Measure every run.** A run states its estimate as a share of the weekly plan, stops and asks me
  at twice that or at 15% of the weekly plan, and ends with a report from `session-usage`: a
  read-only script that reads the run's own transcripts and splits usage by coordinator,
  builders, and reviewers, with turns, average and peak context, and the model mix.

The stop line has already changed a plan: one build was estimated at about 23% of a weekly plan
*(estimate)*, so it was split into three runs of at most about 15% each.

## The tradeoff

- Summaries drop detail. A coordinator that never reads the diff can't catch a builder's wrong
  summary. The reviews have to, which is one reason reviews stay ([risk-tiered
  reviews](risk-tiered-reviews.md)).
- A turn budget leaves partial steps behind, and more sessions to manage.
- The report's token weights only rank where usage went. Plan share is the official measure, and
  the plan reading is account-wide, so a reading taken during a run includes anything else I was
  running at the time ([measure by plan share](measure-by-plan-share.md)).
- The expected saving is about 35 to 45% for the same work. That is an estimate. Checking it
  against real run reports is still an open item in my records.

## What broke

The 83% week is the failure that produced these rules. Before them, coordinator threads grew to
hundreds of thousands of tokens, builders ran for hundreds of turns, and review rounds repeated on
small fixes. A run had no stop line, so nothing paused it partway through the week.

## Use it yourself

1. Measure one heavy day before changing anything: turns, context per turn, and share by role,
   from your own transcripts.
2. Cap what subagents return to the coordinator, and send full reports to files.
3. Pick a context size at which the coordinator writes a hand-off and restarts in a fresh session.
4. Give every builder a named read list, a step size, and a turn budget, and make it stop and
   report at the limit.
5. Write an estimate before each run, set a stop-and-ask line, and compare the end-of-run report
   with the estimate.
