# Flattened action-item metrics with three-tier scoring

Per-type scoring (separate metrics for todos, reminders, events) creates a double-penalty when the agent and ground truth disagree on type. One misclassification counts as both a missed item AND a hallucinated item. We instead flatten todos/reminders/events into a single pool of action items and score in three tiers: **detection** (was the item found at all?), **classification** (was the type correct?), and **field accuracy** (were the key fields right?), with each tier scored only when the previous tier passes.

This mirrors how the NER community handles the same problem (MUC-7, CoNLL evaluation conventions) and gives a cleaner diagnostic for iteration: we can now say "the agent finds 95% of action items but only types them correctly 80% of the time" instead of mashing both signals into one number.
