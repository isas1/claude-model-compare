#!/usr/bin/env python3
"""
collect.py — Track A collector for model-compare.

Walks ~/.claude/projects (or --root), streams every .jsonl transcript file
line-by-line, and aggregates usage metrics per (session, model) row into
data.json, exactly per METRIC-RULES.md (binding spec — see that file for the
rationale behind every rule implemented here).

Python 3 stdlib ONLY. Read-only on the transcript tree: this script never
opens a transcript file in write/append mode.

Usage:
    python3 collect.py [--root PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants / lookup tables (METRIC-RULES.md §1, §5a, §5b)
# ---------------------------------------------------------------------------

MODEL_MAP = {
    "claude-fable-5": "Fable 5",
    "claude-opus-4-8": "Opus 4.8",
    "claude-sonnet-5": "Sonnet 5",
    "claude-sonnet-4-6": "Sonnet 4.6",
}
HAIKU_PREFIX = "claude-haiku-4-5-"
HAIKU_LABEL = "Haiku 4.5"

DURATION_GAP_CAP_MS = 300_000  # 5 minutes (§5a)

# Task category keyword lists, in priority order (§5b). debug-fix checked
# first. First category with any keyword hit (case-insensitive substring) wins.
TASK_CATEGORY_RULES = [
    ("debug-fix", [
        "fix", "bug", "error", "broken", "crash", "fail", "debug",
        "why isn't", "not working", "stack trace",
    ]),
    ("build-feature", [
        "build", "add", "implement", "create", "make", "feature",
        "component", "site", "page", "refactor",
    ]),
    ("writing-content", [
        "write", "draft", "copy", "blog", "email", "content", "marketing",
        "story", "post",
    ]),
    ("research-analysis", [
        "research", "analy", "compare", "investigate", "find out",
        "explain", "summarize", "review",
    ]),
    ("config-tooling", [
        "config", "setup", "install", "ci", "deploy", "launch.json",
        "settings", "env", "permission", "hook",
    ]),
]
DEFAULT_TASK_CATEGORY = "other"


def normalize_model(raw):
    """Map a raw message.model string to its display label.

    Returns None for <synthetic> / null / empty — caller must skip the line
    (these never produce a row). Any other unrecognized id is returned
    verbatim (§1: "anything else ... the raw id, verbatim").
    """
    if not raw:
        return None
    if raw == "<synthetic>":
        return None
    if raw in MODEL_MAP:
        return MODEL_MAP[raw]
    if raw.startswith(HAIKU_PREFIX):
        return HAIKU_LABEL
    return raw


def classify_task_category(text):
    """§5b: case-insensitive substring match, debug-fix checked first,
    first category with any keyword hit wins."""
    lowered = text.lower()
    for category, keywords in TASK_CATEGORY_RULES:
        for kw in keywords:
            if kw in lowered:
                return category
    return DEFAULT_TASK_CATEGORY


def parse_ts(raw):
    """Parse an ISO-8601 timestamp string to a float epoch-ms value.
    Returns None if missing or unparseable (never raises)."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000.0
    except (ValueError, TypeError):
        return None


def ms_to_iso(ms):
    if ms is None:
        return None
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def has_real_text(content):
    """§5 user-turn predicate helper: content is a non-empty string, OR a
    list containing >=1 text block and ZERO tool_result blocks."""
    if isinstance(content, str):
        return len(content) > 0
    if isinstance(content, list):
        has_text = False
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_result":
                return False
            if btype == "text" and isinstance(block.get("text"), str) and block.get("text"):
                has_text = True
        return has_text
    return False


def is_qualifying_user_turn(line):
    """Exact predicate from METRIC-RULES.md §5 user-turns row:
    (type=="user") AND (message.role=="user") AND (isSidechain != true)
    AND (isMeta != true) AND has_real_text(content)."""
    if line.get("type") != "user":
        return False
    msg = line.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    if line.get("isSidechain") is True:
        return False
    if line.get("isMeta") is True:
        return False
    return has_real_text(msg.get("content"))


def extract_texts(content):
    """Best-effort flatten of a user message's content to text, for task
    category classification only. Never stored in data.json — label only."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return ""


def empty_main_block():
    return {
        "assistant_messages": 0,
        "user_turns": 0,
        "output_tokens": 0,
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "tool_calls": {},
        "tool_errors": 0,
    }


def empty_subagent_block():
    return {
        "messages": 0,
        "output_tokens": 0,
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "tool_calls": {},
        "tool_errors": 0,
    }


class RowState:
    """Mutable accumulation state for one (session_id, model) row."""

    __slots__ = (
        "session_id", "model", "project", "task_category",
        "start_ms", "end_ms", "main", "subagent", "main_events",
    )

    def __init__(self, session_id, model):
        self.session_id = session_id
        self.model = model
        self.project = None
        self.task_category = None
        self.start_ms = None
        self.end_ms = None
        self.main = empty_main_block()
        self.subagent = empty_subagent_block()
        self.main_events = []  # list of ts_ms for main-only duration calc

    def touch_ts(self, ts_ms):
        if ts_ms is None:
            return
        if self.start_ms is None or ts_ms < self.start_ms:
            self.start_ms = ts_ms
        if self.end_ms is None or ts_ms > self.end_ms:
            self.end_ms = ts_ms


def get_or_create_row(rows, session_id, model):
    key = (session_id, model)
    row = rows.get(key)
    if row is None:
        row = RowState(session_id, model)
        rows[key] = row
    return row


class Counters:
    def __init__(self):
        self.top_level_files_seen = 0
        self.files_with_data = 0
        self.files_nested_scanned = 0
        self.lines_skipped = 0
        self.chain = 0
        self.fallback = 0
        self.dropped = 0
        self.models_seen = set()


# ---------------------------------------------------------------------------
# Directory walk (METRIC-RULES.md §0)
# ---------------------------------------------------------------------------

def iter_project_dirs(root):
    try:
        entries = os.scandir(root)
    except OSError:
        return
    for e in entries:
        if e.is_dir(follow_symlinks=False):
            yield e.path


def iter_top_level_files(project_dir):
    """*.jsonl directly in the project dir (not in subdirectories)."""
    try:
        entries = os.scandir(project_dir)
    except OSError:
        return
    for e in entries:
        if e.is_file() and e.name.endswith(".jsonl"):
            yield e.path


def iter_nested_agent_files(project_dir):
    """Recursively walk */subagents/** under project_dir, yielding
    (path, parent_session_id, is_journal) for every .jsonl found.

    parent_session_id is derived per METRIC-RULES.md §0: split the file's
    absolute path at "/subagents/", take the last path component of the left
    part. This is NEVER dirname-based, so workflow-nested files
    (subagents/workflows/wf_*/agent-*.jsonl) attribute correctly — a naive
    dirname() would return "wf_*" and silently orphan them.
    """
    marker = "subagents" + os.sep
    for dirpath, _dirnames, filenames in os.walk(project_dir):
        rel = os.path.relpath(dirpath, project_dir)
        if rel == "." or "subagents" not in rel.split(os.sep):
            continue
        for fname in filenames:
            if not fname.endswith(".jsonl"):
                continue
            full = os.path.join(dirpath, fname)
            split_marker = os.sep + "subagents" + os.sep
            if split_marker not in full:
                continue
            left = full.split(split_marker, 1)[0]
            parent_session_id = os.path.basename(left)
            is_journal = fname == "journal.jsonl"
            yield full, parent_session_id, is_journal


# ---------------------------------------------------------------------------
# Top-level (main session) file processing
# ---------------------------------------------------------------------------

def process_top_level_file(path, rows, counters):
    """Process one top-level session file. Returns True if it produced >=1
    kept line (counts toward files_with_data).

    The file is streamed once, line by line. Per-line side effects that don't
    need lookahead (token/tool_call/tool_error accumulation) are applied
    immediately. Qualifying user turns and assistant lines are additionally
    appended, in file order, to a small in-memory `events` list, and a
    parentUuid->child map is built across ALL parsed lines, so that a second
    pass can resolve user-turn attribution (TRANSITIVE parentUuid chain-walk
    per amended §4, else nearest FOLLOWING assistant line in file order, else
    drop) without re-reading the file. Neither structure holds line content —
    only ids/types/timestamps — so this does not defeat the "stream, don't
    load whole file" constraint.
    """
    session_id = os.path.basename(path)
    if session_id.endswith(".jsonl"):
        session_id = session_id[: -len(".jsonl")]

    produced_data = False
    project = None
    first_user_text = None
    first_user_seen = False

    # tool_use.id -> ("main"|"subagent", model); join within this file only.
    tool_use_model = {}

    # File-order event list for the attribution pass:
    #   ("assistant", parentUuid, uuid, model, ts_ms)
    #   ("user_turn", None, uuid, None, ts_ms)
    events = []

    # parentUuid -> child-line info for the TRANSITIVE chain-walk (§4,
    # amended). Recorded for EVERY parsed line regardless of type, because
    # the chain threads through skipped types (attachment, system,
    # last-prompt, custom-title, mode, ...). First child in file order wins
    # (transcripts are append-only; the chain is linear in practice).
    # Value: (type, uuid, main_assistant_model_or_None)
    parent_to_child = {}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                counters.lines_skipped += 1
                continue
            if not isinstance(line, dict):
                counters.lines_skipped += 1
                continue

            ltype = line.get("type")

            # Chain-walk bookkeeping happens BEFORE any type skip: skipped
            # line types still carry the uuid/parentUuid links the walk must
            # traverse.
            _puid = line.get("parentUuid")
            if _puid and _puid not in parent_to_child:
                _walk_model = None
                if ltype == "assistant" and line.get("isSidechain") is not True:
                    _wmsg = line.get("message")
                    if isinstance(_wmsg, dict):
                        _walk_model = normalize_model(_wmsg.get("model"))
                parent_to_child[_puid] = (ltype, line.get("uuid"), _walk_model)

            if ltype not in ("user", "assistant"):
                counters.lines_skipped += 1
                continue

            if project is None and isinstance(line.get("cwd"), str) and line.get("cwd"):
                project = os.path.basename(line["cwd"].rstrip("/"))

            ts_ms = parse_ts(line.get("timestamp"))

            if ltype == "assistant":
                msg = line.get("message")
                if not isinstance(msg, dict):
                    counters.lines_skipped += 1
                    continue
                model = normalize_model(msg.get("model"))
                if model is None:
                    counters.lines_skipped += 1
                    continue

                counters.models_seen.add(model)
                is_sidechain = line.get("isSidechain") is True
                row = get_or_create_row(rows, session_id, model)
                if project:
                    row.project = project
                produced_data = True

                content = msg.get("content")
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}

                scope = "subagent" if is_sidechain else "main"
                block = row.subagent if is_sidechain else row.main
                if scope == "main":
                    block["assistant_messages"] += 1
                else:
                    block["messages"] += 1
                block["output_tokens"] += int(usage.get("output_tokens") or 0)
                block["input_tokens"] += int(usage.get("input_tokens") or 0)
                block["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
                block["cache_creation_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            name = c.get("name") or "unknown"
                            block["tool_calls"][name] = block["tool_calls"].get(name, 0) + 1
                            tid = c.get("id")
                            if tid:
                                tool_use_model[tid] = (scope, model)

                row.touch_ts(ts_ms)
                if scope == "main" and ts_ms is not None:
                    row.main_events.append(ts_ms)

                if not is_sidechain:
                    events.append(("assistant", line.get("parentUuid"), line.get("uuid"), model, ts_ms))
                # Inline sidechain assistant lines (§3 fallback path) do not
                # participate in user-turn attribution and are never main.

            else:  # ltype == "user"
                msg = line.get("message")
                if not isinstance(msg, dict):
                    counters.lines_skipped += 1
                    continue

                # tool_result / is_error join — applies to any user line
                # (join within this file only), independent of whether the
                # line also qualifies as a user turn.
                content = msg.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error") is True:
                            tid = c.get("tool_use_id")
                            info = tool_use_model.get(tid) if tid else None
                            if info:
                                scope, tmodel = info
                                target_row = get_or_create_row(rows, session_id, tmodel)
                                if scope == "main":
                                    target_row.main["tool_errors"] += 1
                                else:
                                    target_row.subagent["tool_errors"] += 1

                if is_qualifying_user_turn(line):
                    produced_data = True
                    if not first_user_seen:
                        first_user_seen = True
                        first_user_text = extract_texts(content)
                    events.append(("user_turn", None, line.get("uuid"), None, ts_ms))

    # --- Pass 2: user-turn attribution (transitive chain-walk, §4 amended) ---
    for idx, ev in enumerate(events):
        if ev[0] != "user_turn":
            continue
        _, _, user_uuid, _, ts_ms = ev
        attributed_model = None
        method = None

        if user_uuid:
            # TRANSITIVE chain-walk: follow parentUuid links forward through
            # any non-user, non-assistant line types. Stop with credit on an
            # assistant line; stop and fall back on hitting another USER
            # line, exceeding 50 hops, or a dead-end. Inline-sidechain
            # assistant lines (walk_model None) are treated as intermediates
            # — §3 excludes them from user-turn attribution everywhere.
            cur = user_uuid
            for _hop in range(50):
                child = parent_to_child.get(cur)
                if child is None:
                    break  # dead-end -> fallback
                ctype, cuuid, cmodel = child
                if ctype == "assistant" and cmodel is not None:
                    attributed_model = cmodel
                    method = "chain"
                    break
                if ctype == "user":
                    break  # hit another user line -> fallback
                if not cuuid:
                    break  # unlinked intermediate -> dead-end -> fallback
                cur = cuuid

        if attributed_model is None:
            # Fallback: nearest FOLLOWING assistant line in file order.
            for j in range(idx + 1, len(events)):
                if events[j][0] == "assistant":
                    attributed_model = events[j][3]
                    method = "fallback"
                    break

        if attributed_model is None:
            # Dangling last turn — no assistant line after it at all. Drop.
            counters.dropped += 1
            continue

        target_row = get_or_create_row(rows, session_id, attributed_model)
        target_row.main["user_turns"] += 1
        target_row.touch_ts(ts_ms)
        if ts_ms is not None:
            target_row.main_events.append(ts_ms)
        if method == "chain":
            counters.chain += 1
        else:
            counters.fallback += 1

    # Task category: from first qualifying user turn's text only (§5b).
    category = classify_task_category(first_user_text or "") if first_user_seen else DEFAULT_TASK_CATEGORY

    # Apply project + task_category to every row created for this session
    # (session-level fields, not per-model).
    for (sid, _model), row in rows.items():
        if sid != session_id:
            continue
        if row.project is None:
            row.project = project if project else "unknown"
        row.task_category = category

    return produced_data


# ---------------------------------------------------------------------------
# Nested subagent file processing
# ---------------------------------------------------------------------------

def process_nested_file(path, parent_session_id, rows, counters):
    """Process one nested subagent .jsonl file. All contributions go to the
    SUBAGENT block of (parent_session_id, this line's own model). The
    tool_use.id join happens WITHIN this file only — never crosses files."""
    tool_use_model = {}  # tool_use.id -> model, local to this nested file

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                counters.lines_skipped += 1
                continue
            if not isinstance(line, dict):
                counters.lines_skipped += 1
                continue

            ltype = line.get("type")
            if ltype not in ("user", "assistant"):
                counters.lines_skipped += 1
                continue

            ts_ms = parse_ts(line.get("timestamp"))

            if ltype == "assistant":
                msg = line.get("message")
                if not isinstance(msg, dict):
                    counters.lines_skipped += 1
                    continue
                model = normalize_model(msg.get("model"))
                if model is None:
                    counters.lines_skipped += 1
                    continue
                counters.models_seen.add(model)

                row = get_or_create_row(rows, parent_session_id, model)
                # Subagent-only rows MUST carry real dates from subagent
                # timestamps (never null when timestamps exist) — §6.
                row.touch_ts(ts_ms)

                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                block = row.subagent
                block["messages"] += 1
                block["output_tokens"] += int(usage.get("output_tokens") or 0)
                block["input_tokens"] += int(usage.get("input_tokens") or 0)
                block["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
                block["cache_creation_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)

                content = msg.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            name = c.get("name") or "unknown"
                            block["tool_calls"][name] = block["tool_calls"].get(name, 0) + 1
                            tid = c.get("id")
                            if tid:
                                tool_use_model[tid] = model
                # Subagent user-role lines never count as messages/turns —
                # nothing further to do for them below except the tool_result
                # join, handled in the else branch.

            else:  # user line in nested file — tool_result / is_error join only
                msg = line.get("message")
                if not isinstance(msg, dict):
                    counters.lines_skipped += 1
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error") is True:
                            tid = c.get("tool_use_id")
                            model = tool_use_model.get(tid) if tid else None
                            if model:
                                row = get_or_create_row(rows, parent_session_id, model)
                                row.subagent["tool_errors"] += 1


# ---------------------------------------------------------------------------
# Duration + row-dict assembly
# ---------------------------------------------------------------------------

def compute_duration_ms(main_events_ts_sorted):
    """§5a: sum of min(gap, 300000ms) across consecutive main-message
    timestamps in order. A single-message row -> duration 0."""
    if len(main_events_ts_sorted) < 2:
        return 0
    total = 0.0
    prev = main_events_ts_sorted[0]
    for ts in main_events_ts_sorted[1:]:
        gap = ts - prev
        if gap < 0:
            gap = 0
        total += min(gap, DURATION_GAP_CAP_MS)
        prev = ts
    return int(round(total))


def build_row_dict(row):
    main_events_sorted = sorted(row.main_events)
    duration_ms = compute_duration_ms(main_events_sorted)
    return {
        "session_id": row.session_id,
        "model": row.model,
        "project": row.project or "unknown",
        "task_category": row.task_category or DEFAULT_TASK_CATEGORY,
        "start_ts": ms_to_iso(row.start_ms),
        "end_ts": ms_to_iso(row.end_ms),
        "duration_active_ms": duration_ms,
        "main": row.main,
        "subagent": row.subagent,
    }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def collect(root):
    """Walk root, process all top-level and nested files, return
    (rows dict keyed by (session_id, model) -> RowState, Counters)."""
    rows = {}
    counters = Counters()

    for project_dir in iter_project_dirs(root):
        # Top-level files first so project/task_category are set on the row
        # before any nested file for the same session creates a
        # subagent-only row for a different model.
        for path in iter_top_level_files(project_dir):
            counters.top_level_files_seen += 1
            produced = process_top_level_file(path, rows, counters)
            if produced:
                counters.files_with_data += 1

        for path, parent_session_id, is_journal in iter_nested_agent_files(project_dir):
            if is_journal:
                continue
            if not os.path.basename(path).startswith("agent-"):
                continue
            counters.files_nested_scanned += 1
            process_nested_file(path, parent_session_id, rows, counters)

    return rows, counters


def build_data(rows, counters):
    row_dicts = [build_row_dict(r) for r in rows.values()]
    row_dicts.sort(key=lambda r: (r["session_id"], r["model"]))

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_level_files_seen": counters.top_level_files_seen,
        "files_with_data": counters.files_with_data,
        "files_nested_scanned": counters.files_nested_scanned,
        "lines_skipped": counters.lines_skipped,
        "turn_attribution": {
            "chain": counters.chain,
            "fallback": counters.fallback,
            "dropped": counters.dropped,
        },
        "models_seen": sorted(counters.models_seen),
        "rows": row_dicts,
    }


def print_summary(data, elapsed_s):
    print(f"model-compare collect.py — run summary ({elapsed_s:.1f}s)")
    print(f"  top-level files seen:    {data['top_level_files_seen']}")
    print(f"  top-level files w/ data: {data['files_with_data']}")
    print(f"  nested files scanned:    {data['files_nested_scanned']}")
    print(f"  lines skipped:           {data['lines_skipped']}")
    ta = data["turn_attribution"]
    total_ta = ta["chain"] + ta["fallback"] + ta["dropped"]
    fallback_pct = (ta["fallback"] / total_ta * 100) if total_ta else 0.0
    print(f"  turn attribution: chain={ta['chain']} fallback={ta['fallback']} "
          f"dropped={ta['dropped']} (fallback={fallback_pct:.2f}%)")
    if fallback_pct > 5.0:
        print("  WARNING: fallback ratio exceeds 5% — escalate to Lead before trusting attribution.")
    print(f"  models seen: {', '.join(data['models_seen'])}")

    per_model_sessions = {}
    per_model_rows = {}
    for row in data["rows"]:
        per_model_sessions.setdefault(row["model"], set()).add(row["session_id"])
        per_model_rows[row["model"]] = per_model_rows.get(row["model"], 0) + 1
    print("  per-model row counts (sessions / rows):")
    for model in sorted(per_model_sessions, key=lambda m: -len(per_model_sessions[m])):
        print(f"    {model}: {len(per_model_sessions[model])} sessions, {per_model_rows[model]} rows")


def main():
    parser = argparse.ArgumentParser(description="Track A collector for model-compare.")
    parser.add_argument("--root", default=os.path.expanduser("~/.claude/projects"),
                         help="Root directory to scan (default: ~/.claude/projects)")
    parser.add_argument("--out", default="./data.json",
                         help="Output path for data.json (default: ./data.json)")
    args = parser.parse_args()

    start = time.time()
    rows, counters = collect(args.root)
    data = build_data(rows, counters)
    elapsed = time.time() - start

    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print_summary(data, elapsed)
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
