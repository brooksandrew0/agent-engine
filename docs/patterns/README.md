# Patterns

Eight patterns from building the engine. Each covers the problem, what I did, the tradeoff, what
broke, and how to use it yourself.

- [Thin coordinator, bounded builders](thin-coordinator.md): keep the build thread small, cap each builder, and estimate and report every run's usage.
- [Risk-tiered reviews](risk-tiered-reviews.md): review depth follows risk, a review is settled at no high or medium findings, and two rounds is the cap.
- [One file per log entry](one-file-per-log-entry.md): new log entries as one file each, folded in later, so parallel PRs stop conflicting.
- [A coherence check for docs](coherence-check.md): a code-only check that fails a PR when docs contradict each other.
- [A three-layer brain with one keeper](three-layer-brain.md): core facts, cards, and sources in git, one writer, code does the git, and private items kept out.
- [One daily brief](one-daily-brief.md): one issue a day for everything that needs me, answered with short verbs, with a stop on runaway questions.
- [Measure by plan share, not dollars](measure-by-plan-share.md): measure the subscription's usage windows, log every run, and pause background work by one rule.
- [Agents open PRs; only I merge](humans-merge.md): the merge is the deploy, the lanes check who merged, agent sessions can't merge, and PRs are verified off GitHub's runners.
