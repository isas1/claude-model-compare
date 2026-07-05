# METRIC-RULES-V2.md — v2 metric ADDENDUM (Track A)

Status: ADDENDUM to METRIC-RULES.md. This file adds new metrics; it does NOT modify
existing files, existing schema fields, or existing rules. Everything here is **additive**:
new fields only, no rename, no type change, no semantic change to any v1 field. A v1
consumer that ignores the new fields keeps working unchanged.

The v1 framing constraint (§7 of METRIC-RULES.md) is inherited verbatim and is BINDING on
everything below: descriptive not causal; no better/worse/wins/beats; metrics and labels
only, never conversation text.

Answering the design question — "how do these models differ in HOW they work?" — the honest
answer is a set of **shape** metrics that are ratios/derivations of things collect.py already
counts. Almost all of P0 is renderable client-side from the EXISTING data.json with zero
collector change. That is the deliberate bias for a same-day ship.

---

## 0. Design stance (read first)

Two hard truths that shape every metric below:

1. **Confounded by routing.** Which model handled a session was chosen by the user's router
   / manual pick, not randomly. So every cross-model difference is "in your usage, sessions
   that happened to run on X looked like…", never "X does Y." Wording enforces this.
2. **Cheap beats clever today.** A metric that is a pure function of the current 12-ish
   per-row integers ships this afternoon with no collect.py risk. A metric needing new
   collector passes (thinking blocks, stop_reason, parallelism, interrupts) is P1/P2 and
   gated behind schema additions that are themselves additive.

Cohort-size caveat is mandatory everywhere a per-model number is shown: Fable 5 (~46
sessions) and Sonnet 5 (~26) are small next to Opus 4.8 (~442). Medians on n<30 are noisy.

**Census amendment (2026-07-05):** a read-only census of 32 sampled transcripts (6,784
messages) verified several previously-unverified fields. Census numbers quoted below are
from that 32-file SAMPLE and are directional only — collect.py computes exact values over
the full tree at P1 implementation time.

---

## A. ACCEPTED metrics

Legend: **RENDER** = computed client-side in app.js from existing data.json fields, no
collector change. **COLLECT** = needs a new field written by collect.py (additive schema
addition, spec'd in §C).

### A1. Interaction shape — RENDER — P0

Per (session,model) row, all from existing `main` fields:

- **assistant messages per user turn** = `main.assistant_messages / main.user_turns`
  (autonomy proxy: how much the model does per human prompt). Guard: if `user_turns == 0`,
  the ratio is **undefined** — exclude that row from the ratio's cohort (do NOT treat as 0
  or infinity). Report the excluded count.
- **tool calls per user turn** = `sumToolCalls(main.tool_calls) / main.user_turns`. Same
  zero guard.
- **one-shot rate** = share of a model's rows where `main.user_turns == 1`. Cohort-level
  percentage, not a per-row value. (Rows with `user_turns == 0` — e.g. subagent-only rows,
  or sessions whose only user turn was dropped — are excluded from the denominator.)

Aggregation: report **median** of the per-row ratios across the cohort (mean underneath,
matching the existing table convention). One-shot rate is a single cohort percentage.

Edge cases: a model with an all-zero-user-turn cohort shows "—". Ratios are per-row then
medianed — never sum-of-messages / sum-of-turns (that pooling would let one giant session
dominate; the existing table pools ONLY the tool-error rate, deliberately, and that stays
as-is).

### A2. Tool mix profile ("explorer / editor / orchestrator" fingerprint) — RENDER — P0

Bucket each tool NAME already present in `main.tool_calls` into one of five classes, then
show each model's tool calls as a normalized **% across classes** (so a model with 10× the
absolute calls is still comparable). Classification is a static name→class map in app.js:

| class | tool names (exact, case-sensitive as they appear) |
|---|---|
| explore | `Read`, `Grep`, `Glob`, `LS`, `NotebookRead`, `ToolSearch`, `mcp__*read*`, `mcp__*search*`, `mcp__*list*`, `mcp__*get*`, `mcp__*fetch*`, `WebFetch`, `WebSearch` |
| edit | `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Artifact`, `mcp__*create*`, `mcp__*update*`, `mcp__*edit*`, `mcp__*write*` |
| execute | `Bash`, `BashOutput`, `KillBash`, `KillShell` |
| orchestrate | `Task`, `Agent`, `SendMessage`, anything matching `*ExitPlanMode*`, `mcp__*spawn*` |
| other | everything unmatched (Skill, TodoWrite, mcp__* not caught above, unknown names) |

Rule: lowercase-substring match for the `mcp__*` wildcards, exact match for the named tools;
named-tool match is checked BEFORE wildcard match. Unmatched → `other`. Store the map in app.js
as a single ordered list of `[regexOrName, class]`; first match wins.

Compute per model: sum each class's calls across the cohort's rows, divide by the cohort's
total calls → 5 percentages summing to 100. Cohort with zero tool calls → all "—".

Display: a 5-segment horizontal stacked bar per model (one row per model), % labels.
This is the single highest-signal "how they work differently" visual — it is the fingerprint.

### A3. Delegation propensity — RENDER — P0

From existing fields:
- **subagent share of output tokens** = `subagent.output_tokens /
  (main.output_tokens + subagent.output_tokens)` per row; median across cohort. Zero guard:
  denominator 0 → exclude row.
- **orchestrate-class call share** already falls out of A2 (the `orchestrate` segment).
- **subagent-active session rate** = share of a model's rows with `subagent.messages > 0`.

No collector change: `subagent` block already carries messages + output_tokens + tool_calls.

### A4. Cache efficiency — RENDER — P1

= `main.cache_read_tokens / (main.cache_read_tokens + main.input_tokens)` per row, median.
Reads as "share of context served from cache." Honest caveat: this is dominated by session
LENGTH and prompt-caching mechanics, not model behavior — label it "context reuse," place it
low, and do not let it read as an efficiency ranking. Zero guard: denominator 0 → exclude.
P1 because it is the weakest signal-per-pixel of the render-only set.

### A5. Verbosity (message-level) — RENDER — P0

= `main.output_tokens / main.assistant_messages` per row = mean output tokens per assistant
message, median across cohort. Distinct from the existing session-level output-tokens metric
(that one is confounded by session length; this one is per-message and closer to "how much
the model says each time it speaks"). Zero guard: `assistant_messages == 0` → exclude row.

### A6. Category × model usage-share matrix — RENDER — P0

Existing `task_category` + `model` on every row. Build a matrix: rows = models, cols = the 6
categories. Two honest normalizations, pick ONE for the headline and offer the other as a toggle:

- **row-normalized (recommended default):** within a model, what % of its sessions fell in
  each category. Answers "what did you tend to use this model for." Rows sum to 100%.
- **column-normalized:** within a category, what % of those sessions ran on each model.
  Answers "when you did debugging, which model handled it." Cols sum to 100%.

Render as a heatmap table (intensity = %). Cohort caveat on the whole table. This is the data
backbone of the suggested-use panel (§B).

### A7. Suggested-use / "tends to be used for" panel — RENDER — P0

Per model, derive a short observational profile from A2 + A6 + A1, NO new data:
- top 2 categories by row-normalized share (from A6)
- the dominant tool class (from A2)
- autonomy read from A1 (msgs/turn median: label bins — see §B wording)

This is the "what each model is suited to" section the user asked for, phrased strictly
observationally with mandatory caveats. Exact wording template in §B — the template is
BINDING, not a suggestion. This panel must never rank models or say one is better for a
category. It reports, per model independently, what that model's own sessions looked like.

### A8. Correction / follow-up cadence — COLLECT (cheap) — P1

"User sends a short message very soon after the assistant finishes" = weak frustration/
correction proxy. Derivable but NOT from current data.json (needs inter-message gap +
turn-length). Two sub-signals, both computed in collect.py during the existing single stream:

- **quick-follow-up rate:** count user turns whose timestamp is < 45s after the immediately
  preceding assistant line's LAST timestamp, divided by total user turns for the row. Uses
  the parentUuid/position machinery already built; add a counter.
- **short-follow-up:** of those quick follow-ups, how many had `has_real_text` content under
  ~120 chars (length of the flattened text — a LENGTH integer, never the text). Store the
  count only.

Store as row integers (see §C). P1 because it is genuinely useful but touches collect.py, and
its "frustration" reading is soft — must be labeled "cadence, not sentiment."

### A9. stop_reason distribution — COLLECT (cheap) — P1

Assistant lines carry `message.stop_reason` (`end_turn`, `tool_use`, `max_tokens`,
`stop_sequence`, sometimes null). CENSUS-CONFIRMED: the field is present on every assistant
line in the 32-file sample, and the distribution genuinely varies (tool_use 83–95%; None
rate 0.3–12%, with Fable/Haiku as the None-rate outliers). Distribution differs by how a
model works: high `tool_use` share = tool-driven loops; any `max_tokens` share = truncation
pressure. Collect a `{stop_reason: count}` map in the main block. Additive, one dict per row.
**None handling (binding):** a null/missing/non-string `stop_reason` is bucketed under the
key `"none"` — the line is NEVER dropped for lacking a stop_reason (it still counts in every
other metric, and in this distribution under "none"). P1 only because it needs a collector
re-run; promote to P0 if collect.py is being re-run anyway for A8.

### A10. Thinking block frequency — COLLECT (cheap) — P1 (PROMOTED from reject)

Census-verified extractable: content blocks with `type=="thinking"` appear on 26.4% of
assistant messages in the sample, with real per-model spread (Haiku 34.4%, Fable 31.7%,
Opus 26.9%, Sonnet 5 25%, Sonnet 4.6 22.1%) — a genuine "how they work" differentiator.

- **thinking_block_frequency** = share of MAIN assistant messages containing ≥1 content
  block with `type=="thinking"`. Collect-time: during the existing content-block loop on a
  kept main assistant line, if ANY block has `type=="thinking"`, increment
  `main.thinking_messages` once for that line (a line with 3 thinking blocks counts once).
  Render-time: `thinking_messages / assistant_messages` per row, median across cohort.
  Zero guard: `assistant_messages == 0` → exclude row. Main lines only for v2.
- **Thinking LENGTH / thinking token share stays REJECTED:** Fable and Opus return EMPTY
  thinking text (CoT omitted by the API), so any length-based metric is structurally biased
  against models whose CoT is redacted. Block PRESENCE is the only honest thinking metric.

### A11. Text verbosity in characters — COLLECT (cheap) — P1

Census-verified: average text-block char length varies ~5× by model (Fable ≈1,116 chars per
text block vs Sonnet 4.6 ≈226). Complements A5 (tokens per message) with a per-text-block
character view that is independent of tokenizer differences.

- Collect-time: on each kept MAIN assistant line, for every content block with
  `type=="text"` whose `text` is a string, add `len(text)` to `main.text_chars` and
  increment `main.text_blocks` by 1. **Privacy rule restated and binding for this field:
  store the two INTEGERS only — never the text, never a substring, sample, prefix, or hash
  of the text, in data.json or anywhere else. The v1 never-copy-conversation-text rule
  applies in full.**
- Render-time: **text_chars_per_text_block** = `text_chars / text_blocks` per row, median
  across cohort. Zero guard: `text_blocks == 0` → exclude row.

### A12. Parallelism (multi-tool-use per assistant message) — REJECTED (was P2)

DEMOTED by census: assistant messages with ≥2 `tool_use` blocks measured at 0.03% of
messages (1/2,963 in the sample). There is no signal to compare — the harness issues tool
calls one message at a time in practice. Reject; do not spend schema or UI space on it.

---

## B. Suggested-use panel — BINDING wording template

Placement: new section `#suggestedUseSection`, directly UNDER the existing disclaimer / above
the comparison table, so caveats are read first. One card per visible model.

Card template (fill the {slots}; never deviate from the observational verbs):

```
{Model}
In your usage, sessions on {Model} most often looked like {cat1} ({p1}%) and {cat2} ({p2}%).
These sessions leaned {tool_class_phrase} and averaged {autonomy_phrase} per prompt.
Based on {n} session(s).
```

Slot rules:
- `{tool_class_phrase}`: dominant tool class → phrase:
  explore → "toward reading and searching"; edit → "toward writing and editing";
  execute → "toward running commands"; orchestrate → "toward delegating to subagents";
  other → "toward mixed tooling".
- `{autonomy_phrase}`: median assistant-msgs-per-turn bin:
  `< 2` → "a short exchange"; `2–5` → "a few steps"; `> 5` → "an extended run".
- `{p1}/{p2}`: row-normalized category shares (A6). If a model has only one category, drop
  the "and {cat2}" clause.

Mandatory caveats attached to the panel (one block, always visible, not collapsible):

```
How to read this: these are observations about YOUR sessions, not claims about the models.
Which model ran a session was decided by routing and habit, not a fair test — so this reflects
what you reached for, not what any model is best at. Small cohorts (some models have well under
50 sessions) make these patterns noisy. This panel never ranks models or recommends one over
another.
```

Forbidden in this panel (enforced at review): "better", "best", "worse", "recommend", "should
use", "ideal for", "wins", "beats", "outperforms", "suited to X over Y", any comparative across
models. Allowed: "in your usage", "tended to", "most often", "leaned toward", "looked like".
Each card describes ONE model in isolation — no cross-model sentence.

---

## C. Schema additions (additive only — no breaking change)

All new fields are OPTIONAL and default to a zero/empty value; every v1 field is untouched.
A consumer reading v1-only fields is unaffected. Version marker added at top level so the UI
can feature-detect:

```jsonc
{
  // ...ALL existing v1 top-level fields unchanged...
  "schema_version": 2,          // NEW. absent/1 => v1 data; UI hides COLLECT-only v2 cards.
  "rows": [
    {
      // ...ALL existing row fields unchanged...
      "main": {
        // ...ALL existing main fields unchanged...
        "stop_reasons": { "end_turn": 30, "tool_use": 12, "none": 2 }, // A9. {}=default; null stop_reason -> "none"
        "thinking_messages": 11,            // A10. int, default 0 (main assistant lines with >=1 thinking block)
        "text_chars": 48210,                // A11. int, default 0 (sum of text-block char COUNTS — never text)
        "text_blocks": 41,                  // A11. int, default 0
        "quick_follow_ups": 3,              // A8. int, default 0 (<45s after prev assistant)
        "short_quick_follow_ups": 1         // A8. int, default 0 (quick AND text len < 120)
      }
      // subagent block unchanged
    }
  ]
}
```

Collect-time rules for the new fields:
- `stop_reasons` (A9): on each kept MAIN assistant line, read `message.stop_reason`; if it is
  a non-empty string, `stop_reasons[val] += 1`. null/missing/non-string → key `"none"` — the
  line is never dropped for a missing stop_reason. Guard in the existing try/except; subagent
  lines excluded (main only for v2 today).
- `thinking_messages` (A10): during the existing content-block loop on a kept MAIN assistant
  line, if any block has `type=="thinking"`, increment once per line. Presence only — never
  read, measure, or store the thinking text (length is structurally biased: Fable/Opus CoT
  arrives empty).
- `text_chars` / `text_blocks` (A11): same content-block loop; for each `type=="text"` block
  with string `text`, `text_chars += len(text)`, `text_blocks += 1`. Integers only; the
  never-copy-conversation-text rule applies in full (no substrings/samples/hashes).
- `quick_follow_ups` / `short_quick_follow_ups` (A8): computed in the existing user-turn
  attribution pass. For each qualifying user turn, find the immediately preceding MAIN
  assistant line by file position; if `user.ts - prev_assistant.ts < 45000 ms`, increment
  `quick_follow_ups` on the ATTRIBUTED model's row. If additionally the flattened text length
  (already computed transiently for category classification — a length int, never stored text)
  is < 120, increment `short_quick_follow_ups`. Missing/unparseable ts on either side → skip
  (do not count). These attach to the same row the user turn is credited to.

All new fields are guarded so a bad line falls to the existing skip path. None can raise on
absent data (default 0 / {}). `turn_attribution`, counters, and every existing field keep
their exact v1 meaning.

RENDER-only metrics (A1–A7) add NOTHING to the schema — they are pure functions of v1 fields.
This is why they are P0 and shippable today with an app.js-only change.

---

## D. UI placement sketch

Order top→bottom (new sections marked ★):

1. Header + disclaimer (existing).
2. ★ **Suggested-use panel** (§B) — cards, one per model. Caveat block above the cards.
3. Overview cards (existing).
4. ★ **Interaction shape** row of stat cards (A1: msgs/turn, tools/turn, one-shot %) +
   ★ **verbosity** (A5) as one more card in the same grid. Median primary, mean muted.
5. ★ **Tool-mix fingerprint** (A2) — stacked horizontal bars, one per model. Highest-signal
   visual; give it prominence right after interaction shape.
6. Comparison table (existing) — ADD new rows in a new "Shape (per-row ratios, median)"
   section: msgs/turn, tools/turn, verbosity, subagent output share (A3), cache reuse (A4).
   These slot into the existing table renderer as new TABLE_METRICS entries with a `.get`
   that returns the per-row ratio and the zero-guard filter already applied by the existing
   `.filter(v => !NaN)` path — set undefined ratios to NaN so they drop out cleanly.
7. ★ **Category × model heatmap** (A6) — table with row/col normalization toggle.
8. Tokens-over-time chart (existing).
9. Tool usage bars (existing).
10. ★ (if schema_version>=2) **stop_reason** mini-bars (A9), **thinking frequency** (A10),
    **text chars per text block** (A11), **follow-up cadence** (A8) — grouped in a
    "Message patterns" section near the bottom, each with its soft-signal caveat. Hidden
    entirely when data is v1.

Feature detection: A8–A11 sections render only if `DATA.schema_version >= 2` AND the field is
present on rows; otherwise the section is omitted (no empty shells, no errors on v1 data.json).

---

## E. REJECTS (with one-line reason)

- **Error-recovery rate (tool error → successful retry of same tool)** — REJECT for v1/v2.
  Requires ordered per-tool-name success/failure sequencing across the tool_use/tool_result
  join; the collector deliberately resolves errors order-independently and stores only counts.
  Real signal but a genuine new collector subsystem — out of scope for a same-day ship.
- **Thinking LENGTH / thinking token share** — REJECT (census-empirical). Fable/Opus return
  EMPTY thinking text (CoT omitted by the API), so length is structurally biased against
  CoT-redacted models. Thinking block PRESENCE was census-verified and is PROMOTED to P1 (A10).
- **Parallelism (≥2 tool_use per message)** — REJECT (census-empirical, demoted from P2).
  Measured at 0.03% of assistant messages (1/2,963) — no signal to compare. See A12.
- **Interruption / user-interrupt markers** — REJECT (census-empirical). Census attempt at
  regex-detecting interrupt markers in message structure produced mostly FALSE POSITIVES —
  no reliable marker exists. A guessed marker would produce a fake "frustration" number —
  worse than omitting it. A8 quick-follow-up is the honest, verifiable stand-in.
- **Pooled msgs/turn (sum msgs / sum turns)** — REJECT as the headline; one megasession
  dominates. Per-row median (A1) is the honest aggregation. (Pooling stays reserved for the
  tool-error rate only, where it is already justified.)
- **"Efficiency" / cost-per-outcome framing on cache** — REJECT the framing (keep the raw
  ratio as A4 "context reuse"). "Efficiency" implies better/worse; banned by §7.

---

## F. Implementation priority (same-day ship)

**P0 — ship today (app.js only, zero collector change, pure functions of v1 data.json):**
- A1 interaction shape (msgs/turn, tools/turn, one-shot rate)
- A2 tool-mix fingerprint (the flagship visual)
- A3 delegation propensity (subagent output share, subagent-active rate)
- A5 verbosity (output tokens / assistant message)
- A6 category × model heatmap
- A7 suggested-use panel with §B binding wording + caveats
- Table rows for the above ratios; §B/§D wording review gate.

**P1 — same day if time, else fast follow (small collect.py additions, one re-run):**
- A9 stop_reason distribution (cheapest COLLECT — census-confirmed field on every line;
  "none" bucketing rule)
- A10 thinking block frequency (census-verified extractable; presence only, never length)
- A11 text chars per text block (census-verified 5× spread; integers only, never text)
- A8 follow-up cadence (reuses attribution pass; label "cadence not sentiment")
- A4 cache reuse (RENDER but low signal-per-pixel; place low)

All P1 COLLECT items ride the SAME single collect.py re-run. Census numbers used to justify
them are from a 32-file sample — directional only; the re-run computes exact values.

**P2 — skip today:**
- (empty after census — parallelism was demoted to REJECT: 0.03% incidence, no signal)
- Error-recovery, thinking LENGTH, interruption, parallelism — REJECTED above, not deferred.

Ship rule: P0 is a single app.js change plus new sections in index.html; no data.json
regen required, so it cannot break the existing pipeline. Gate P0 behind the §B wording
review. P1 rides one additive collect.py re-run guarded by `schema_version: 2` so a stale
v1 data.json degrades gracefully (COLLECT-only cards simply hide).
