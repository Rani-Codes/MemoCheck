# Ground truth time-window schema

Ground truth needs to express vague date references ("sometime next week", "by Friday", "after the meeting") that the agent's exact-datetime output schema cannot. We introduce a parallel `GroundTruthReminder` / `GroundTruthTodoItem` / `GroundTruthCalendarEvent` set of models with two date fields where the agent has one: `remind_at` for exact matches and `remind_at_window: TimeWindow` for range matches. `TimeWindow` is a structured object with optional `start` and `end` datetimes, where a missing bound represents an open range. This handles exact times, single-day windows, multi-day windows, before-X, and after-X uniformly with no vocabulary to maintain.

We rejected string-encoded constraints (e.g. `"any_time_in_week_of_2026-05-11"`) because they fail late (typos crash at scoring time, not validation time), require a parser branch per form, and cannot be validated by Pydantic at model construction. Structured `TimeWindow` objects fail loud, fail early, and extend cleanly.

### Eval logic (normalized to overlap)

Both ground-truth and agent date fields can be one of: a `date` (all-day), a `datetime` (time-specific), a `TimeWindow` (ground-truth only), or null. To avoid a combinatorial mess of comparison branches, scoring normalizes both sides into a window-overlap check:

1. If *both* ground-truth date fields (`remind_at` / `remind_at_window`, etc.) are null → pass iff the agent's date field is also null; fail otherwise.
2. Normalize each side:
   - A `datetime` becomes the point `[dt, dt]`, with a ±60s tolerance applied symmetrically when comparing point-to-point.
   - A `date` becomes the inclusive window `[date 00:00:00, date 23:59:59]` UTC.
   - A `TimeWindow` is used as-is.
3. Pass iff the agent's normalized point/window overlaps the ground-truth's normalized window.

This is one function. No per-shape branches.

### Known limitations accepted for v0

- Discrete sets ("Monday or Tuesday") are encoded as a single covering window rather than `list[TimeWindow]`. Acceptable distortion at this scope.
- All datetimes are assumed UTC anchored to `memo_recorded_at`.
- `TimeWindow.start` and `TimeWindow.end` are typed `Optional[datetime]`, while the exact-form fields are `date | datetime`. A labeler writing a window like "May 11" therefore needs to pick explicit start/end datetimes (typically `2026-05-11T00:00:00` and `2026-05-11T23:59:59`). This asymmetry is intentional -- a `TimeWindow` always represents a bounded range, so collapsing date-level windows to datetime bounds keeps the eval logic uniform. A labeler-facing helper to build day windows is fine to add later but not required for v0.
- When ground truth uses a datetime and the agent emits a date-only value (or vice versa), the date is normalized to a full-day window and the comparison passes if the datetime falls within it. This is a deliberate lenient choice: the agent at least got the day right, which is valuable signal at our small N. v2 can tighten this if information-loss penalties become important.
