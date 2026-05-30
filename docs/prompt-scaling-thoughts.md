# Side note: prompt bloat and scaling rule-coverage to production

Not part of MemoCheck's scope. This is a thinking-out-loud note on a real production
question the v1 date work raised: how far can you keep teaching a model rules by stuffing
them into the prompt?

## The question

MemoCheck's time-of-day rules are workday-shaped ("after lunch", "EOD", "before I leave
today"). Fine for a focused benchmark. But a real product would also need "before lunch",
"breakfast", "after dinner", different rules per culture and timezone, and a long tail of
other phrasings. Each one is another line in the prompt, or another example. Can you just
keep adding them?

## Short answer: no, and this is a real production issue

A prompt that only grows hits three walls:

- **Cost and latency.** Every rule and example is tokens on every single call. At thousands
  or millions of calls a day, a bloated system prompt is a real bill and a real slowdown.
- **The model stops listening.** Models have a limited budget for following instructions.
  Past a point, more rules don't help and can hurt: instructions get diluted, the model
  skims the middle of a long prompt (the "lost in the middle" effect), and edge rules start
  to conflict. You can actually lose accuracy by adding more, and weaker/cheaper models hit
  this wall sooner, which is exactly the segment a cost-sensitive product runs on.
- **Maintenance.** A giant prompt is hard to reason about, hard to test, and any edit can
  quietly shift behavior on unrelated inputs.

## What you do instead

The main move is to stop asking the model to memorize deterministic rules at all:

- **Pull deterministic logic out of the prompt.** Let the model do the fuzzy part it's good
  at (read "after lunch" and tag it as a vague-time phrase) and let plain code resolve the
  phrase to a time with a lookup table. The table can be as big as you want: it's testable,
  versioned, free per call, and adding "before lunch" is a one-line data change instead of a
  prompt change. In MemoCheck terms, our canonical-time table would live in code, with the
  model just emitting the phrase.
- **Retrieve examples instead of listing them all.** Keep a library of examples and pull the
  few most relevant to each input, rather than carrying all of them on every call.
- **Fine-tune once you have data.** Enough labeled examples lets a smaller model learn the
  rules in its weights instead of in the prompt.

## The signal to watch

The practical limit isn't a fixed token count, it's behavior. Watch accuracy as the prompt
grows: when adding rules stops improving (or starts hurting) the weakest model you support,
that's the cue to move that logic out of the prompt rather than pile on more.

## Why MemoCheck still puts the rules in the prompt

Because the project is deliberately measuring the model's raw single-call ability to extract
intent, not building the production system around it. Moving normalization into code would
measure our code, not the model. So the in-prompt rules are the right call here, and "this
isn't how you'd scale it" is a fair limitation to note in the README.
