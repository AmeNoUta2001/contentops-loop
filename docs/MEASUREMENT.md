# Measurement specification

> This is the English counterpart of the core of `docs/01-诊断口径.md` (which contains the full
> Chinese specification, including the parts that only matter for the original vertical).
>
> Two kinds of statements appear below, and they are labelled on purpose:
> - **[SPEC]** — a definition this project chooses. It needs to be internally consistent and
>   reproducible; it does not need any platform to agree with it.
> - **[OBSERVED]** — something measured on a real account. It says what was seen there, not what any
>   platform does internally.
>
> Explanations for observations are marked as interpretations. No platform-side explanation in this
> project should be read as documented platform behaviour.

---

## 1. Why a fixed post-publish window

**[SPEC]** All comparative analysis uses a single window: the calendar day of publication
(if published at or before 12:00), otherwise the following day.

Why 12:00: content published in the afternoon does not receive a full day of exposure on the day
itself, and comparing that against a full day of data would understate it.

**Why not cumulative totals. [OBSERVED]** Two effects compound:

- exposure is not spread evenly over time — most of it arrives near publication;
- counters keep accumulating afterwards at a much lower click rate.

Both push cumulative CTR downward over time, so an article that performed well early looks
progressively worse in a cumulative view. That is an artifact of the denominator, not a change in the
content. Cumulative values are therefore still stored and charted for long-term trend, but they are
**not** used to judge health.

## 2. The three metrics

| Metric | Definition | How this project uses it |
|---|---|---|
| First-day impressions | impressions accumulated inside the window | approximate early-distribution volume |
| First-day reads | reads accumulated inside the window | paired with impressions for CTR |
| First-day CTR | first-day reads / first-day impressions | approximate click-side performance |

Source priority for the window value:

1. platform per-day traffic data for the publication date (preferred);
2. otherwise the snapshot taken during/after the window — documented as a **lower bound**;
3. otherwise the article is excluded as non-comparable.

> Two sources for the same article can differ by roughly 2x, because a snapshot is a point-in-time
> capture while per-day traffic is a completed bucket. Every row records which source was used
> (`src`); do not mix sources inside one comparison.

## 3. Diagnostic decomposition

**[SPEC]** Early distribution is decomposed for diagnostic purposes:

```
first-day impressions  ≈  structure freshness  ×  topic pool size  ×  account-level allocation
```

⚠️ **This is a working diagnostic framework, not a statistically estimated causal model.** The terms
are not independent, and their coefficients are not identified from observational data. Its purpose is
to force separate investigation of different failure causes, not to predict values.

| Dimension | Observable? | How it is examined |
|---|---|---|
| Structure freshness | partly controllable | reusing the same narrative structure repeatedly is **[OBSERVED]** to coincide with a steep drop in early impressions while CTR stays normal. One *interpretation* is same-content de-duplication; there is no platform-side evidence for that mechanism. |
| Topic pool size | selectable | group history by topic and rank by the median first-day impressions **with viral outliers excluded** |
| Account-level allocation | not controllable | inferred only when *all* topics drop at the same time; this term cannot be measured precisely |

**Viral exclusion is mandatory** for pool ranking: one article with 5-digit impressions otherwise
carries the whole topic median.

## 4. Disposition table

**[SPEC]** Suggested action per article, first match wins:

| First-day impressions | First-day CTR | Diagnosis | Action |
|---|---|---|---|
| high | ≥ pass line | healthy | publish a second article on the same axis (reproducibility check) |
| medium | normal | pool too small | move to a larger pool next time |
| low | ≥ strong-CTR line | **under-distributed** — not disproven, just not tested | re-publish with a new title/cover within 24h (max 1 per article, 2 per week) |
| low | 1% – strong line | click-through too low | change axis (structure) |
| low | < 1% | title/cover problem | change title and cover |

> The numeric cut-offs (`big_pool_show`, `small_pool_show`, `own_pass_ctr`, `own_strong_ctr`) live in
> `config/vertical.json`. The shipped values are calibration outputs from one vertical, and are meant
> to be re-measured — the documentation says so wherever they appear.

The point of the table is one distinction: **low distribution + high CTR and low distribution + low CTR
are opposite situations.** The first is worth re-publishing; the second needs new content. Collapsing
them into "performance was poor" leaves no actionable next step.

## 5. Stop gate

**[SPEC]** A heuristic of this project — not a platform rule. It fires only when both hold:

1. median first-day impressions of the last 5 articles < half the 30-day median, **and**
2. zero articles in the last 14 days reached the CTR pass line.

**Veto:** if the median first-day CTR of the last 5 articles is still ≥ 6%, the gate does not fire.
The click side is healthy, so the problem is distribution, and stopping would forfeit the work.

Its purpose is to constrain *when* the decision "stop publishing" becomes available, so it is not taken
on the strength of two bad days.

## 6. Calibrating the pass line

Do not guess:

1. use `benchmark_store.py` to collect comparable articles and bucket them **by article age**;
2. locate your own position within your own age bucket;
3. take the level clearly above the median as the pass line.

**Bucketing is mandatory** — articles of different ages are not comparable, because a new article
necessarily has fewer impressions. Buckets below `min_n_quantile` report "insufficient sample" rather
than a quantile.

## 7. What this specification deliberately does not do

- No causal inference. Every "why" is a candidate explanation, never an established result.
- No absolute prediction. The framework is not used to predict read counts (this was tried once, was
  falsified by the project's own data, and was removed).
- No hidden insufficiency. When the sample is small, the output says so instead of producing a number
  that looks usable.
