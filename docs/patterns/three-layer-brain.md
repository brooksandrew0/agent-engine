# A three-layer brain with one keeper

Every agent needs the same facts about me, and none should be able to quietly rewrite them. My
shared memory is a git repo in three layers with one keeper. Code, not the model, does the git,
core files change only through proposals I merge, and private items never enter it.

## The problem

I wanted one memory any session could use, from any AI tool, with real rigor: ingestion, conflict
resolution, cleanup. At first every agent read and wrote the brain repo directly, so any session
could edit the files that describe who I am, following whatever instructions it happened to have.

That failed in a way I could see. On 2026-11-02 a session started in a cloud environment had no
access to the keeper's tools and no copy of the current rules. Its only instructions were old ones
that said to write to the brain directly. It read a truncated copy of the brain's README, asked for
push access, and suggested a hand edit to a protected file. I replaced those stale instructions
the same day.

## What I did

- **Three layers, all text in git.** Core facts (who I am, my rules, the people I work with, the
  top of each project file), short summary cards and notes, and the raw sources they came from.
  Lookups go core first, then cards, then the cited lines of a source. Sources are never deleted,
  and since 2026-11-08 a filing run that changes an existing source is refused.
- **One keeper.** Mimir is the only routine writer since
  2026-10-31. Its GitHub App reaches the brain repo and nothing else. Other agents read
  through Mimir's tools and send what they learn with `submit`.
- **Code does git, not the model.** The model files cards in a sandbox. Then the wrapper decides:
  no result, a held result, or any change to a protected path holds the item and resets the
  clone. A secret check runs on every commit. The model never runs git.
- **Protected files only by proposal.** The core files, the rules, the keeper's own procedures, and
  skills change only through a pull request I merge. Merging is the only approval; a comment never
  approves a protected change.
- **No model in the lookup path.** The lookup server searches, reads, and queues; the calling agent
  does the thinking.
- **Private items stay out.** Before filing, a separate privacy step sorts every incoming item.
  Private items go to a store on the server run by separate Linux users, one with no model at all,
  in a local git repo with no remote. The boundary is file permissions, not instructions in a
  prompt, and if the privacy step is down nothing reaches the brain. A mixed item is filed
  privately whole, and the brain gets only the shareable excerpt with a pointer. Since 2026-11-07
  an item the sorter is unsure about settles to private.

## The tradeoff

- **One keeper is one queue.** Filing runs every 15 minutes, so a new fact isn't instant, and
  everything stops if Mimir stops.
- **Filings skip the PR rule.** Mimir commits ordinary filings straight to `main`, the main
  exception to "agents open PRs". Git history and checks after the fact are the safety net, not a
  review before the commit.
- **Defaulting to private loses things.** Unsure means private, so some useful material never
  reaches the brain until I release it by hand.

## What broke

- **Proposal PRs that conflicted with each other.** On 2026-11-03 one filing run opened seven
  proposal PRs, six of them changing the same procedures file, each built from `main` on its own.
  Each merge could conflict the rest, and two sat conflicting for about 30 to 45 minutes. The fix:
  proposals from one run that touch the same file share one PR, a PR is rebuilt on `main` after
  any merge that touches its files, and a PR someone else has pushed to is never rebuilt.
- **The private default caught the wrong thing.** A design document written by my own builder
  agent was kept in the private store by the unsure rule and never reached the brain. A fix that
  lets that exact kind of agent output skip the check was built on 2026-11-09.

## Use it yourself

1. Split memory into a small core you protect, short cards, and raw sources you never edit.
2. Give one agent write access, with a credential scoped to that one repo.
3. Let the model write files, and let code decide what gets committed.
4. List your protected files in code, and route changes to them through PRs you merge.
5. Sort private material out before filing, behind an operating-system boundary, and default unsure
   items to private.
