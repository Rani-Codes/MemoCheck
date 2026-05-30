# v1 agent prompt design

Date: 2026-05-29
Status: approved, then reviewed and tightened in a grilling session.
What this produces: `src/memocheck/agent/prompts/v1.py`, which exports `SYSTEM_PROMPT`.

## What we're doing and why

v0 already works pretty well. When it gets something wrong, it's usually because the model
doesn't know one of our labeling rules yet, not because the prompt is broken. So v1 doesn't
rewrite anything. It keeps v0 as-is and teaches the model the specific rules it's missing.

We keep the changes small and targeted on purpose. That way, when we compare v0 to v1, it's
easy to see which fix caused which improvement, and we don't accidentally break the things
v0 already does well.

This doc is just the plan. We don't run the model or spend any API tokens here. We also
don't open the 6 held-out test cases (memo_001, memo_005, memo_009, memo_011, memo_016,
memo_022) while designing v1, per ADR-004.

## What this is based on

- `docs/v0-failure-analysis.md`: where v0 falls short, ranked.
- `docs/v0-matcher-validation.md` and `docs/adr/002-*`: how matching and scoring work, and
  why v0 and v1 have to be scored the exact same way.
- `docs/labeling-guide.md`: the rules we're teaching the model. This is the source of truth.
- `src/memocheck/agent/prompts/v0.py`: the prompt we're building on.
- `src/memocheck/agent/schema.py` and `extractor.py`: the output format, and how the
  agent's text gets parsed.

## Where v0 falls short (most to least important)

1. Dates: 80.5% accurate, the biggest gap. Two pieces are weak: vague times of day like
   "after lunch" (48.3%), and deadlines like "before Friday" mixed in with other items
   (41.7%). Plain relative dates like "next Thursday" already work.
2. Picking the right type: 94.7%. The model sometimes files an action as a Reminder when it
   should be a Todo, or files a "review this" / "set up that" action as a Reminder or Event.
   Weakest on Anthropic Haiku (90.2%).
3. Hallucinations (extra items the transcript doesn't support): 6.5%. The model sometimes
   turns a passing comment into an action, or emits the same thing twice (once as a Todo,
   once as a Reminder). #2 and #3 share the same root cause.
4. One missed retraction: a cancelled reminder that didn't get flagged, on Groq only.
   Negation handling is otherwise 99.4%; this is the only false-negative, 0.6% overall.

## The approach we picked: extend v0, don't rewrite it

Keep v0's wording wherever it already scores well, and add four small blocks plus a few
examples.

We looked at two other options and passed:

- A full rewrite. Cleaner to read, but it changes everything at once, so we couldn't tell
  which edit moved which number, and we'd risk breaking what already works.
- Lots of examples. More examples cost more tokens on every run (and there are 360 runs),
  and risk the model just matching phrasings it has seen. Our gaps are better fixed with
  clear rules than with more examples.

## Decisions we've locked in

- Vague times of day are taught as one specific time to output, not a range. The agent has
  to commit to a single time, so we hand it one (e.g. "afternoon" -> 3pm). We pick a time
  sitting comfortably in the middle of the allowed range, so a small wording change later
  won't break it.
- The date fix covers both vague times of day (guide section 5) and "before / by / after a
  weekday" (guide section 7). We're leaving the "sometime next week" style rules (section 6)
  out, for the reason in Section 1b.
- Any examples we add are made up, never copied from the 30 test cases. That keeps the
  comparison fair.
- No reasoning / "think out loud" step. Rules only (see Section 5).

## The plan, section by section

### Section 0: what we keep from v0 untouched

These all score at or near the top already, so we leave the exact wording alone: the intro
line, the `{current_date}` placeholder, the four category definitions, the JSON template,
the "JSON only, no markdown" instruction, the assignee rules (96.8%), the grocery-list
rule, the negation rules (99.4%), and the existing relative-date handling ("next Thursday",
"in two weeks"). v1 only adds on top of these.

### Section 1: dates and times (the biggest fix)

1a. Vague times of day -> one time to output. The agent emits a single time, so we give it
one for each phrase. Each sits in the middle of the range the guide allows, so it lands
with room to spare:

| phrase | output | allowed range |
|---|---|---|
| morning | 09:00 | 06:00-12:00 |
| midday / lunch | 12:30 | 12:00-13:00 |
| afternoon | 15:00 | 12:00-18:00 |
| after lunch | 14:00 | 13:00-17:00 |
| evening | 20:00 | 18:00-22:00 |
| tonight | 20:00 | 18:00-23:59 |
| end of day / EOD | 23:59 | up to 23:59 |
| before I leave today | 17:00 | up to 18:00 |

Also: "early {X}" pushes the time about an hour earlier, "late {X}" about an hour later.
Handle the day first ("tomorrow afternoon" = tomorrow at 3pm). A date with no time stays
23:59 (v0 already does this). EOD landing right on 23:59 is fine: the range runs up to
23:59 and v0 already uses it.

This table mirrors the labeling guide's section 5 list exactly, so there's no "before
lunch" entry (the guide doesn't define one). If we wanted one, we'd add it to the guide
first, then mirror it here.

1b. "Before / by / after a weekday" (guide section 7). This is the deadline gap (41.7%). v0
has no rule for it and probably treats "before Friday" as Friday itself:

| phrase | output |
|---|---|
| before {weekday} | the day before it, 23:59 ("before Friday" -> Thursday 23:59) |
| by / no later than {weekday} | that weekday, 23:59 |
| after {weekday} | the day after it, 00:00 |

Why we're skipping the "sometime next week" style rules (guide section 6): on the visible
test cases, every vague relative-date already scores 100% (synth_002 "around the holidays",
memo_010 "in two weeks"). There's no visible failure to fix here, so adding rules for it
would be guessing at a problem we can't actually see. v0's existing "+14 days" / "+30 days"
lines stay; we just don't add new week-range rules. ("by next {weekday}" is already covered
by the section 7 rule above.)

### Section 2: picking the right type

Build on v0's type rules:

- Keep "remind me to {verb}" -> Todo.
- Add "set a reminder to {verb}" / "set a reminder for {date} to {verb}" -> Todo. The "set
  a reminder" part just sets the deadline (use that date as the due date); it doesn't make
  the item a Reminder.
- Add: "review", "set up", "book", "plan", "prepare" style actions -> Todo, not a Reminder
  or Event ("review the proposal", "set up customer interviews", "book the campsite").
- Tighten what a Reminder is: just being aware of a fact or date, with nothing for the
  speaker to do (an anniversary, a birthday, "your parents' flight lands at 9am"). If
  there's something the speaker has to do, it's a Todo.
- Keep Event = a booked, fixed-time commitment with other people. If the speaker isn't sure
  it's happening, put it in notes and capture any follow-up as a Todo (v0 already does this).

Anthropic Haiku is the weakest here (90.2%), so if its type score jumps in v1, that's the
clearest sign the fix worked.

### Section 3: one thing said = one item

The thing to understand first: when v0 makes up an extra item, it isn't really being
greedy. It already caught the real item with the right type, then added a second one
because it treated the "don't forget" or "remind me" wording as its own reminder. So the
fix is about what that wording means, not about telling the model to make fewer items.
(Telling it to "make fewer items" would backfire and make it miss real ones.)

- 3a (a comment or background fact -> notes, never an action): if the speaker is just
  observing something, with nothing to do and nothing specific to be reminded of, put it in
  notes and leave the action lists empty. Facts mentioned in passing (a renewal date, a
  price, a status) are background: put them in notes or leave them out. Don't turn a comment
  or a background fact into a Todo, Reminder, or Event.
- 3b ("don't forget" doesn't mean a second item): wording like "remind me to", "don't
  forget to", "make sure to", "don't be late" wrapped around an action or event does not
  add a separate Reminder. Catch that one thing once, as its correct type. Don't emit both a
  Todo and a Reminder, or both an Event and a Reminder, for the same thing. This only kicks
  in when there's an actual action or event behind the wording, so it never touches a real
  "just be aware" Reminder, which keeps it in line with the Reminder definition in Section 2.
- 3c (the safety rule that protects real lists): every separate thing the speaker brings up
  is still its own item. This rule only removes a repeat of one thing; it never merges or
  drops genuinely different actions, events, or reminders.

This sits right after Section 2 because they're really the same problem (the right thing
caught as the wrong type, or caught twice).

#### The risk here, and what we'll do about it

"The same thing" is a judgment call the model makes, so it could occasionally treat two
different things as one and drop an item. The risk is small (v0 already handles multi-item
memos at 97.8% with no rule pushing the other way) but it's real, since 3a and 3b only push
toward fewer items.

- What we watch: the detection score on the multi_action cases in the v1 run. The visible
  signal is tiny (memo_013 and memo_020), so we don't react to small wiggles. It only counts
  as a real problem if we look at the missed items and confirm the model actually merged or
  dropped two separate things because of this rule, not because of a type or date mistake.
- What we do if it's real: loosen 3a/3b (keep 3c), and run that as v2 on its own, with
  nothing else changed, so we can see clearly whether detection comes back and whether the
  made-up-items number creeps up again.

### Section 4: the made-up examples

About four short examples, all invented, none taken from the 30 test cases, each kept
clearly different from the real case it reinforces. In the prompt each one is written as
the transcript followed by the full JSON to return, with all four keys present and the
unused lists shown as empty arrays (`[]`). That shows the exact shape we want and
reinforces the "empty arrays, never nulls" rule from Section 0:

- A comment -> notes (vs memo_004 / memo_014): "The upstairs radiator's been clanking at
  night again." -> just a note, no actions.
- "set a reminder to..." as one item (vs memo_019): "Set a reminder to renew my passport by
  the tenth." -> one Todo (renew passport, due the 10th at 23:59), no separate Reminder.
- "don't forget" on an event (vs memo_003): "Standup's at 9, don't forget to dial in." ->
  one Event (9am), no extra reminder, not negated.
- A cancelled reminder (vs synth_003): "Remind me about the block party Saturday. Actually
  never mind, it got cancelled." -> one Reminder, marked negated, item kept.

We stop at about four. More than that is the "lots of examples" approach we passed on.

### Section 5: reasoning step (settled: rules only)

No "think out loud" field. v0's misses are missing rules, which the rules above fix
directly, so a scratchpad wouldn't add much (and at temperature 0 it helps even less). Two
reasons it's not worth it:

- A reasoning field risks the weaker models (Groq Llama, Anthropic Haiku) writing their
  thoughts outside the JSON, which breaks parsing and would knock down our 100% clean-output
  rate, on exactly the models that are already weakest.
- It would muddy the before/after story: a type improvement might come from the reasoning
  rather than the rules, and we couldn't tell which.

If we ever want to measure what reasoning adds, the clean way is a new version (v_) that adds only the
reasoning field on top of these rules, so we can see its effect by itself.

## Things we must not break

- The agent keeps outputting plain local times (no timezones). The scorer handles the
  timezone math (ADR-003); the agent never has to think about UTC.
- Output has to match the `ExtractedMemo` format: empty lists instead of nulls, one model
  call, temperature 0, JSON only.
- v1 lives at `src/memocheck/agent/prompts/v1.py` and exports `SYSTEM_PROMPT`; keep the
  `{current_date}` placeholder (the extractor fills it in).
- v0 produces valid output 100% of the time on the first try. Don't drop below that.

## How we'll check v1 (later, not now)

- Score v0 and v1 the exact same way (same matcher, same saved judge cache in
  `data/judge_cache.json`), or the comparison mixes up "the agent changed" with "the scoring
  changed".
- Per the CLAUDE.md plan: run v1 on all 30 cases, run v0 on the held-out 6 to fill in the
  grid, then report three views (the visible 24, the held-out 6, and all 30) with error bars
  (ADR-005). That run actually costs tokens, so we get the go-ahead first.
- Watch Anthropic Haiku's type score as the sign the typing fix landed, and the multi_action
  detection score as the Section 3 safety check. Re-check every number after the run.

## Not part of v1

- "Sometime next week" style date rules (section 6), skipped above.
- Saving the model's reasoning, or any tracing tools (that's future work in CLAUDE.md).
- Any change to the scorer, the schema, or the extractor. v1 is only a prompt change.
