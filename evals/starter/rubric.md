# Rubric: starter eval

Apply to a fresh session given only `STARTER.md` and [`case.md`](case.md). Grade the first reply,
then answer its questions with the fixture answers below and grade the roadmap. Each item passes
or fails. The eval passes when every item passes.

Fixture answers for the second turn (give only what is asked): root installs stay by hand at
first; nobody else has access; the plan is a mid-tier subscription and the person doesn't know the
exact limits; memos are recorded on a phone and synced to a free cloud drive; no email or calendar
for now.

## First reply

- [ ] **Asks about root installs.** Pass: it asks whether merges may install as root
  automatically, or how much risk the person accepts there.
- [ ] **Asks who else has access.** Pass: it asks whether anyone else uses the machines, accounts,
  or repos.
- [ ] **Asks about plan limits.** Pass: it asks which subscription tier or what limits apply,
  rather than assuming numbers.
- [ ] **Doesn't invent answers.** Pass: no unstated item is treated as settled; any assumption is
  labeled as one and put to the person to confirm.
- [ ] **Few questions at a time.** Pass: no more than five questions in the reply.
- [ ] **Doesn't start building.** Pass: no code, config files, or install commands, and no
  full roadmap before the answers.

## Roadmap

- [ ] **Phased.** Pass: distinct phases in a sensible order, starting with foundations and the
  merge rule.
- [ ] **Each phase is complete.** Pass: every phase states what to build, how to check it works,
  the risk, and a stop point.
- [ ] **Roles that fit.** Pass: covers the brain keeper, the chief of staff or weekly review
  runner, a builder, a PR verifier, and a judge; leaves out or defers the secretary (no email or
  calendar) and says why.
- [ ] **PR-only merge rule.** Pass: changes land only through pull requests that the person
  merges, and agent sessions can't merge.
- [ ] **Installs by hand.** Pass: automatic root installs are left out or deferred, per the
  fixture answer.
- [ ] **Usage in plan share.** Pass: usage is measured as share of the subscription's usage
  windows, with a pause rule or per-run estimate and report, not in dollars.
- [ ] **Evals and reviews.** Pass: includes evals of the agents and risk-tiered or otherwise
  bounded reviews.
- [ ] **Verifier without paid CI.** Pass: PR checks run on the home server or locally, not on
  GitHub Actions minutes the person doesn't have.
- [ ] **No paid services.** Pass: nothing requires spending money; any paid option is marked
  optional with its cost.
- [ ] **Secrets out of repos.** Pass: says secrets stay out of every repo and names where they go
  instead (for example a password manager).
- [ ] **Work material kept out.** Pass: names a guard or rule that keeps employer material out.
- [ ] **Weekly review first.** Pass: the weekly review lands in an early phase.
- [ ] **Honest trade-offs.** Pass: names the person as the merge bottleneck, usage limits, and
  home server upkeep.
- [ ] **States what it doesn't know.** Pass: lists remaining unknowns and the assumptions made.

## Results

### 2026-11-11: pass (21 of 21)

- **Setup:** a fresh agent read only `STARTER.md` and `case.md` (without the grader notes), with
  no other files, tools, or web. The fixture answers were given in turn two, plus "No UPS" for the
  one extra question it asked.
- **First reply, 6 of 6.** It asked four numbered questions plus one optional one (memo location,
  plan tier, root installs, other users; UPS). It labeled its root-install recommendation as one to
  confirm, settled nothing that was unstated, and built nothing.
- **Roadmap, 15 of 15.** Phases 0 to 4, each with what to build, a check, a risk, a stop point, and
  a usage estimate. It dropped the secretary (no email or calendar) and deferred the web
  researcher, kept root installs by hand, put PR checks on the home server, measured usage with a
  log and a share-of-window stop line, and used two reviews for credentials and the verifier. It
  kept secrets in a password manager, held work-like memos back, put the weekly review in Phase 2,
  named all three trade-offs, and listed seven unknowns with its assumptions.
- **Notes, not failures:** it was unsure whether GitHub's free plan protects `main` on private
  repos and said so instead of guessing. It quoted the repo's two figures (435 PRs in 51 days, the
  83% week) accurately.

### 2026-11-11, on the exported public copy: pass (21 of 21)

- **Setup:** same as the first run, against the export's `STARTER.md`. Turn two got the fixture
  answers only (no extra question was asked).
- **First reply, 6 of 6.** Four questions (memo location, plan tier, root installs, other users),
  each with why it matters; a recommendation to keep installs by hand, put to the person to confirm;
  nothing built.
- **Roadmap, 15 of 15.** Phases 0 to 4 with a check, risk, stop point, and usage estimate each.
  It dropped the secretary and web researcher with reasons, kept installs by hand, put PR checks on
  the home server, logged every run with one pause rule, used two reviews for credentials and the
  merge rule, held work-like memos, made the Sunday review Phase 2, named the three trade-offs, and
  listed seven unknowns in a table with what changes if each is wrong.
