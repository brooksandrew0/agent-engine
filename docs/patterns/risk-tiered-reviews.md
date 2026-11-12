# Risk-tiered reviews

Review depth follows risk, not habit. A change that touches private data or installs as root gets
two independent reviews; a docs change gets one cheap pass. A review is settled when it has no high
or medium findings, and it gets at most two rounds before I decide.

## The problem

Since 2026-11-02 every design and diff in a build run went to a clean-context judge and a security
reviewer, got fixed, and went back for re-review until both called it settled. I still want that:
the reviews catch real problems before anything reaches me as done. But "until settled" had no
limit. The drift-loop design took four rounds of both reviews (2026-11-05). The brain read
telemetry plan took three (2026-11-03).

On 2026-11-07 reviews were about 20% of a day's laptop usage: about 30 passes at 80k to 160k tokens
of context each, with second and third rounds spent on small fixes ([thin
coordinator](thin-coordinator.md) has the full breakdown).

## What I did

The coordinator sets the tier at design time and writes it in the step's brief. When unsure, it's
Tier A.

| Tier | When | Reviews |
|---|---|---|
| A, high risk | By effect: private data, mail, deletes, credentials or secrets, auth, anything exposed to the network. By path: anything that installs or deploys on merge (merges install as root) | A judge and a security review, separately, on the strongest model |
| B, ordinary code | Everything else that runs | One judge pass that also covers security |
| C, records and docs | Docs, status, records, runbooks, wording | One pass on a cheaper model. Skipped only for mechanical changes (folds, renames) that the automated checks fully cover |

Rules for every tier:

- **Settled** means no high or medium findings. Low findings and nits go in the PR as a list and
  don't start another round.
- **The reviewer grades severity.** The coordinator copies each grade into the PR word for word.
  Nobody else downgrades a finding to skip a round.
- **At most two rounds.** If round two still finds a high or medium, the run stops and asks me.
- **Re-reviews are narrow.** They get the fix diff, the earlier findings, and the files the fix
  touches, and they check that each finding is fixed and nothing new broke. They run on the cheaper
  model, except a Tier A step with a high finding.
- **Review the increment.** Each review gets its own step's diff, not a stacked PR.
- **Small briefs.** A reviewer gets the diff, the design section, and the shared contracts, not
  the whole repo.
- **No extra final pass.** The settled round is the final pass unless the head changed after it.

## The tradeoff

- Most engine steps touch server config, so they stay Tier A. The savings come mainly from the
  round cap and narrow re-reviews. My estimate was reviews dropping from about 20% to about 12% of
  a day like 2026-11-07. It hasn't been checked against real runs yet.
- A two-round cap means I sometimes decide with a medium finding still open.
- A cheap Tier C pass can miss something, and mechanical changes get no model review at all. The
  automated checks carry that weight.
- A reviewer with a small brief only sees what it's given. If the shared contracts are wrong, it
  won't know.

## What broke

Before the cap, the round count was the failure: three and four rounds were normal on big designs,
and later rounds were often about small fixes.

The tiers caught a flaw in their own first draft. The build-cost plan that set them up got one
cheap Tier C pass on 2026-11-07. Round one found no high, three medium, and four low findings. One
medium: Tier A was keyed to keywords instead of the paths a change touches. Tier A is now defined
by path as well as by effect. All findings were fixed, and a narrow round two settled it.

An earlier design for reviews of every PR (2026-11-03) already capped rounds at three, then handed
me the disagreement in one line from each side. The build rules tightened that to two.

## Use it yourself

1. Write down your Tier A list by effect and by path. Include anything that deploys on merge.
2. Have whoever plans the step set the tier, not the builder, and default to the highest tier when
   unsure.
3. Define "settled" in severities, and let the reviewer, not the author, grade severity.
4. Cap rounds, and make the cap end in a human decision, not a third round.
5. Give re-reviews only the fix diff and the earlier findings.
