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

# §4 (amended): measured fallback baseline is ~20% (dominated by queued user
# messages, Lead-reviewed and accepted). Escalate only when fallback
# materially exceeds that baseline (>30%).
FALLBACK_WARN_PCT = 30.0

# (source key in message.usage, output key in our blocks)
USAGE_KEYS = (
    ("output_tokens", "output_tokens"),
    ("input_tokens", "input_tokens"),
    ("cache_read_input_tokens", "cache_read_tokens"),
    ("cache_creation_input_tokens", "cache_creation_tokens"),
)
BLOCK_TOKEN_KEYS = ("output_tokens", "input_tokens",
                     "cache_read_tokens", "cache_creation_tokens")

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


class SkipLine(Exception):
    """Raised during per-line parsing when the line must be skipped
    (counted in lines_skipped) per §0 skip rules / crash hardening."""


def normalize_model(raw):
    """Map a raw message.model string to its display label.

    Returns None (caller skips the line) for <synthetic> / null / empty /
    NOT A STRING (§0 amended). Any other unrecognized string id is returned
    verbatim (§1: "anything else ... the raw id, verbatim").
    """
    if not isinstance(raw, str):
        return None
    if not raw or raw == "<synthetic>":
        return None
    if raw in MODEL_MAP:
        return MODEL_MAP[raw]
    if raw.startswith(HAIKU_PREFIX):
        return HAIKU_LABEL
    return raw


def safe_int(v):
    """§0 (amended): numeric usage fields coerce via int(); a non-coercible
    value counts as 0 without losing the line's other data."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


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


def _check_hashable(value):
    """Raise SkipLine if value is unhashable (list/dict/...) — §0 amended
    crash-hardening rule for tool_use name/id and uuid fields."""
    try:
        hash(value)
    except TypeError:
        raise SkipLine()


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
    """Mutable accumulation state for one (session_id, model) row.

    Main-line and subagent-line timestamps are tracked SEPARATELY (§6:
    start_ts/end_ts use main-line timestamps when the row has main lines,
    subagent timestamps ONLY for subagent-only rows)."""

    __slots__ = (
        "session_id", "model", "project", "task_category",
        "main_start_ms", "main_end_ms", "sub_start_ms", "sub_end_ms",
        "main", "subagent", "main_events",
    )

    def __init__(self, session_id, model):
        self.session_id = session_id
        self.model = model
        self.project = None
        self.task_category = None
        self.main_start_ms = None
        self.main_end_ms = None
        self.sub_start_ms = None
        self.sub_end_ms = None
        self.main = empty_main_block()
        self.subagent = empty_subagent_block()
        self.main_events = []  # list of ts_ms for main-only duration calc

    def touch_main_ts(self, ts_ms):
        if ts_ms is None:
            return
        if self.main_start_ms is None or ts_ms < self.main_start_ms:
            self.main_start_ms = ts_ms
        if self.main_end_ms is None or ts_ms > self.main_end_ms:
            self.main_end_ms = ts_ms

    def touch_sub_ts(self, ts_ms):
        if ts_ms is None:
            return
        if self.sub_start_ms is None or ts_ms < self.sub_start_ms:
            self.sub_start_ms = ts_ms
        if self.sub_end_ms is None or ts_ms > self.sub_end_ms:
            self.sub_end_ms = ts_ms


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
        self.files_nested_orphaned = 0
        self.lines_skipped = 0
        self.chain = 0
        self.fallback = 0
        self.dropped = 0
        self.tool_id_collisions = 0
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
# Guarded per-line parsers (§0 amended crash hardening). Parsing is separated
# from applying so a skipped line never leaves partial mutations on a row.
# ---------------------------------------------------------------------------

def _parse_assistant_line(line):
    """Validate + extract everything needed from an assistant line.
    Returns (model, usage_dict keyed by our block keys, tool_uses list of
    (name, tid)) or raises SkipLine. Performs NO row mutation."""
    msg = line.get("message")
    if not isinstance(msg, dict):
        raise SkipLine()
    model = normalize_model(msg.get("model"))
    if model is None:
        raise SkipLine()

    usage_raw = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
    usage = {out_key: safe_int(usage_raw.get(src_key))
             for src_key, out_key in USAGE_KEYS}

    tool_uses = []
    content = msg.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                name = c.get("name")
                tid = c.get("id")
                _check_hashable(name)   # unhashable name/id -> skip line (§0)
                _check_hashable(tid)
                tool_uses.append((name or "unknown", tid))
    return model, usage, tool_uses


def _parse_user_error_results(line):
    """Extract the tool_use_ids of is_error:true tool_result blocks from a
    user line. Raises SkipLine on non-dict message or unhashable ids.
    Performs NO row mutation."""
    msg = line.get("message")
    if not isinstance(msg, dict):
        raise SkipLine()
    tids = []
    content = msg.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error") is True:
                tid = c.get("tool_use_id")
                _check_hashable(tid)
                if tid is not None:
                    tids.append(tid)
    return tids


# ---------------------------------------------------------------------------
# Top-level (main session) file processing
# ---------------------------------------------------------------------------

def process_top_level_file(path, rows, counters, session_meta=None):
    """Process one top-level session file. Returns True if it produced >=1
    kept line (counts toward files_with_data). Records the session's
    project / task_category into session_meta — session-level fields stamped
    onto ALL of the session's rows (including subagent-only rows created
    later from nested files) by the reconciliation pass in collect().

    The file is streamed once, line by line. Per-line parsing is guarded
    (§0 amended: any exception while processing a line skips that line and
    never aborts the file). User-turn attribution and the tool-error id-join
    are resolved AFTER the stream from small in-memory structures (ids,
    types, positions — never content), making both order-independent within
    the file.
    """
    session_id = os.path.basename(path)
    if session_id.endswith(".jsonl"):
        session_id = session_id[: -len(".jsonl")]

    produced_data = False
    project = None
    first_user_text = None
    first_user_seen = False

    # tool_use.id -> ("main"|"subagent", model); first occurrence in file
    # order wins (§0 amended); collisions counted for the run summary.
    tool_use_map = {}
    # tool_use_ids of is_error:true results; join resolved after the stream
    # so a result-before-use ordering still counts (§5 has no ordering
    # qualifier).
    pending_error_tids = []

    # File-order event list for the attribution pass:
    #   ("assistant", model, ts_ms)
    #   ("user_turn", uuid, ts_ms, pos)
    events = []

    # parentUuid -> ordered list of (pos, type, uuid, main_assistant_model)
    # for the TRANSITIVE chain-walk (§4 amended). Recorded for EVERY parsed
    # line regardless of type. ALL children are kept (never first-only /
    # last-writer-wins): duplicate uuids exist in real files (§0 amended)
    # and are resolved positionally — the walk takes the nearest child AT OR
    # AFTER the current position in file order.
    parent_to_children = {}

    pos = -1
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
            pos += 1

            try:
                ltype = line.get("type")

                # Chain-walk bookkeeping BEFORE any type skip: skipped line
                # types still carry the uuid/parentUuid links the walk must
                # traverse.
                puid = line.get("parentUuid")
                _check_hashable(puid)
                if puid:
                    walk_model = None
                    if ltype == "assistant" and line.get("isSidechain") is not True:
                        wmsg = line.get("message")
                        if isinstance(wmsg, dict):
                            walk_model = normalize_model(wmsg.get("model"))
                    parent_to_children.setdefault(puid, []).append(
                        (pos, ltype, line.get("uuid"), walk_model))

                if ltype not in ("user", "assistant"):
                    counters.lines_skipped += 1
                    continue

                if project is None and isinstance(line.get("cwd"), str) and line.get("cwd"):
                    project = os.path.basename(line["cwd"].rstrip("/"))

                ts_ms = parse_ts(line.get("timestamp"))

                if ltype == "assistant":
                    # Parse (guarded, no mutation) ...
                    model, usage, tool_uses = _parse_assistant_line(line)

                    # ... then apply (validated inputs; cannot raise).
                    counters.models_seen.add(model)
                    is_sidechain = line.get("isSidechain") is True
                    row = get_or_create_row(rows, session_id, model)
                    produced_data = True

                    scope = "subagent" if is_sidechain else "main"
                    block = row.subagent if is_sidechain else row.main
                    if scope == "main":
                        block["assistant_messages"] += 1
                    else:
                        block["messages"] += 1
                    for out_key in BLOCK_TOKEN_KEYS:
                        block[out_key] += usage[out_key]
                    for name, tid in tool_uses:
                        block["tool_calls"][name] = block["tool_calls"].get(name, 0) + 1
                        if tid is not None:
                            if tid in tool_use_map:
                                counters.tool_id_collisions += 1
                            else:
                                tool_use_map[tid] = (scope, model)

                    # §6 main-wins rule: inline-sidechain lines feed the
                    # SUBAGENT timestamp track, never main start/end.
                    if is_sidechain:
                        row.touch_sub_ts(ts_ms)
                    else:
                        row.touch_main_ts(ts_ms)
                        if ts_ms is not None:
                            row.main_events.append(ts_ms)
                        events.append(("assistant", model, ts_ms))
                    # Inline sidechain assistant lines (§3 fallback path) do
                    # not participate in user-turn attribution.

                else:  # ltype == "user"
                    # Guarded extraction; join deferred to end-of-file.
                    tids = _parse_user_error_results(line)
                    pending_error_tids.extend(tids)

                    if is_qualifying_user_turn(line):
                        produced_data = True
                        if not first_user_seen:
                            first_user_seen = True
                            first_user_text = extract_texts(line["message"].get("content"))
                        events.append(("user_turn", line.get("uuid"), ts_ms, pos))

            except SkipLine:
                counters.lines_skipped += 1
                continue
            except Exception:
                # §0 amended: ANY exception while processing a line skips
                # that line and increments lines_skipped; a bad line never
                # aborts a file.
                counters.lines_skipped += 1
                continue

    # --- Tool-error id-join (order-independent within this file, §5) ---
    for tid in pending_error_tids:
        info = tool_use_map.get(tid)
        if info:
            scope, tmodel = info
            target_row = get_or_create_row(rows, session_id, tmodel)
            if scope == "main":
                target_row.main["tool_errors"] += 1
            else:
                target_row.subagent["tool_errors"] += 1

    # --- User-turn attribution (transitive chain-walk, §4 amended) ---
    for idx, ev in enumerate(events):
        if ev[0] != "user_turn":
            continue
        _, user_uuid, ts_ms, user_pos = ev
        attributed_model = None
        method = None

        if user_uuid:
            # TRANSITIVE chain-walk: follow parentUuid links forward through
            # any non-user, non-assistant line types. Duplicate uuids (§0
            # amended) are resolved positionally: among all lines whose
            # parentUuid == current uuid, take the nearest one AT OR AFTER
            # the current position in file order — never dict-last-writer.
            # Stop with credit on an assistant line; stop and fall back on
            # hitting another USER line, exceeding 50 hops, or a dead-end.
            # Inline-sidechain / synthetic assistant lines (walk_model None)
            # are intermediates — §3/§1 exclude them from attribution.
            cur_uuid = user_uuid
            cur_pos = user_pos
            for _hop in range(50):
                child = None
                for cand in parent_to_children.get(cur_uuid, ()):
                    if cand[0] > cur_pos:
                        child = cand
                        break
                if child is None:
                    break  # dead-end (or nothing at/after) -> fallback
                cpos, ctype, cuuid, cmodel = child
                if ctype == "assistant" and cmodel is not None:
                    attributed_model = cmodel
                    method = "chain"
                    break
                if ctype == "user":
                    break  # hit another user line -> fallback
                if not cuuid:
                    break  # unlinked intermediate -> dead-end -> fallback
                cur_uuid = cuuid
                cur_pos = cpos

        if attributed_model is None:
            # Fallback: nearest FOLLOWING assistant line in file order.
            for j in range(idx + 1, len(events)):
                if events[j][0] == "assistant":
                    attributed_model = events[j][1]
                    method = "fallback"
                    break

        if attributed_model is None:
            # Dangling last turn — no assistant line after it at all. Drop.
            counters.dropped += 1
            continue

        target_row = get_or_create_row(rows, session_id, attributed_model)
        target_row.main["user_turns"] += 1
        target_row.touch_main_ts(ts_ms)
        if ts_ms is not None:
            target_row.main_events.append(ts_ms)
        if method == "chain":
            counters.chain += 1
        else:
            counters.fallback += 1

    # Session-level metadata (§5/§5b: project and task_category are
    # session-level, not per-model). Stamping happens in collect()'s
    # reconciliation pass, AFTER nested files may have created
    # subagent-only rows for this session.
    category = classify_task_category(first_user_text or "") if first_user_seen else DEFAULT_TASK_CATEGORY
    if session_meta is not None:
        session_meta[session_id] = {
            "project": project,
            "task_category": category,
        }

    return produced_data


# ---------------------------------------------------------------------------
# Nested subagent file processing
# ---------------------------------------------------------------------------

def process_nested_file(path, parent_session_id, rows, counters):
    """Process one nested subagent .jsonl file. All contributions go to the
    SUBAGENT block of (parent_session_id, this line's own model). The
    tool_use.id join happens WITHIN this file only (never crosses files) and
    is order-independent (resolved after the stream). Duplicate tool ids:
    first occurrence wins, collisions counted."""
    tool_use_map = {}       # tool_use.id -> model, local to this nested file
    pending_error_tids = []

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

            try:
                ltype = line.get("type")
                if ltype not in ("user", "assistant"):
                    counters.lines_skipped += 1
                    continue

                ts_ms = parse_ts(line.get("timestamp"))

                if ltype == "assistant":
                    model, usage, tool_uses = _parse_assistant_line(line)

                    counters.models_seen.add(model)
                    row = get_or_create_row(rows, parent_session_id, model)
                    # §6: subagent timestamps tracked separately — used for
                    # start_ts/end_ts ONLY when the row has no main lines.
                    row.touch_sub_ts(ts_ms)

                    block = row.subagent
                    block["messages"] += 1
                    for out_key in BLOCK_TOKEN_KEYS:
                        block[out_key] += usage[out_key]
                    for name, tid in tool_uses:
                        block["tool_calls"][name] = block["tool_calls"].get(name, 0) + 1
                        if tid is not None:
                            if tid in tool_use_map:
                                counters.tool_id_collisions += 1
                            else:
                                tool_use_map[tid] = model
                    # Subagent user-role lines never count as messages/turns.

                else:  # user line in nested file — error-result join only
                    tids = _parse_user_error_results(line)
                    pending_error_tids.extend(tids)

            except SkipLine:
                counters.lines_skipped += 1
                continue
            except Exception:
                counters.lines_skipped += 1
                continue

    # Order-independent join, within this nested file only (§5).
    for tid in pending_error_tids:
        model = tool_use_map.get(tid)
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
    # §6 main-wins rule: main-line timestamps when the row has main lines
    # with parseable timestamps, otherwise this model's subagent-line
    # timestamps. Null only if no line of the row had a parseable timestamp.
    if row.main_start_ms is not None:
        start_ms, end_ms = row.main_start_ms, row.main_end_ms
    else:
        start_ms, end_ms = row.sub_start_ms, row.sub_end_ms
    return {
        "session_id": row.session_id,
        "model": row.model,
        "project": row.project or "unknown",
        "task_category": row.task_category or DEFAULT_TASK_CATEGORY,
        "start_ts": ms_to_iso(start_ms),
        "end_ts": ms_to_iso(end_ms),
        "duration_active_ms": duration_ms,
        "main": row.main,
        "subagent": row.subagent,
    }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def collect(root):
    """Walk root, process all top-level and nested files, return
    (rows dict keyed by (session_id, model) -> RowState, Counters).

    Three phases:
      1. ALL top-level files (collecting the set of known session ids and
         session-level metadata).
      2. Nested subagent files. A nested tree whose parent session id has
         no top-level file is ORPHANED (§0 amended): skipped entirely,
         counted in files_nested_orphaned — a nested file never creates a
         session row.
      3. Session-level field reconciliation: stamp every row of a session
         with the session's project / task_category, so subagent-only rows
         created in phase 2 inherit them (§5/§5b session-level rule).
    """
    rows = {}
    counters = Counters()
    session_meta = {}
    known_sessions = set()

    project_dirs = list(iter_project_dirs(root))

    # Phase 1: all top-level files.
    for project_dir in project_dirs:
        for path in iter_top_level_files(project_dir):
            counters.top_level_files_seen += 1
            base = os.path.basename(path)
            if base.endswith(".jsonl"):
                base = base[: -len(".jsonl")]
            known_sessions.add(base)
            produced = process_top_level_file(path, rows, counters, session_meta)
            if produced:
                counters.files_with_data += 1

    # Phase 2: nested subagent files.
    for project_dir in project_dirs:
        for path, parent_session_id, is_journal in iter_nested_agent_files(project_dir):
            if is_journal:
                continue
            if not os.path.basename(path).startswith("agent-"):
                continue
            if parent_session_id not in known_sessions:
                counters.files_nested_orphaned += 1
                continue
            counters.files_nested_scanned += 1
            process_nested_file(path, parent_session_id, rows, counters)

    # Phase 3: session-level field reconciliation.
    for (sid, _model), row in rows.items():
        meta = session_meta.get(sid)
        if meta:
            row.project = meta["project"]
            row.task_category = meta["task_category"]

    return rows, counters


def build_data(rows, counters):
    row_dicts = [build_row_dict(r) for r in rows.values()]
    row_dicts.sort(key=lambda r: (r["session_id"], r["model"]))

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_level_files_seen": counters.top_level_files_seen,
        "files_with_data": counters.files_with_data,
        "files_nested_scanned": counters.files_nested_scanned,
        "files_nested_orphaned": counters.files_nested_orphaned,
        "lines_skipped": counters.lines_skipped,
        "turn_attribution": {
            "chain": counters.chain,
            "fallback": counters.fallback,
            "dropped": counters.dropped,
        },
        "models_seen": sorted(counters.models_seen),
        "rows": row_dicts,
    }


def print_summary(data, elapsed_s, tool_id_collisions=0):
    print(f"model-compare collect.py — run summary ({elapsed_s:.1f}s)")
    print(f"  top-level files seen:    {data['top_level_files_seen']}")
    print(f"  top-level files w/ data: {data['files_with_data']}")
    print(f"  nested files scanned:    {data['files_nested_scanned']}")
    print(f"  nested files orphaned:   {data['files_nested_orphaned']}")
    print(f"  lines skipped:           {data['lines_skipped']}")
    print(f"  duplicate tool_use.id collisions: {tool_id_collisions}")
    ta = data["turn_attribution"]
    total_ta = ta["chain"] + ta["fallback"] + ta["dropped"]
    fallback_pct = (ta["fallback"] / total_ta * 100) if total_ta else 0.0
    print(f"  turn attribution: chain={ta['chain']} fallback={ta['fallback']} "
          f"dropped={ta['dropped']} (fallback={fallback_pct:.2f}%)")
    if fallback_pct > FALLBACK_WARN_PCT:
        print(f"  WARNING: fallback ratio exceeds {FALLBACK_WARN_PCT:.0f}% — materially above "
              "the ~20% baseline accepted in METRIC-RULES.md §4 (queued user "
              "messages); escalate to Lead before trusting attribution.")
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

    print_summary(data, elapsed, tool_id_collisions=counters.tool_id_collisions)
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
