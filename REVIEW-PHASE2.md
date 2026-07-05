# REVIEW-PHASE2.md — Adversarial review of collect.py (Track A collector)

Reviewer: fresh-context adversarial gate (did not write this code).
Date: 2026-07-05. Method: rule-by-rule audit of METRIC-RULES.md §0–§6 against
collect.py; 11 hostile scratch fixtures run through `collect.py --root`; two
independent real-data metric recomputes; read-only audit; timed real run.
All real-data checks were read-only; no conversation text is quoted below.

---

## VERDICT: **fail** (one MUST-FIX that produces wrong numbers on real data)

The collector is well-structured and correct on the load-bearing metrics
(tokens, messages, tool calls/errors, user-turn attribution, subagent
aggregation, duration, timestamps). The 47-test suite passes and the real run
meets the PLAN §1 session-count acceptance bar. But one defect writes wrong
values into `data.json` for 25+ real sessions, so this must be fixed and
re-reviewed before Phase 3 builds on the data.

---

## MUST-FIX

### MF-1 — Subagent-only model rows get `project="unknown"` and `task_category="other"` even when the parent session's project/category are known

- **What:** A `(session, model)` row that exists only because of nested
  subagent lines (no main-chain lines for that model) never receives the
  session's `project` or `task_category`. It is emitted with
  `project="unknown"` and `task_category="other"` even though other rows of the
  **same session** carry the real project/category. The spec is explicit that
  both fields are **session-level, not per-model** (§5 "project label …
  session-level (not per model)"; §5b "Session-level"; §6 project is
  `"unknown"` only "if no line carried `cwd`" — here a line in the session did).
- **Where:** `collect.py`
  - `process_top_level_file` lines **514–522**: the project/task_category
    patch loop runs at the end of *each top-level file*, iterating only over
    rows that exist **at that moment**.
  - `collect()` lines **660–672**: for each project dir, top-level files are
    processed, then nested files. The subagent-only row is created inside
    `process_nested_file` (line **568**) **after** the parent's
    `process_top_level_file` already ran its patch loop — so the row never gets
    patched.
  - `process_nested_file` (lines 530–607) never sets `project` or
    `task_category`.
  - `build_row_dict` lines **636–637** then fall back to
    `"unknown"` / `"other"`.
  - The comment at line **657** ("Top-level files first so project/task_category
    are set on the row before any nested file … creates a subagent-only row")
    states the intended invariant, but that invariant does not hold: nested
    files are processed after the top-level patch loop has already completed.
- **Spec rule violated:** §5 (project attribution = session-level), §5b
  (task category = session-level), §6 (project `"unknown"` only when *no* line
  in the session carried `cwd`).
- **Reproduction (real data):** full run over `~/.claude/projects`,
  `data.json` — **25 sessions** have a subagent-only row labeled
  `project="unknown"` while another row of the same session has a real project;
  **19 sessions** likewise for `task_category`. Concrete example, session
  `046cb1ac-…`: Opus row `project="Creative", task_category="build-feature"`;
  Haiku subagent-only row (104 subagent messages) `project="unknown",
  task_category="other"`. Both should read `Creative` / `build-feature`.
- **Reproduction (minimal fixture):** scratch file `77777777-….jsonl` (main
  Opus line with `cwd=/x/projG`, prompt "spawn a subagent") + nested
  `…/subagents/workflows/wf_x/deeper/agent-deep.jsonl` (Haiku).
  Output: Opus row `project=projG`; Haiku subagent-only row `project=unknown`
  (expected `projG`), `task_category=other` (expected the session's category).
- **Impact:** These rows silently drop out of every project filter and
  task-category filter in the Phase 3 dashboard — the exact "row vanishes from a
  filter" failure the spec's subagent-date rule (§6) was written to prevent,
  reproduced here on a different field. Fix: reconcile project + task_category
  in a final pass over `rows` in `collect()` (group by `session_id`, take the
  session's known project/category and stamp every row of that session),
  after all top-level AND nested files are processed.

---

## SHOULD-FIX

### SF-1 — Duplicate `uuid` values collapse the chain-walk map and can misattribute user turns in multi-model sessions

- **What:** `parent_to_child` is keyed on `parentUuid` with "first child in file
  order wins" (line 362, `if _puid and _puid not in parent_to_child`). If two
  lines share a `uuid` (so two later lines share the same `parentUuid`), only
  the first is recorded; the chain-walk for the second user turn follows the
  wrong branch.
- **Where:** `collect.py` lines 361–368 (map build), 472–486 (walk).
- **Spec rule:** §4 transitive chain-walk assumes a linear, uniquely-keyed
  chain ("the chain is linear in practice"). That assumption is violated by real
  data.
- **Reproduction (fixture, demonstrated wrong number):** scratch file with two
  user turns sharing `uuid="dup"`, first replied to by Opus, second by Fable.
  Expected split Opus 1 / Fable 1. **Actual: Opus 2 / Fable 0.**
- **Real-data status:** duplicate uuids are NOT hypothetical — 3 of 120 sampled
  files contain them (one file: 683 duplicated *assistant* uuids + 351
  duplicated *user* uuids, and it is multi-model Opus+Sonnet 4.6). I recomputed
  that file's per-model user turns independently (nearest-following-assistant)
  and it happened to **match** collect.py exactly (Sonnet 4.6: 10, Opus 4.8:
  64) — the duplicated assistant uuids resolve to the same model as the
  positional fallback, so no wrong number is produced **today**. This is a
  latent correctness risk, not a current miscount; hence should-fix, not
  must-fix. Recommend documenting the assumption or de-duping by preferring the
  nearest-in-file-order child.

### SF-2 — Tool-error id-join is order-dependent; a `tool_result` appearing before its `tool_use` is silently dropped

- **What:** The `tool_use.id → tool_result` join is done during a single live
  stream: `tool_use_model[id]` is populated when the assistant line is read, and
  consulted when the user `tool_result` line is read (lines 415–416 populate,
  439–448 consume; nested: 588–589 / 602–607). If a `tool_result` with
  `is_error:true` precedes its `tool_use` in file order, the map is empty at
  join time and the error is not counted.
- **Where:** `collect.py` 433–448 (top-level), 594–607 (nested).
- **Spec rule:** §5 tool-errors: "join `tool_result.tool_use_id` → the
  `tool_use.id` in an assistant line of the SAME file" — no ordering qualifier.
- **Reproduction (fixture):** scratch file with the `is_error:true`
  `tool_result` line placed **before** its matching `tool_use` assistant line.
  Expected `tool_errors=1`; **actual `tool_errors=0`.**
- **Real-data status:** across all 607 top-level files, **0 of 870**
  error tool_results reference a not-yet-seen tool_use id — tool_use always
  precedes its result in practice. No wrong number today; latent robustness gap.
  Fix: two-pass (collect all tool_use ids in the file first) or defer the join.

### SF-3 — Fallback-ratio warning threshold (5%) contradicts the spec's accepted baseline (~20%)

- **What:** `print_summary` warns "fallback ratio exceeds 5% — escalate to
  Lead" (lines 708–709). The real run reports fallback = **19.65%**, tripping
  the warning on every normal run.
- **Where:** `collect.py` line 708.
- **Spec rule:** §4 (amended) sets the accepted baseline at **≈20%** and says
  escalate only if fallback **materially exceeds** it (">30%"). The 5% gate is
  a false alarm and will train the operator to ignore the warning — defeating
  the one signal that would catch a genuinely broken chain-walk.
- **Reproduction:** any full real run prints the WARNING despite behaving
  exactly per spec. Fix: raise the threshold to 30% to match §4.

---

## NITS

- **N-1 — `project` is read only from `user`/`assistant` lines, not "first
  `all` line with `cwd`" (spec §5).** cwd is read at line 374, after the
  non-user/assistant skip at line 370, so `attachment`/`system`/etc. lines that
  carry `cwd` are ignored for project derivation. cwd varies within a file in
  16/200 sampled files (worktree/`cd` switches); because only the basename is
  stored and cwd is usually stable, this virtually never changes the label, but
  it is a literal deviation from "first `all` line with `cwd`."
- **N-2 — `--out` default is a relative `./data.json`.** `main` resolves it via
  `os.path.abspath` (line 735) so it writes to the CWD, not under `--root`
  — safe. But if an operator runs `collect.py` with CWD inside `--root`, the
  output lands inside the scanned tree (still a *write outside the scan pass*,
  never a transcript mutation). Consider defaulting `--out` next to the script
  or refusing an `--out` path under `--root`.
- **N-3 — Missing spec-rule test coverage** (lower severity, all currently
  pass on real data): no test for (a) subagent-only row inheriting session
  project/category [would have caught MF-1]; (b) duplicate-uuid attribution
  [SF-1]; (c) tool_result-before-tool_use ordering [SF-2]; (d) deeply-nested
  `subagents/workflows/wf_*/deeper/agent-*.jsonl` (tests cover one workflow
  level, not two); (e) inline-sidechain lines in a *top-level* file (§3
  fallback path) — I verified this path works, but it is untested.

---

## WHAT I VERIFIED CLEAN (load-bearing for Phase 3)

- **Read-only discipline:** the only two transcript opens (lines 342, 536) are
  mode `"r"`; the sole write (line 736) targets `os.path.abspath(--out)`,
  outside the scan. No `os.remove/rename/mkdir/append` to the tree. Post-run,
  no transcript file under `~/.claude/projects` was modified by collect.py
  (the only newer files are this live Claude Code session's own transcript).
- **Performance:** full real run over 607 top-level + 3103 nested files =
  **8.2 s**, well under the 60 s budget.
- **Session-count acceptance (PLAN §1):** Opus 443 ≥ 442, Fable 47 ≥ 46,
  Sonnet 5 28 ≥ 26. Meets the "real-run counts ≥ inventory" gate.
- **Cross-check #1 (multi-model user-turn attribution, real session
  `276ba614-…`, Opus 4.8 + Sonnet 4.6, with 683 duplicated assistant uuids):**
  collect.py → Sonnet 4.6 user_turns=10, Opus 4.8 user_turns=64. Independent
  nearest-following-assistant recompute → identical (10 / 64). Chain-walk vs
  fallback split matches spec; no double-counting (chain+fallback+dropped
  reconcile).
- **Cross-check #2 (subagent tokens, workflow-nested session `da29d05b-…`,
  145 nested agent files under `subagents/workflows/wf_*/`):** collect.py →
  Opus 4.8 subagent messages=5942, output_tokens=1,505,265. Independent
  recompute (glob all `agent-*.jsonl` any depth, sum usage) → **identical**.
  The §0 split-at-`/subagents/` parent-id derivation and subagent aggregation
  are correct on real workflow-nested data.
- **§0 walk / dispatch:** top-level basename → session_id (verified with a
  file whose internal `sessionId` contradicts its filename and a file whose
  name is not a uuid — both correctly use the basename); nested parent id via
  split-at-`/subagents/` (workflow-nested `wf_*/deeper/` attributes to the
  session, never `wf_*`); `journal.jsonl` skipped; non-`agent-` nested names
  skipped (all 3103 real nested files are `agent-*`, 113 `journal`).
- **Per-line skips:** malformed JSON, non-dict, non-user/assistant types,
  `<synthetic>`/null/empty model — all counted as `lines_skipped`, never abort
  the file. Real run skipped 48,351 lines without error.
- **User-turn predicate (§5):** mixed text+tool_result content correctly
  **excluded**; `isSidechain`/`isMeta` excluded; string and text-list content
  accepted. Verified by fixture and unit tests.
- **Token separation (§5):** input / output / cache_read / cache_creation kept
  in four separate fields; cache never summed into input; missing usage keys
  default to 0 (fixture with `usage:{output_tokens:7}` only → input 0, output 7).
- **Tool-error id-join (in-order, same-file):** counts `is_error===true` only;
  cross-file `tool_use_id` correctly does NOT join (fixture 2: error referencing
  another file's tool id → tool_errors=0).
- **Subagent policy (§3):** subagent lines contribute to the subagent block of
  their OWN model; subagent user lines never counted as turns; inline-sidechain
  lines in a top-level file route to the subagent block and are excluded from
  user-turn attribution (verified with a top-level file carrying inline
  `isSidechain:true` user+assistant lines).
- **Duration (§5a):** per-message gaps capped at 300000 ms; out-of-order
  timestamps produce a non-negative gap (negative clamped to 0);
  unparseable/missing timestamps dropped from duration only (still count for
  tokens/messages); single-message row → 0.
- **Timestamps (§6):** 0 rows with null `start_ts` on the real run; subagent-
  only rows carry real dates from subagent-line timestamps.
- **Schema (§6):** all integer fields default 0 (never null), `tool_calls`
  defaults `{}`, no absolute paths anywhere in `data.json`, top-level and row
  key sets exactly match the spec.
