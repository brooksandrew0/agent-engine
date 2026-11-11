# Agents open PRs; only I merge

Agents never ship anything. Every change arrives as a pull request, my own verifier tests it, and I
merge. The merge is the deploy, and code on the server checks that the merge really was mine.

## The problem

Agents here write code and config that install as root on my home server. If an agent could get a
change live by itself, a mistake or a prompt-injected instruction becomes a root change. I needed
one path to production that only I can open, and a test of every PR that doesn't depend on the
agent that wrote it.

The test half had a money problem too. Checks ran on GitHub Actions, and private repos on the free
plan get 2,000 Actions minutes a month. Every budget I have there is $0, so going over doesn't
bill; it blocks Actions until the next month.

## What I did

- **Agents open PRs; I merge every one.** No agent's change goes live except through my merge.
  Rebase merges are not used. (The brain keeper's filings to the brain repo are the one exception;
  see [three-layer brain](three-layer-brain.md).)
- **The merge is the deploy.** Two lanes on the server watch `main`. The deploy lane polls every 2
  minutes and redeploys container stacks, with a policy check, a snapshot, a health check, and
  rollback. The install lane (since 2026-11-05) checks every minute and installs each changed
  component as root, with tests, a backup, a check, and rollback. First installs stay by hand.
- **The lanes check it was me.** Every new commit on `main` must be the merge commit of a pull
  request, merged by my account, and since 2026-11-05 made by GitHub rather than a local merge
  pushed up. Otherwise the lane refuses the whole range, skips nothing, alerts, and stalls until I
  fix it.
- **A merge block for agent sessions.** My laptop sessions use my own GitHub login, so a session
  could merge and pass that check. Since 2026-11-05 a managed settings file denies Claude sessions
  every merge command, the API merge routes, auto-merge, and pushes to `main`.
- **A verifier off GitHub's runners.** The PR verifier on the home server (since 2026-11-04)
  tests every PR's latest commit, merged with current `main`, about a minute after each push, in
  rootless containers with no network, a read-only filesystem, and no capabilities. Its
  check list comes from `main`, so a PR can't grade itself. A PR that a builder agent wrote runs only
  after I approve that exact commit. Since 2026-11-05 the merge rule is a green check from it.

## The tradeoff

- **I'm the bottleneck.** 435 merged PRs in 51 days (as of 2026-11-10), and the rule is that I
  merge every one.
- **A merge I don't read is still a root change.** Nothing stops me merging something I didn't
  understand, and there is no second reviewer.
- **The lanes are the hard line.** Other guards help, but the deploy and install lanes are what
  refuse anything that isn't a merged pull request, so they are where the testing goes.

## What broke

- **Actions minutes ran out.** From 2026-11-01 to 2026-11-03, two workflows with five jobs, run on
  every push and every PR update, used 1,917 of the 2,000 monthly minutes. The jobs' real run time
  was about 200 minutes; every job bills at least a full minute. I cut it to one job on
  2026-11-03, and the minutes still ran out that day, blocked until 2026-12-01. The verifier on the
  server went live the next day and became the merge rule on 2026-11-05.
- **A timeout read as "no".** On 2026-11-09 the merge check treated a GitHub API timeout as a
  refusal, rejected a genuine merge, and opened a false incident. Now calls retry, and "couldn't ask"
  is kept apart from "refused": it accepts nothing and only delays.

## Use it yourself

1. Make merge the only path to production, and have the deploy side verify who merged.
2. Refuse the whole range on any commit that fails that check, and never skip past it.
3. Take merge rights away from agent sessions explicitly, even ones that run as you.
4. If hosted minutes are scarce, run PR checks on your own hardware, with the list read from `main`.
5. Make your merge rule one signal you can see on the PR, and check it yourself before merging.
