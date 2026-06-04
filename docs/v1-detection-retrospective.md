# v1 detection retrospective (v0 -> v1)

## What this is

When we talk about v0 -> v1, we usually say two things got better: the agent picks the right
type more often (type accuracy), and it makes up fewer items (hallucinations). Both are true. 
But there's a flip side we didn't say out loud: v1 also got a little worse at *catching* 
every real item (detection). The same change caused both, so it's only fair to report both.

This doc lays out that detection dip, checks whether it's real or just a scoring quirk (it's
real), and explains why we didn't chase it the way the v1 plan said we might. Every number here
can be recomputed from the frozen data in `data/db_snapshot/`.

One thing to know up front: detection and hallucination are read off the same matching step, so
they tend to move together. Detection asks "did we catch each real item?" Hallucination asks
"did we invent items that weren't there?"

## The dip

These are pooled scores (we add up the raw counts across cases, we don't average the per-case
percentages). The error bars are 95% bootstrap confidence intervals from
`data/results/v0_vs_v1.json`.

| slice | v0 | v1 | change | error bars |
|---|---|---|---|---|
| all 30 cases | 0.9824 (613/624) | 0.9663 (603/624) | -0.0160 | [-0.0333, +0.0019], crosses zero |
| visible 24 | 0.9782 (493/504) | 0.9583 (483/504) | -0.0198 | [-0.0366, 0.0000], just touches zero |
| held-out 6 | 1.0000 (120/120) | 1.0000 (120/120) | 0.0000 | no change |

So it's small. On all 30 cases the error bars cross zero, so we can't be sure it's real rather
than noise. On the 24 cases we tuned v1 against, it's right on the edge of being real. On the 6
held-out cases there's no dip at all.

## Both numbers moved for one reason: v1 makes fewer items

Across all 30 cases, v1 wrote down 33 fewer action items than v0 (650 -> 617), and the notes
count barely changed (176 -> 178). Those 33 missing items split cleanly:

- 23 were junk we're happy to lose. That's the hallucination win (made-up items went 37 -> 14,
  error bars [-0.071, -0.004], clearly real).
- 10 were real items we wanted to keep. That's the detection cost (caught items went
  613 -> 603).

One change, both effects. The math lines up exactly: 650 = 613 real + 37 junk, and
617 = 603 real + 14 junk.

## Is the dip real, or did the scorer just shuffle things around?

Real. Two checks:

- If v1 had still written the items but phrased them so the matcher missed them, they'd show up
  as *hallucinations* instead. But hallucinations went down, not up. So the items aren't
  shuffled, they're gone.
- The notes count didn't move, so the missing items weren't quietly tucked into notes either.

Per case, the drop in items lines up with the drop in detection (same denominators, 12 runs
each):

| case | v0 caught | v1 caught | v0 items | v1 items |
|---|---|---|---|---|
| memo_018 | 27/36 | 24/36 | 27 | 24 |
| memo_010 | 24/24 | 21/24 | 24 | 21 |
| memo_013 | 60/60 | 58/60 | 66 | 61 |
| memo_020 | 60/60 | 56/60 | 63 | 58 |
| synth_003 | 10/12 | **12/12** | 10 | 15 |

Detection only drops when the one item covering a real thing disappears. So these 10 are
genuine misses: v1 sometimes treated two separate things as one and merged them, which is the
exact risk the v1 plan called out in Section 3. It isn't the good kind of trimming (moving a
passing comment into notes), that barely happened. The last row, synth_003, is the opposite:
v1 caught a cancelled reminder that v0 had missed, so detection there went *up*. The dip is
mostly on Anthropic Haiku and GPT-4.1 mini, and on busy multi-item memos that mostly aren't in
the `multi_action` category, so the "keep an eye on multi_action" plan was looking in the wrong
place.

## Why we're telling you, and why we didn't fix it

It's a good trade: we dropped 23 junk items to lose 10 real ones, and the hallucination win is
solid while the detection dip might just be noise. But here's the honest part. If we call the
hallucination drop a real win because its error bars clear zero, we have to hold the detection
dip to the same test and admit it's almost real too. We can't use the error-bar test for the
good news and skip it for the bad news. So the writeup reports the detection change right next
to the hallucination win, not buried.

The v1 plan said that if this dip turned out to be real, we'd loosen the merge rules and try it
as v2. We didn't. We spent v2 on the bigger date gap instead. This doc is the look we promised,
just done after the fact rather than as its own run.
