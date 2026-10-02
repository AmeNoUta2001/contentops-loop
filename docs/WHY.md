# Architecture Decision Record — ContentOps Loop

This document records **why** the system is shaped the way it is. It is written as a set of decisions,
each with the context that forced it, the alternative that was rejected, and the consequences we accept.

It is deliberately not a pitch. Several entries below exist because an earlier version of this system
did the opposite thing and produced a wrong decision.

Format: **Context → Decision → Consequences → Rejected alternative.**

---

## ADR-001 — Measure in a fixed post-publish window, not on cumulative totals

**Context.** Platform dashboards present cumulative counters (impressions, reads, CTR) as the primary
metric. Those counters keep moving after publication: impressions accumulate unevenly over time, and the
impressions that arrive later convert to reads at a much lower rate than the first batch. As a result,
cumulative CTR of a healthy article drifts downward for reasons that have nothing to do with the article.

**Decision.** All comparative analysis uses a single **first-day window** (publish time ≤ 12:00 → same
calendar day; later → next day). Cumulative values are still stored and displayed for long-term
trend observation, but they are not used to judge whether an article is healthy. The window definition
is *our* analytical construct; it is not claimed to mirror any internal platform concept.

**Consequences.**
- Articles become comparable to each other and to their own past.
- Half-day data is never compared against full-day data (the 12:00 cut).
- Two data sources for the same article can disagree by ~2x (a snapshot is a point-in-time capture,
  while per-day platform traffic is a daily bucket). Mixing them within one analysis invalidates it,
  so the source is recorded per row (`src`) and the snapshot value is documented as a *lower bound*.

**Rejected alternative.** Using cumulative metrics with a "minimum age" filter. It still mixes
flat-but-large denominators with healthy early performance, and the drift is not linear.

---

## ADR-002 — Refuse to score small samples

**Context.** Early on, a topic was ranked "large" because a single article in it had 5-digit first-day
impressions. The median for that topic was being carried by one outlier. Acting on that ranking meant
piling more content into what was actually a small pool.

**Decision.** Two guards, applied everywhere:
1. **Viral exclusion** — articles at or above `viral_show` are excluded from the *stable* median used for
   pool ranking (both values are shown, so nothing is hidden).
2. **Minimum sample size** — below `min_n_quantile`, quantiles and grades are replaced by
   "insufficient sample".

**Consequences.**
- Some topics are unrankable for a while. That is the intended behaviour, not a failure.
- Every ranking carries its sample count (`n`, `n_stable`) so a reader can discount it.
- Exit code `40` (`INSUFFICIENT_DATA`) exists as a first-class outcome so a scheduler does not have to
  treat "not enough data yet" as either success or failure.

**Rejected alternative.** Smoothing or imputing missing samples. It would produce a number for every
topic, which is exactly the failure mode being avoided: a number that looks usable being used.

---

## ADR-003 — Taxonomy is a deterministic rule set, not a model

**Context.** Topic classification decides which statistics get computed and which articles are compared
to each other. A misclassification therefore propagates into every downstream number. An LLM classifier
was available and would have been less work to write.

**Decision.** Classification is a deterministic keyword rule set stored in `config/vertical.json`:
topic family (first match wins, so specific families precede generic ones), motif, out-of-vertical veto
list, explicit AND-groups, and a manual override table for individual corrections. Every result returns
the matched keywords and a confidence level. Unmatched titles are reported as `unclassified` — the tool
does not guess.

**Consequences.**
- Re-running any analysis yields byte-identical classifications.
- A human review comment ("this one is actually X") becomes a one-line vocabulary edit, not a prompt
  change or a model swap.
- Vocabulary maintenance is manual work. In exchange, the vocabulary accumulates as a project asset
  instead of living inside a prompt.
- The vocabulary is data, not code — swapping verticals means editing one JSON file.

**Rejected alternative.** An LLM classifier. Rejected because it is neither auditable nor reproducible:
the same input can classify differently across runs, and "fix the classifier" has no single-line answer.

---

## ADR-004 — Evidence and decision are separate layers with different rates

**Context.** Several collectors were producing their own conclusions ("therefore we should do X").
The conclusions conflicted with each other, direction changed several times in a week, and afterwards
nobody could tell which change caused which result.

**Decision.** Analyzers emit **facts only**. Direction changes go through a single outlet, are rate-limited
(one change per period), and require at least three pieces of evidence pointing the same way. Ideas that
do not clear the bar go into a "pending" list with the reason they were not adopted, rather than being
silently dropped or silently applied.

**Consequences.**
- The system can legitimately output "no change this period". That is a valid result, and it has to be
  written down explicitly (otherwise the agent invents something to report).
- Technique-level learning (how to open, how to structure) can still be absorbed continuously, but must
  be recorded so the change is attributable.
- Slower response to genuine shifts. Accepted deliberately: unattributable speed is not progress.

**Rejected alternative.** Letting each analysis stream adjust direction directly. Observed to produce
oscillation and to destroy the ability to attribute outcomes.

---

## ADR-005 — Every change carries a rollback condition

**Context.** Changes were being adopted with a rationale and a start date, but no stated condition under
which they would be reverted. Changes therefore accumulated permanently, including the ones that did not
work, because "did it work?" had no defined answer.

**Decision.** A direction change must state four things: **evidence** (≥3 items, each as
source | fact | number), **counter-evidence / risk**, **effective date**, and **rollback condition**.

**Consequences.**
- Each change becomes a testable claim with an expiry condition.
- Requires writing down the disconfirming case in advance, which occasionally kills a change before it
  ships. That is a feature.
- Changes that never trigger their rollback condition still need periodic review, since "no evidence of
  harm" is not evidence of benefit.

**Rejected alternative.** Retrospective evaluation only. Retros tend to rationalise; a pre-registered
rollback condition cannot be rationalised after the fact.

---

## ADR-006 — Replay must not see the future

**Context.** The replay harness exists to answer "would this rule have helped?" using history. The most
common way to get a flattering answer is to let the evaluation see information that was not available at
the decision point — using the final outcome to define the candidate set, or including a snapshot from
after the decision date.

**Decision.** Every replay unit is built at an **as-of time `t`** and may only use data that existed at
`t`. The framework records the as-of boundary per unit and reports the number of units where the boundary
is violated (`asof_snapshot >= replay_date`), instead of assuming the operator got it right.

**Consequences.**
- Replay results are usually *worse* than the intuition they replace. That is the point.
- A candidate evaluator that only looks good without the boundary check is treated as unmeasured.
- The harness has been used to reject an external title-scoring service that showed no incremental
  signal under replay. A harness that only ever adopts is not an evaluation.

**Rejected alternative.** Full-history evaluation. It produces numbers that cannot be reproduced in
production, because production never has the future either.

---

## ADR-007 — Agents consume facts; they do not recompute them

**Context.** When an agent is handed raw data and asked for an analysis, it will recompute. Small
differences in rounding, de-duplication, or window selection produce numbers that disagree with the
canonical ones. The disagreement is invisible in the output — both look plausible — but downstream
decisions then rest on two different datasets.

**Decision.** Metrics are computed **once, in code**, and written to disk (`--json`, `reports/*.json`).
Prompts instruct the agent to cite those numbers and explicitly forbid recomputation, re-running the
collector, or editing the metric files.

**Consequences.**
- Numbers quoted by an agent are traceable to a specific script run.
- The scripts must be reliable enough to trust, which is why the core is deterministic and tested.
- Prompts must state which values are authoritative and where they come from; an agent with no
  inject-contract will re-derive rather than cite.

**Rejected alternative.** Letting the agent compute from raw payloads. Rejected: unreproducible, and
errors are indistinguishable from results.

---

## ADR-008 — Platform collectors are isolated from the analytics core

**Context.** The first implementation read platform-specific fields directly in analysis code, so the
analytic layer was implicitly tied to one platform's response shapes, and a change to any endpoint could
break measurement.

**Decision.** Collectors are the only components that know about a platform. They emit a documented
snapshot document; everything downstream is a pure function of snapshots. The snapshot shape is
described in `schemas/snapshot.schema.json`.

**Consequences.**
- The measured core can be developed and tested with synthetic snapshots, with no network and no
  credentials — which is exactly what the bundled `examples/` dataset demonstrates.
- Adding a platform is additive: write a collector that emits the same shape.
- Some platform nuance is necessarily lost at the boundary. Where a field is platform-specific, it is
  carried through as an optional field rather than interpreted by the core.

**Rejected alternative.** A generic "source" abstraction over each platform's native API. Rejected as
speculative: with one platform it would have been an untested abstraction layer, and the snapshot
boundary already provides the isolation that matters.

---

## ADR-009 — Unified exit codes instead of "exit 0 with a message"

**Context.** Several scripts reported real failures (expired credentials, upstream errors, empty
responses) and then exited `0`. Human readers saw the message; schedulers and CI saw success. The
distinction between "not enough data yet" and "the run failed" was also unrepresentable.

**Decision.** A shared code set in `scripts/exitcodes.py`:
`0` OK · `10` credential · `20` upstream · `30` bad data · `40` insufficient data · `50` config ·
`60` integrity · `64` usage. Machine-readable `PREFIX:` lines stay on stdout; human explanation stays
alongside or on stderr.

**Consequences.**
- A scheduler can retry on `20`, alert a human on `10`, and stay quiet on `40`.
- `40` is intentionally distinct: "insufficient data" is a normal state in a daily pipeline, and
  treating it as failure would train operators to ignore alerts.
- Scripts must be explicit about which category an error falls into, which occasionally forces the
  question "is this actually a data problem or a credentials problem?" — a useful question.

**Rejected alternative.** Ad-hoc codes per script. Rejected: the caller would need per-script knowledge,
and `sys.exit(0)` on error had already proven to be silently harmful.

---

## ADR-010 — Vertical vocabulary and thresholds are configuration, not code

**Context.** Topic families, out-of-vertical veto words, and calibrated thresholds were spread across
four scripts. Changing vertical meant editing all four, and a missed edit produced silently wrong
classifications rather than an error.

**Decision.** Everything vertical-specific lives in `config/vertical.json` — vocabulary, niche
in/out lists, manual overrides, and all numeric thresholds. Scripts contain only mechanism.

**Consequences.**
- Changing vertical is a one-file edit.
- "Vocabulary is empty" becomes a *detectable* state: scripts warn at startup instead of quietly
  classifying everything as `other`.
- Thresholds are explicitly calibration outputs, not constants. The shipped values are from one vertical
  and are expected to be re-measured — the documentation says so wherever they appear.

**Rejected alternative.** Keeping defaults in code with an optional override file. Rejected: the defaults
would silently be wrong for a new vertical, which is the failure mode this ADR exists to prevent.

---

## ADR-011 — Timestamps are interpreted in a fixed platform timezone

**Context.** The platform returns Unix timestamps. The obvious conversion,
`datetime.datetime.fromtimestamp(ts)`, produces a time in the **host machine's** local timezone. Two
consequences followed:

1. The first-day window decision ("published after 12:00 → window moves to the next day") flipped
   depending on where the code ran. The same dataset produced different disposition tables on a
   UTC machine and on a UTC+8 machine.
2. Worse, the derived publication *date* could land on the previous calendar day, which means the
   snapshot itself — the evidence layer every downstream number comes from — was quietly wrong.

This was found by CI, not by review: the suite passed locally (UTC+8) and failed on a UTC runner.

**Decision.** All platform timestamps and all "today" values used for data attribution go through
`scripts/platform_time.py`, which interprets them in a **fixed offset** (`CONTENTOPS_TZ_OFFSET`,
default `+8`). The host's `TZ` is irrelevant. Cosmetic timestamps in generated reports may still use
local time; anything that determines *which data is compared to which* may not.

**Consequences.**
- The core is reproducible across machines, which is a precondition for the entire "same input → same
  output" claim.
- A deployment targeting a different platform sets the offset once instead of patching call sites.
- Test fixtures must construct timestamps with an explicit timezone too, otherwise the *tests* inherit
  the host dependency they exist to prevent. A portability test now asserts byte-identical output under
  four different `TZ` values.

**Rejected alternative.** Setting `TZ=Asia/Shanghai` in CI. It would have made CI green while leaving
the product dependent on whoever runs it — the failure would return on the next non-CST machine.

---

## Related documents

- `docs/01-诊断口径.md` — the measurement specification *(Chinese)*
- `docs/02-工程决策与踩坑.md` — engineering pitfalls log, with the concrete incidents behind several
  ADRs above *(Chinese)*
- `docs/03-数据字典.md` — field-level data dictionary *(Chinese)*
- `docs/04-换赛道-移植清单.md` — what transfers when changing vertical, and what must be re-established
  *(Chinese)*
- `docs/05-真实cron-prompt脱敏.md` — five sanitized production agent prompts *(Chinese)*
