# METRIC-RULES.md — Track A binding metric specification (Phase 1)

Status: BINDING. `collect.py` (Phase 2) implements this file exactly. Ambiguity escalates
to Lead; the implementer does not reinterpret rules. All rules below were verified against
the live `~/.claude/projects` tree on 2026-07-05 (read-only). Where this file conflicts with
SCHEMA-NOTES.md, this file wins — SCHEMA-NOTES got the session-identity headline wrong (see
§2) and its findings were re-checked here.

---

## 0. Terminology and the file model (read first)

Two physically distinct kinds of transcript file exist under `~/.claude/projects/<project>/`:

- **TOP-LEVEL file** — `~/.claude/projects/<project>/<uuid>.jsonl`. **607** of these (2026-07-05).
  Verified: the file's basename (minus `.jsonl`) equals the `sessionId` inside every one of its
  lines in **100%** of cases (607/607 match, 0 mismatch, 0 missing). This is the **main session**.
- **NESTED SUBAGENT file** — `~/.claude/projects/<project>/<sessionId>/subagents/**/agent-*.jsonl`
  (either directly under `subagents/` or under `subagents/workflows/wf_*/`). **~3,101** of these.
  Verified: the `<sessionId>` **directory name** equals the parent session's id AND equals the
  `sessionId` written inside the nested file's lines (12/12 sampled, 0 mismatch). The nested
  file's *basename* is an agent id (`agent-<hash>`), NOT a session id. Every sampled nested file
  carried `isSidechain:true` on its lines and its own `message.model` on assistant lines.
- **JOURNAL file** — `.../subagents/**/journal.jsonl` (~113). Types are only `started`/`result`;
  **no `message`, no `usage`, no `model`.** Pure workflow metadata. **SKIPPED entirely.**

**Session counting unit = the TOP-LEVEL file.** A subagent file attaches to its parent session
via the path component immediately BEFORE `/subagents/`: split the file's absolute path at
`/subagents/`, take the last component of the left part. Never derive it via `dirname` of the
file — workflow-nested files (`subagents/workflows/wf_*/agent-*.jsonl`) sit deeper, and a naive
`dirname` returns `wf_*`, silently orphaning them.

### Walk / dispatch algorithm the collector MUST use

```
for each project dir under --root:
    for each *.jsonl directly in the project dir:      -> classify as TOP-LEVEL, session_id = basename
    for each */subagents/**/agent-*.jsonl:             -> classify as NESTED SUBAGENT,
                                                            parent_session_id = last path component
                                                            before "/subagents/" (split rule, §0)
    ignore  */subagents/**/journal.jsonl                -> SKIP (metadata)
```

Grouping is by `session_id` (top-level) / `parent_session_id` (nested). Because top-level
basenames are exact session ids and nested basenames are agent ids, a naive
"group by filename" would wrongly fragment sessions — so we group by the derived id above,
NOT by filename and NOT by the `sessionId` field found inside nested lines being treated as a
new session. A nested file NEVER creates its own session row; it only contributes SUBAGENT
counters to its parent session.

### Per-line skip rules (all files)

Skip (increment `lines_skipped`) any line that: fails `json.loads`; is not a dict; has
`type` not in {`user`,`assistant`}; is an assistant line whose `message.model` is `<synthetic>`,
`null`, empty, or NOT A STRING. ALL per-line processing is wrapped in try/except — ANY
exception while processing a line (malformed usage values, unhashable tool_use fields,
wrong-typed anything) skips that line and increments `lines_skipped`; a bad line never
aborts a file. Numeric usage fields: coerce via int() inside the guard; non-coercible →
treat that field as 0 (do not lose the line's other data if only one field is bad — but a
raised exception anywhere still falls back to skip-line).

**Orphaned nested files** (a `<sessionId>/subagents/` tree with NO matching top-level
`<sessionId>.jsonl`): skipped entirely — a nested file never creates a session row. Count
them in a `files_nested_orphaned` counter in data.json.

**Duplicate ids:** duplicate `uuid` values within a file (observed: 683 in one real file)
— when resolving `parentUuid` references, prefer the nearest matching line AT OR AFTER the
referencing line in file order; deterministic, never dict-last-writer. Duplicate
`tool_use.id` within a file: first occurrence in file order wins the join; count
collisions in the run summary (stdout only, not data.json). Verified:
0 malformed JSON lines across the tree; `<synthetic>` = 0.26% of assistant lines (152/58,373 in
top-level), empty model = 0% in top-level files.

---

## 1. Model normalization map

Applied to every raw `message.model` string. Collect **all** models; never drop a real one.

| raw id                          | display label |
|---------------------------------|---------------|
| `claude-fable-5`                | `Fable 5`     |
| `claude-opus-4-8`               | `Opus 4.8`    |
| `claude-sonnet-5`               | `Sonnet 5`    |
| `claude-sonnet-4-6`             | `Sonnet 4.6`  |
| `claude-haiku-4-5-*` (prefix)   | `Haiku 4.5`   |
| anything else (e.g. `claude-opus-4-7`, `claude-opus-4-6`) | the raw id, verbatim |
| `<synthetic>` / null / empty    | (line skipped — never produces a row) |

Match `claude-haiku-4-5-*` by prefix (`claude-haiku-4-5-20251001` observed). Dashboard **defaults
the visible set to Fable 5 / Opus 4.8 / Sonnet 5**; all other collected models are present in
data.json and toggle-able. Verified live model census: opus-4-8, fable-5, sonnet-4-6, sonnet-5,
haiku-4-5-20251001, plus rare opus-4-7 / opus-4-6.

---

## 2. What SCHEMA-NOTES got wrong / confirmed (do not re-litigate)

- **WRONG (overridden):** "filename ≠ sessionId ~85%; group by sessionId not filename." The 85%
  mismatch came from mixing in nested `agent-*.jsonl` files. For the **607 top-level files the
  match is 100%.** Counting unit is the top-level file (§0).
- **Confirmed:** parentUuid chain is continuous and usable for user-turn attribution (§ user turns).
- **Confirmed:** `is_error` absent OR false = success; `is_error:true` = error (§ tool errors).
  Live sample: absent=1463, false=701, true=77, null=0 — treat only `true` as an error.
- **Confirmed:** zero malformed lines; still wrap every line in try/except (files are live-appended).
- **Confirmed w/ correction:** `<synthetic>`/missing-model is rare (0.26%, not 0.08%) — skip it.
- **Confirmed:** usage keys stable May–July (`input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens` all present on every usage dict).
- **Confirmed:** journal/summary lines carry no usage → no double-count. `journal.jsonl` skipped.

---

## 3. Subagent policy (critical)

Verified facts driving this policy:
1. In the **current 607 top-level files there are ZERO inline `isSidechain:true` lines.** All
   subagent activity lives in separate nested `agent-*.jsonl` files. **Therefore no
   inline-vs-nested coexistence and NO double-count risk in this dataset.**
2. Nested files carry their own `message.model` (a Haiku subagent inside an Opus session shows
   `claude-haiku-4-5-*`), their own `usage`, and both user- and assistant-role lines.

**Policy:**

- **Attribution by the subagent's OWN `message.model`.** A Haiku subagent inside an Opus session
  counts as Haiku usage, in a Haiku (session, model) sub-row of that parent session — NOT as Opus.
- Subagent assistant lines contribute to **SUBAGENT counters only** (`subagent_messages`,
  `subagent_output_tokens`, etc.), never to the session's **main** counters.
- **Subagent user-role lines NEVER count as user turns** (they are tool plumbing / injected
  prompts). They are excluded everywhere from `user_turns`.
- **Main vs subagent is separately reported** in data.json: a `(session, model)` row carries
  BOTH a `main` block and a `subagent` block (see §6 schema) so the two are always distinguishable.
- **Inline-sidechain fallback (older files):** if a *top-level* file is ever encountered with an
  inline `isSidechain:true` line, that line is routed to the SUBAGENT block of the matching
  `(session, its own model)` row and excluded from main counters and from user turns — identical
  treatment to a nested line. **Dedup guard:** the two sources never describe the same physical
  line (nested lines live only in nested files; inline lines only in top-level files), so simply
  processing every line exactly once — each line from exactly one file — cannot double-count.
  No cross-file matching is needed or attempted.

---

## 4. Row semantics — one row per (session, model)

- Emit **one row per distinct (session_id, model)** pair. A single top-level session with two
  assistant models yields two rows; each subagent model adds its own `subagent` contribution to
  the row for that model (creating the row if that model had no main-chain lines).
- **User-turn attribution via TRANSITIVE parentUuid chain-walk** (amended after Phase 2
  measurement: direct one-hop user→assistant matches occur in only ~0.2% of turns — intermediate
  line types (`attachment`, `system`, `last-prompt`, `custom-title`, `mode`, ...) sit between the
  user line and its assistant reply in the chain): from the qualifying user line's `uuid`, follow
  the chain forward — find the line whose `parentUuid` == current uuid. If it is an ASSISTANT
  line: credit the user turn to that assistant's `message.model` row, done. If it is any
  non-user, non-assistant type: continue the walk from that line's uuid. If it is another USER
  line, the walk exceeds 50 hops, or the chain dead-ends: fall back to the nearest following
  assistant line in file order; if no assistant line follows at all (dangling last turn), drop
  the turn (do not guess).
  **A given user turn is credited to exactly ONE model row — never duplicated.**
  The collector MUST log the fallback ratio (turns attributed via chain vs via fallback vs
  dropped) in its run summary. **Measured baseline (2026-07-05): fallback ≈ 20%, dominated
  (83%) by QUEUED user messages** — user sends prompt B before prompt A is answered, so B's
  chain hits a user line. Lead-reviewed and ACCEPTED: for queued prompts the fallback resolves
  to the same nearest-following assistant that a through-user walk would reach, so attribution
  numbers are unaffected; only the chain/fallback label differs. Escalate to Lead only if
  fallback materially exceeds this ~20% baseline (say >30%) — that would indicate a new,
  undiagnosed cause.
- **Multi-model sessions appear in multiple "last X" cohorts.** A session with Opus + Fable rows
  is counted once under Opus's "last 25" and once under Fable's "last 25". The UI must state this
  explicitly ("a session with N models appears in N model columns").

---

## 5. Metric rules table

Source line legend: **A** = assistant top-level line, **U** = user top-level line,
**SA** = subagent line (nested `agent-*.jsonl`, any role), **all** = any kept line.
"main" = top-level / non-sidechain; "sub" = subagent block.

| metric | source line(s) | include | exclude | attribution rule | test fixture |
|---|---|---|---|---|---|
| **sessions** | top-level file | one per top-level `<uuid>.jsonl` that yields ≥1 kept line | nested files; journal.jsonl; files with only skipped lines | session id = top-level basename; a session spans exactly one top-level file | `single_message_session.jsonl` |
| **user turns** | U (main only) | exact predicate: `(type=="user") AND (message.role=="user") AND (isSidechain != true) AND (isMeta != true) AND has_real_text`, where `has_real_text` = content is a non-empty string, OR content is a list containing ≥1 block of `type=="text"` and ZERO blocks of `type=="tool_result"` | any line whose content list contains a `tool_result` block (even mixed with text); `isSidechain==true`; subagent user lines; `isMeta==true` | credited to the model of the assistant whose `parentUuid`==user.uuid (fallback + logging rule in §4); exactly one row | `multi_model_session.jsonl`, `sidechain_user_line.jsonl` |
| **assistant messages** (main) | A | one per kept assistant top-level line | subagent assistant lines; skipped-model lines | that line's own `message.model` row | `multi_model_session.jsonl` |
| **output_tokens** (main) | A `message.usage.output_tokens` | sum over kept main assistant lines | subagent lines | own model row | `cache_token_separation.jsonl` |
| **input_tokens** (main, "fresh") | A `message.usage.input_tokens` | sum; **kept separate — NEVER add cache into this** | cache_read / cache_creation | own model row | `cache_token_separation.jsonl` |
| **cache_read_tokens** (main) | A `message.usage.cache_read_input_tokens` | sum; separate field | — | own model row | `cache_token_separation.jsonl` |
| **cache_creation_tokens** (main) | A `message.usage.cache_creation_input_tokens` | sum; separate field | — | own model row | `cache_token_separation.jsonl` |
| **tool calls by name** | A content blocks `type==tool_use` | count per `name`; UI shows top 10 + `other` (aggregation is UI-side; collector stores full `{name:count}` map) | tool_use inside subagent lines counted under sub block, not main | issuing assistant line's model | `tool_calls_and_error.jsonl` |
| **tool errors** (main) | U content block `type==tool_result` with `is_error==true` | count only when `is_error===true` | `is_error` absent / false / null = success | join `tool_result.tool_use_id` → the `tool_use.id` in an assistant line of the SAME file → that assistant's model row | `tool_calls_and_error.jsonl` |
| **subagent tool_calls / tool_errors** | SA lines, same block types | same rules as main tool calls/errors, applied WITHIN each nested file (join never crosses files) | main-chain lines | issuing subagent assistant line's own model, into that model's `subagent` block | `subagent_nested.jsonl`, `subagent_tool_error.jsonl` |
| **subagent_messages** | SA assistant lines | one per kept subagent assistant line | subagent user lines (never messages) | subagent line's OWN `message.model`, in parent session's row for that model | `subagent_nested.jsonl` |
| **subagent_output_tokens** / **subagent_input_tokens** / **subagent_cache_read_tokens** / **subagent_cache_creation_tokens** | SA `message.usage.*` | sum over subagent assistant lines, four kinds separate (same rule as main) | main-chain lines | subagent line's own model | `subagent_nested.jsonl` |
| **duration_active_ms** | A + U `timestamp` (main only) | sum of gaps between consecutive main messages in this (session,model), each gap **capped at 300000 ms (5 min)** | idle gaps > 5 min counted as 5 min; subagent lines excluded from main duration | span computed over this model's main messages only (see §5a) | `multi_model_session.jsonl`, `single_message_session.jsonl`, `missing_timestamp.jsonl` |
| **project label** | first `all` line with `cwd` | `os.path.basename(cwd)` only | full path — NEVER store the absolute path | session-level (not per model); if no line has `cwd`, label = `"unknown"` | `missing_cwd.jsonl` |
| **task category** | first qualifying user turn text (main) | one label ∈ {build-feature, debug-fix, writing-content, research-analysis, config-tooling, other} | never store the prompt text itself | session-level; labeled by Scout/heuristic from the FIRST user prompt only (§5b) | `task_category.jsonl` |

### 5a. Duration rule (decided)

**Active duration, per-message-gap capped at 5 minutes.** For a given `(session, model)` row,
take that model's main messages (assistant + attributed user turns) in timestamp order, sum
`min(next.ts - prev.ts, 300000)` across consecutive pairs. Rationale: raw `last − first` is
garbage for sessions left open overnight; the 5-min cap converts "walked away" gaps into a bounded
constant. A single-message row → duration 0. Lines with missing/unparseable `timestamp` are
dropped from the duration computation only (they still count for tokens/messages). Subagent
lines are excluded from main duration; the dashboard does not report a separate subagent duration
in v1.

### 5b. Task category labeling rule

Session-level, from the FIRST main user turn only. Heuristic keyword mapping the collector applies
(no LLM call in v1; the Scout may hand-correct later):

Matching is CASE-INSENSITIVE substring on the lowercased prompt. Categories are checked in
the order below, first category with any keyword hit wins. `debug-fix` is checked FIRST so
"fix the build" lands in debug-fix, not build-feature. Known rough edge: substring matching
misfires on prompts mixing intents ("build a bug tracker") — accepted for v1, Scout may
hand-correct labels later.

- `debug-fix` — fix/bug/error/broken/crash/fail/debug/why isn't/not working/stack trace.
- `build-feature` — build/add/implement/create/make/feature/component/site/page/refactor.
- `writing-content` — write/draft/copy/blog/email/content/marketing/story/post.
- `research-analysis` — research/analy/compare/investigate/find out/explain/summarize/review.
- `config-tooling` — config/setup/install/CI/deploy/launch.json/settings/env/permission/hook.
- `other` — anything unmatched, or session with no user turn.

Store the **label only**, never the prompt. First-match wins in the order above.

---

## 6. data.json output schema (exact)

```jsonc
{
  "generated_at": "2026-07-05T12:34:56Z",   // string, ISO-8601 UTC, collector run time
  "top_level_files_seen": 607,                // int, ALL top-level files encountered
  "files_with_data": 605,                     // int, top-level files that produced ≥1 kept line
  "files_nested_scanned": 3101,               // int, nested subagent files processed
  "lines_skipped": 1234,                      // int, lines dropped (parse fail / non user|assistant / synthetic|empty model)
  "turn_attribution": { "chain": 4100, "fallback": 12, "dropped": 3 },  // §4 logging rule
  "models_seen": ["Opus 4.8","Fable 5","Sonnet 5","Sonnet 4.6","Haiku 4.5","claude-opus-4-7"],
  "rows": [
    {
      "session_id": "046cb1ac-...-49e41e",   // string, top-level basename
      "model": "Opus 4.8",                     // string, normalized display label
      "project": "Creative",                   // string, basename(cwd) only, or "unknown"
      "task_category": "build-feature",        // string enum (§5b)
      "start_ts": "2026-07-01T09:00:00Z",     // string ISO, earliest ts for this (session,model): main lines if any, ELSE this model's subagent lines — never null when any line has a parseable ts
      "end_ts": "2026-07-01T09:41:00Z",       // string ISO, latest ts, same main-else-subagent rule
      "duration_active_ms": 2460000,           // int, capped-gap active duration (§5a)
      "main": {
        "assistant_messages": 42,              // int
        "user_turns": 15,                      // int, attributed to THIS model only
        "output_tokens": 83120,                // int
        "input_tokens": 5120,                  // int, fresh only — cache NEVER added
        "cache_read_tokens": 990000,           // int
        "cache_creation_tokens": 44000,        // int
        "tool_calls": { "Read": 30, "Edit": 12, "Bash": 8 },  // {name:int}
        "tool_errors": 3                       // int (is_error===true joined via tool_use.id)
      },
      "subagent": {
        "messages": 60,                        // int, subagent assistant lines with THIS model
        "output_tokens": 120000,               // int
        "input_tokens": 8000,                  // int
        "cache_read_tokens": 400000,           // int
        "cache_creation_tokens": 22000,        // int
        "tool_calls": { "Read": 15 },          // {name:int}
        "tool_errors": 1                        // int
      }
    }
    // ...one object per (session, model)
  ]
}
```

Field rules: every integer defaults to `0`, never null. `tool_calls` defaults to `{}`.
`start_ts`/`end_ts` use main-line timestamps when the row has main lines, otherwise this
model's subagent-line timestamps (subagent-only rows MUST carry real dates — a Haiku
subagent-only row with null dates would vanish from every date filter and time chart).
Null only if no line of the row had a parseable timestamp. `duration_active_ms` stays
main-only (0 for subagent-only rows). `project` is `"unknown"` if no line carried `cwd`.
A row with subagent activity but no main-chain lines for that model still emits (its `main`
block is all zeros) — fixture: `subagent_only_model_row.jsonl`. No absolute paths, no `cwd` full string,
no conversation text anywhere in the file.

---

## 7. Framing constraint (binding on the UI too)

This tool is **descriptive, not causal.** Usage differences reflect routing, task mix, and user
habits — NOT model capability. **No "better" / "worse" / "wins" / "beats" language anywhere in
data.json field names, collector output, or the dashboard.** Track A answers "how is each model
used," never "which model is good." A visible disclaimer to this effect is required on the Usage
tab (Phase 3 checklist enforces it).

---

## 8. Open questions for the user

None. Every rule above is decided from verified data. Two low-risk assumptions are recorded here
for transparency, both safe to proceed on:

1. Task-category labeling is keyword-heuristic in v1 (no LLM). The Scout may refine labels in a
   later pass; the schema field is stable either way.
2. The 5-minute active-duration cap is a chosen convention (PLAN's recommendation), not derived
   from data. If the user later wants a different cap, it is a one-constant change in collect.py.
