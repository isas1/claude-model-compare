# Model Compare — Implementation Plan (v2, two tracks)

Two questions, two tracks, one dashboard:

- **Track A — Usage patterns.** How is each model actually used? (descriptive, from
  existing transcripts)
- **Track B — Quality comparison.** Same task → Fable 5 / Opus 4.8 / Sonnet 5,
  blind-judged. (the only honest way to ask "is Fable better, and at what?")

Track A runs first — its task-category breakdown decides which task types Track B
benchmarks. Zero-dependency throughout: Python 3 stdlib / Node stdlib + vanilla JS,
same style as the other dashboards in `Documents/Claude/Creative`.

This plan is written for an agent team to execute. Read the whole file before starting.

```
Track A:  jsonl lines -> parse/skip -> event normalize -> (session, model) aggregate -> data.json -> UI
Track B:  task suite  -> run per model (headless)      -> blind judge -> results.json -> UI
```

---

## 1. Verified facts (do not re-research)

- Data source: `~/.claude/projects/*/*.jsonl` — 606 transcript files across 81 project
  dirs (as of 2026-07-05).
- `"type":"assistant"` lines carry `message.model` (exact ID), `message.usage`
  (input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens),
  top-level ISO `timestamp`, plus `sessionId`, `cwd`, `gitBranch`, `isSidechain`,
  `parentUuid`.
- Inventory: Opus 4.8 = 442 sessions, Sonnet 4.6 = 67, Fable 5 = 46, Sonnet 5 = 26.
  (Session counting caveat: see Phase 0 item 8.)
- **Reuse:** `Creative/agent-insights/analyze.mjs` already walks
  `~/.claude/projects/**/*.jsonl`, streams line-by-line, handles the directory layout.
  Start the Track A collector from that skeleton — do not write a walker from scratch.
- claude.ai web chats are OUT OF SCOPE — no local files, no API.
- One verified sample only: schema facts above come from ONE current-version line.
  Older files (May, Sonnet 4.6 era) may differ. Phase 0 exists to close this gap.

## 2. Deliverables

```
fable-tools/model-compare/
├── PLAN.md              (this file)
├── SCHEMA-NOTES.md      (Phase 0 output)
├── METRIC-RULES.md      (Phase 1 output — the rules table, see §5)
├── collect.py           (Track A collector -> data.json)
├── data.json            (generated)
├── bench/
│   ├── REDDIT-SCOUT.md  (user-provided input — community claims to test; optional)
│   ├── tasks/           (task-NN.md prompt files + rubric per task)
│   ├── run_bench.py     (runs tasks per model, headless claude CLI)
│   ├── judge.py         (blind judging -> results.json)
│   └── results.json     (generated)
├── index.html           (dashboard: Usage tab + Quality tab)
├── app.js
└── tests/
    ├── test_collect.py  (stdlib unittest)
    └── fixtures/        (hand-made .jsonl files)
```

Run: `python3 collect.py && python3 -m http.server 8850`. Add `model-compare`
launch.json entry, port 8850.

## 3. Team

| Role | Model | Tasks |
|---|---|---|
| Lead | Opus | Phase 1 spec sign-off, Track B task/rubric design, judging QA, acceptance |
| Implementer | Sonnet 5 | collector, dashboard, bench harness, tests |
| Scout | Haiku | Phase 0 recon, task-category labeling, sample surveys |

Rules: Haiku never writes production code. Sonnet 5 never changes the spec — ambiguity
escalates to Opus. Opus writes code only if Sonnet 5 is blocked twice on same task.

## 4. Track A — Usage patterns

### Phase 0 — Schema recon (Haiku, read-only)

Survey ~30 transcripts spread across projects AND dates (must include several May-era
files). Write SCHEMA-NOTES.md answering:

1. All distinct line `type` values; which carry `usage`.
2. Frequency of `<synthetic>` / missing `message.model` — confirm skip rule.
3. `isSidechain: true` lines — own model + usage? Do sidechains contain user-role lines?
4. Mid-session model switch — what does it look like? Is `parentUuid` chain usable to
   attribute user lines to the following assistant's model?
5. Tool calls (`tool_use` in assistant content) and tool errors (`tool_result`,
   `is_error: true`, in user lines) — confirm `tool_use.id` join is possible.
6. Malformed/truncated lines observed (collector must skip, not crash).
7. Summary/compact entries — any usage that would double-count?
8. **Session identity:** does resuming a session create a new file? Same sessionId in
   two files? Forked sessions? Determines the counting unit — highest-risk unknown.
9. Old-version differences: do May files have `isMeta`, `iterations`, same usage keys?

Constraints: read-only; describe structure, never paste conversation content.

### Phase 1 — Metric Rules table (Opus)

Review SCHEMA-NOTES.md, then write METRIC-RULES.md: one row per metric with columns
**metric | source line | include | exclude | attribution rule | test fixture**.
No Track A code before this table exists. Metrics to rule on:

- sessions (define counting unit per Phase 0 item 8)
- user turns — exact predicate: user-role, string/text content, not tool_result, not
  meta/slash-command, `isSidechain != true`. Attribution in multi-model sessions: via
  parentUuid chain if usable, else nearest following assistant model. Never counted in
  more than one model row.
- assistant messages; tokens (output / fresh input / cache_read / cache_creation —
  never sum cache into input)
- tool calls by name (top 10 + "other"); tool errors — attributed via `tool_use.id`
  join to the issuing assistant message's model
- sidechain message count (separate metric, own model attribution)
- duration — decide idle-gap rule (recommend: sum inter-message gaps capped at 5 min;
  raw last−first is garbage for sessions left open). Per-model row in multi-model
  session: span of that model's messages only.
- project label — **basename of cwd only**, never full path
- task category — Haiku labels each session from its FIRST user prompt only, one of:
  build-feature / debug-fix / writing-content / research-analysis / config-tooling /
  other. Label, don't quote.

Model handling: collect ALL models; normalization map raw ID → display label
(claude-fable-5→"Fable 5", claude-opus-4-8→"Opus 4.8", claude-sonnet-5→"Sonnet 5",
claude-sonnet-4-6→"Sonnet 4.6", unknown→raw ID). Dashboard defaults to the 3 target
models, toggle for rest.

Multi-model sessions: one row per (session, model); may appear in multiple "last X"
cohorts — state this in UI. Spec must state: descriptive, not causal; no "better"
language anywhere in the UI.

### Phase 2 — Collector + tests (Sonnet 5)

`collect.py`, stdlib only, port the walker pattern from agent-insights/analyze.mjs:

- `--root` flag (default `~/.claude/projects`) for testability.
- Stream lines, try/except per line, count skips.
- Implement METRIC-RULES.md exactly. Emit data.json:
  `{ generated_at, files_scanned, lines_skipped, sessions: [...] }`.
- Under ~60s for 606 files. No caching in v1.

Tests (stdlib unittest, hand-made fixtures): empty file, malformed line, synthetic
model, multi-model session (user-turn attribution!), sidechain lines incl. sidechain
user lines, tool error via id-join, two tool calls one error, cache token separation,
single-message session (duration 0), missing timestamp, missing sessionId, unknown
model, **subagent-only model row (must carry real dates)**, **workflow-nested subagent
path (subagents/workflows/wf_*/)**, **subagent tool error (join within nested file)**.
Done when tests pass AND real-run counts ≥ §1 inventory for the 3 target models.

### Phase 3 — Dashboard, Usage tab (Sonnet 5)

`index.html` + `app.js`, vanilla, fetch data.json. Four views, nothing more:

1. Overview cards per model: sessions, median output tokens/session, median active
   duration, median user turns.
2. Comparison table: models × metrics (mean + median), "last X per model" selector
   (10/25/50/all), date-range filter, task-category filter.
3. Tokens-over-time chart (inline SVG, color per model).
4. Tool usage: top tools per model, horizontal bars.

Descriptive-not-causal disclaimer visible. Dark theme. No console errors.

### Phase 4 — QA + acceptance (Sonnet 5 executes, Opus reviews)

Hand-check one Fable, one Opus, one Sonnet 5, AND one multi-model session — manually
sum that session's jsonl tokens/turns, must match dashboard exactly.

Opus checklist:
- [ ] Hand-checked numbers match, including the multi-model session
- [ ] User turns never double-counted across model rows
- [ ] Sidechain user lines excluded from user turns
- [ ] Tool errors attributed via id-join
- [ ] Cache tokens separate from input
- [ ] Malformed-line fixture passes; real run reports skip count
- [ ] No full paths in data.json
- [ ] Disclaimer present; no causal claims in copy
- [ ] Zero deps (`grep -ri "cdn\|http.*://" index.html app.js` clean)

## 5. Track B — Quality comparison (after Track A acceptance)

Honest framing, embed in UI: 10 tasks = structured anecdote, not a benchmark. Blind
judging removes identity bias, not judge subjectivity. Single run per task ignores
variance. Still far better than routing-confounded usage stats for "what is Fable
actually better at."

### Phase 5 — Task suite (Opus designs, Haiku drafts candidates)

Two task sources, ~10 tasks total:

- **~5 from real usage:** top task categories from Track A's distribution, 1–2 tasks
  per category. Haiku drafts candidates inspired by real session categories (never
  copying real prompts verbatim — privacy).
- **~5 from community demand:** the user runs a Reddit scout (r/ClaudeAI etc.) and
  drops results into `bench/REDDIT-SCOUT.md` — a ranked table of model-comparison
  claims with testability ratings. Opus converts the top TESTABLE claims into tasks.
  If REDDIT-SCOUT.md is absent or thin at Phase 5 start, fill the gap from Track A
  categories instead — do not block, do not scout Reddit yourself.

All tasks regardless of source must be: self-contained (prompt + any fixture files in
the task dir), completable headless in <10 min, with a written rubric: 3–5 criteria,
1–5 scale each, criteria specific to the task ("handles the empty-file edge case"),
not generic ("good code"). Reddit-derived tasks additionally record the source claim
they test, so the Quality tab can show "community claim: confirmed / refuted / mixed".
Opus selects, tightens, writes all rubrics. Reject drama-only claims (pricing rants,
vague "nerfed" posts with no testable behavior).

### Phase 6 — Run harness (Sonnet 5)

`bench/run_bench.py`:

- For each task × model (`claude-fable-5`, `claude-opus-4-8`, `claude-sonnet-5`):
  run `claude -p --model <id> --output-format json` in an isolated scratch dir seeded
  with the task's fixture files. Capture: final output, files produced, wall time,
  token usage from the JSON result.
- One run per task×model in v1. Timeout 15 min, record timeouts as failures.
- Store raw outputs under `bench/runs/<task>/<anon-key>/` where anon-key is a random
  letter assigned per task (mapping kept in a separate file the judge never reads).

### Phase 7 — Blind judging (Sonnet 5 builds, Opus QAs)

`bench/judge.py`:

- Judge = `claude -p --model claude-opus-4-8` (judging is Opus-tier work). Judge
  receives: task prompt, rubric, outputs labeled A/B/C in randomized order. NEVER
  model names. Prompt must instruct: score each criterion 1–5 with one-line reason,
  no overall winner declaration.
- Cross-judge check: 3 of 10 tasks also judged by `claude-fable-5` blind. If the two
  judges' rankings disagree on >1 of 3, flag whole judging pass for human review.
- De-anonymize only after all scores recorded → results.json:
  `{ task, category, model, criterion_scores, wall_time, tokens, judge_flags }`.

### Phase 8 — Quality tab + final acceptance (Sonnet 5, Opus reviews)

Dashboard Quality tab: per-category score grid (models × categories, mean rubric
score), per-task drill-down with criterion scores and judge reasons, wall-time and
token cost per task alongside quality (quality-per-token is the interesting ratio).
For Reddit-derived tasks, show the source claim with a confirmed/refuted/mixed badge
based on scores.

Opus final checklist:
- [ ] Judge inputs verifiably contain no model identity (inspect actual judge prompts)
- [ ] Randomized order actually randomized per task (check mapping file)
- [ ] Cross-judge agreement reported in UI
- [ ] "Structured anecdote" caveat visible on Quality tab
- [ ] Timeouts/failures shown, not silently dropped

## 6. Hard constraints (all agents)

- Read-only on `~/.claude/projects` — never write, move, delete transcripts.
- Zero runtime deps. Stdlib + vanilla JS. No CDN, no build step.
- All new files inside `fable-tools/model-compare/`. Bench runs write only to
  `bench/runs/` scratch dirs.
- Privacy: metrics and labels only — never copy conversation text into data.json,
  docs, code, or task prompts.
- Track B spends real API tokens (~30 headless runs + judging). Get explicit user OK
  before Phase 6 executes.
- Don't overbuild. Resist features not listed here.

## 7. Sequence and gates

Phase 0 → 1 → **USER GATE (spec review)** → 2 → 3 → 4 → **USER GATE (Track A
acceptance + Track B cost OK)** → 5 → 6 → 7 → 8 → **USER GATE (final)**.

### Adversarial review gates (mandatory)

Track record of this project: every artifact so far (recon, spec) shipped with real
defects that the author's tier did not prevent and only independent review caught.
Therefore: after EACH code phase (2, 3, 6, 7), a FRESH-CONTEXT reviewer — an agent that
did not write the code, or an external reviewer (Codex) — adversarially reviews the
diff against METRIC-RULES.md / PLAN.md before the next phase starts. Reviewer's brief:
try to find inputs that produce wrong numbers; check every spec rule has a matching
code path and test. Must-fix findings get fixed and re-reviewed before proceeding.
Self-review by the implementer does not satisfy this gate.

Kickoff prompt: "Read fable-tools/model-compare/PLAN.md and execute phase by phase
with the specified model per role. Stop at each USER GATE."
