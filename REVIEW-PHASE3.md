# REVIEW-PHASE3.md — Adversarial review of the Usage dashboard (app.js)

Reviewer: fresh-context, did not write this code. Focus: numbers and filter semantics
in `app.js` (visual/render checked separately by the orchestrator). Independent baseline
recomputed in Python directly from `data.json` (617 rows), then app.js's filter/aggregate
functions were extracted and re-run in Node against the same data and cross-checked by hand.

## VERDICT: pass-with-nits

No wrong numbers, no NaN, no crash found in any code path I exercised. Every table cohort
(all / last-25 / date-range / category) reproduces my independent baseline **exactly**.
The findings below are semantic/labeling issues and one defensible-but-questionable stats
choice — none of them produce a mathematically wrong displayed value against the row data.

The implementer's headline claim is **CONFIRMED**: Fable 5 median output tokens, all
sessions = **112,856** (n=47, odd count, middle element is 112,856). My Python
`statistics.median`, app.js's `median()`, and hand inspection of the sorted array all agree.

---

## MUST-FIX (wrong numbers / NaN / crash)

**None.** I could not construct an input from the real data (or plausible edge inputs)
that makes app.js display a wrong number, NaN, undefined, or throw. Specifically verified
clean: empty set → `median` returns `null` → `fmtNum` → `—` (no NaN); single element;
even count → mean of middle two; numeric sort (`.sort((a,b)=>a-b)` — NOT the lexicographic
`.sort()` bug); zero-calls guard on tool-error-rate returns `null` (filtered out, no
divide-by-zero); duration ms→string math is correct including hours rollover and zero-pad-free
`Xm Ys`; log(0) is pre-guarded (val≤0 points dropped before `yScale`, and `Math.max(...,1)`
inside the log branch). Cross-checked numbers (all match app.js and Python):

| cohort | Fable 5 median out | Opus 4.8 | Sonnet 5 |
|---|---|---|---|
| all sessions | 112,856 (n=47) | 7,388 (n=443) | 29,901.5 (n=28) |
| last 25 / model | 80,225 (n=25) | 20,627 (n=25) | 29,831 (n=25) |
| 2026-06 (UTC, incl) | 221,499 (n=22) | 7,256 (n=423) | 41,159 (n=6) |
| build-feature | 112,856 (n=35) | 9,008 (n=208) | 10,185 (n=15) |

---

## SHOULD-FIX

**S1 — Tool-error-rate row aggregates rates by median/mean-of-ratios, not sum/sum.**
`TABLE_METRICS` "Tool error rate (errors/calls)" computes a *per-session* rate
(`tool_errors / sumToolCalls`) for each row, then the table takes the median and mean of
those per-session rates. The review brief (§5) and standard practice call for the pooled
rate `Σerrors / Σcalls`. The two disagree materially:

| model | table median | table mean | true pooled Σerr/Σcalls |
|---|---|---|---|
| Fable 5 | 2.4% | 5.2% | **3.4%** |
| Opus 4.8 | 2.3% | 4.3% | **2.9%** |
| Sonnet 5 | 3.3% | 5.1% | **4.0%** |

Mean-of-ratios over-weights low-call sessions (a session with 1 call and 1 error reads as
100%). This is not strictly "wrong" — the table's stated unit is per-session median/mean,
consistent with every other row — but "error rate" implies a pooled rate to most readers,
and no pooled figure is shown anywhere. Recommend either adding a pooled "overall error
rate" or relabeling to make the per-session-distribution framing explicit.

**S2 — Overview / chart / tool-usage panels ignore the table's filters, yet share the
"no sessions in range" copy.** `renderOverview`, `renderChart`, and `renderToolUsage` all use
`DATA.rows.filter(r => r.model === model)` with **no** date/category/last-X opts — only
`renderTableSection` applies filters, and the filter `change` listeners only call
`renderTableSection`. So the Overview cards, the tokens-over-time chart, and the Tool-usage
bars are **always all-sessions**, regardless of the From/To/category/last-N controls. The
controls sit under the "Comparison table" heading, so scope is arguably table-only — but the
three unfiltered sections reuse the string **"no sessions in range"** (lines 181, 365, 498),
which asserts a range that those sections never honor. That copy only appears when a model
has zero rows *at all*, so it is misleading rather than numerically wrong. Recommend: either
wire the filters through to all four views, or change the unfiltered sections' empty text to
"no sessions" (drop "in range").

**S3 — Chart uses a single shared y-scale anchored at the data minimum, not 0.** Linear
`yScale` maps `valExtent[0]→bottom, valExtent[1]→top`. With all three default models visible,
`valExtent` spans 0 … 4,305,814, so Opus's giant sessions compress Fable/Sonnet points into a
thin band near the axis. Not a bug, but the y-axis does not start at 0, so bar/point *height*
is not proportional to token count — easy to misread. The log toggle mitigates this. Consider
documenting or anchoring linear scale at 0.

---

## NITS

**N1 — Log-scale y-tick labels are non-round.** Ticks are `10^(lo + (hi-lo)*i/n)`, giving
labels like `21.22`, `450.42`, `9,559`. Cosmetic; values are correct.

**N2 — `fmtNum` sub-1000 branch rounds to 2 decimals** (`Math.round(n*100)/100`). Fine for
counts, but means "Median user turns" of e.g. 4 shows "4" while a mean of 4.333 shows "4.33" —
consistent and correct, just noting the mixed precision is intentional.

**N3 — Last-X tiebreak on equal `start_ts` relies on JS sort stability.** Exactly one
collision exists in the data (`Opus 4.8 | 2026-06-15T08:05:28Z`, 2 rows). `Array.prototype.sort`
is stable (ES2019+), so order is the original `DATA.rows` order — deterministic in practice,
but there is no explicit secondary sort key (e.g. session_id). Harmless at current data size;
would matter only at a last-X boundary landing exactly on a tie.

**N4 — Date filter is second-precision UTC, inclusive both ends.** `fromTs` = `…T00:00:00Z`,
`toTs` = `…T23:59:59Z`; rows compared with `>=` / `<=`. `start_ts` is second-precision UTC
(`…Z`), so boundary rows at exactly `00:00:00Z` / `23:59:59Z` are included as intended. A
hypothetical sub-second timestamp at `23:59:59.5` would be excluded, but none exist. Correct
for this data. Verified: 0 rows have null `start_ts`, so the `parseTs===null` guards never fire
in practice.

---

## WHAT I VERIFIED CLEAN

- **Fable 5 median output tokens = 112,856** (all sessions). Confirmed three ways.
- **All four table cohorts** (all, last-25/model, date-range, category) match my independent
  Python baseline to the exact integer — per-model n, median, and mean.
- **`median()`**: empty→null, single, even (mean of two middle), and **numeric** sort
  (no lexicographic `.sort()` bug).
- **Duration `fmtDuration`**: 0→"0s", 59000→"59s", 60000→"1m 0s", 3599000→"59m 59s",
  3600000→"1h 0m 0s", 3661000→"1h 1m 1s". Integer math and hours rollover correct.
- **Tool-error-rate divide-by-zero guard**: `calls>0 ? errors/calls : null`; null filtered
  before median/mean — no NaN, no Infinity.
- **"Last X per model" semantics**: each model's OWN most-recent X rows, sorted by `start_ts`
  descending, sliced per model (not a global last-X). Order is filter-then-lastX (date/category
  applied first, then the X most recent survivors) — consistent with the "Comparison table"
  scoping.
- **§4 multi-model cohort**: 53 sessions span >1 model; each (session,model) row is an
  independent row and legitimately appears once per model column. The caveat text in index.html
  states this. No user-turn/token double-count across model columns (rows are pre-split by the
  collector; the UI never re-joins them).
- **§7 framing compliance**: no "better/worse/wins/beats/best/rank/outperform" language in
  rendered copy — the only occurrences are the negated disclaimer and a code comment.
- **Cache tokens never folded into input**: `input_tokens`, `cache_read_tokens`,
  `cache_creation_tokens` are three separate table rows; nothing sums cache into input;
  no cache string in the chart tooltip.
- **Main vs subagent never silently summed**: separate `section` groups with the explicit
  "never summed into main" section label; subagent metrics live in their own rows.
- **Chart log-scale + zero tokens**: 29 rows have `output_tokens===0`; in log mode these are
  dropped before scaling (0/47 Fable, 1/443 Opus, 2/28 Sonnet dropped), and the log branch
  clamps with `Math.max(...,1)` — no `log(0) = -Infinity`.
- **Hidden-model exclusion**: chart points, legend, overview, and tool panels all iterate
  `allModelsSeen().filter(m => visibleModels.has(m))` — chip-hidden models are genuinely
  excluded from points AND legend.
- **Zero external deps**: no CDN / http(s) references in app.js or index.html (only the SVG
  namespace URI).
