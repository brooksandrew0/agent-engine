# One daily brief

Every agent that needs me goes through one GitHub issue a day. I answer in its comments with short
verbs, and code turns those into actions. The point is to bound my attention, not the agents'.

## The problem

As the agents multiplied, so did the ways they reached me. The brain keeper posted a daily roundup
issue with its questions. Smithers, the chief of staff, posted a morning brief. The Judge opened its
own issue for eval grades. Pushes reached my phone for filed and held items. By 2026-11-05 I had two
daily issues running side by side, left over from a one-week trial, and questions arriving from
several producers in several places.

## What I did

**One issue, at 09:00.** Smithers posts it. Sections: Today (the only part a model writes), Needs
you, Tracked, Requests, Eval, Health, and Receipts. The rule for building it was "move, don't
re-create": each agent kept its own tested code and renders its own section, and only the posting
moved. The separate roundup issue was retired, and the Judge's cases became the Eval section. It
has been the one daily issue since 2026-11-07.

**Short verbs on IDs.** Every item has an ID with a letter for its kind, and I answer in comments:
`R3 go` to start a request, `R3 good` or `R3 redo: what was missing` to grade a delivery, `E1 good`
for an eval case, `Q7` followed by an answer, `undo` to cancel. Mimir reads comments every 3
minutes and acts after 2, which leaves time for `undo`.

**Questions take a route.** An agent working on its own asks Mimir first, which answers only from
what the brain records, with citations, never with new decisions. What Mimir can't settle goes to
Smithers, who tracks it as a blocker and asks me in the issue. Each run asks at most three
questions, each with a recommendation, and an item has at most three unsettled at once. Questions
expire after 7 days of waiting.

**One shared daily count.** Every producer's questions count against one number for the day. It
started on 2026-11-02 as a budget of 10 a day. On 2026-11-06 questions from jobs got a limit
of 4 of those 10.

**Pushes only for what's urgent.** My phone still gets a fixed-text receipt when a memo arrives,
request delivered or blocked notices, and real alarms. Everything else goes in the issue.

## The tradeoff

- **Latency.** Anything that needs me waits for 09:00 unless it pages.
- **One page gets long.** Mimir's sections share a 45,000-character limit, and the least needed
  sections are shortened and then cut first.
- **One point of failure.** If the issue doesn't post, I see nothing. So the posting has its own
  alarm.
- **Code over model.** Only the Today section comes from a model, and it never sees requests. That
  keeps injected text out of most of the page, but a new kind of section means new code.

## What broke

- **It didn't fit.** On the install night, 2026-11-06, the dry run gave Mimir's sections 65,807
  characters against the 45,000 limit: about 490 open "decided for you" items, each on its own
  line. I added shortening levels (newest 25 on short lines, the rest by ID) and a final cut by
  section, so the total fits by construction and every ID still takes answers.
- **Questions I couldn't answer from the page.** My grade of the 2026-11-08 brief: questions didn't
  carry enough context, and I didn't know what earlier requests were. Now a question about a request
  carries its label, its state, and Mimir's reading of what I asked for.
- **The cap blocked work.** On 2026-11-09 three questions from one design run sat waiting behind the
  4-a-day job limit and blocked that request. A waiting question is work blocked on me. I removed
  the job limit and turned the daily 10 into an emergency stop at 30: when a day hits it, the brief
  leads with a "question stop hit" line and the rest wait a day. The per-run and per-item limits do
  the real work; the daily number now only stops a looping producer.

## Use it yourself

1. Pick one place and one time for everything that needs you, and retire the other channels.
2. Give every tracked item a short ID, and define a few verbs you can type on a phone.
3. Route agents' questions through a lookup over your recorded decisions before they reach you.
4. Limit questions per run and per item, and keep a daily number only as a stop for runaways.
5. Grade the brief itself now and then, and fix what makes a question hard to answer.
