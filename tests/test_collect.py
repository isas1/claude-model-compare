#!/usr/bin/env python3
"""
tests/test_collect.py — stdlib unittest suite for collect.py.

Run: python3 -m unittest discover tests
(run from the model-compare/ directory, or point PYTHONPATH at it.)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import collect  # noqa: E402


FIXTURES_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "root1")


def run_collect():
    """Run the full collector once over the fixture tree and return
    (rows_by_key, counters). rows_by_key is {(session_id, model): dict}."""
    rows, counters = collect.collect(FIXTURES_ROOT)
    row_dicts = {(r.session_id, r.model): collect.build_row_dict(r) for r in rows.values()}
    return row_dicts, counters


class TestUnitFunctions(unittest.TestCase):
    """Pure-function unit tests, no file I/O."""

    def test_normalize_model_known(self):
        self.assertEqual(collect.normalize_model("claude-fable-5"), "Fable 5")
        self.assertEqual(collect.normalize_model("claude-opus-4-8"), "Opus 4.8")
        self.assertEqual(collect.normalize_model("claude-sonnet-5"), "Sonnet 5")
        self.assertEqual(collect.normalize_model("claude-sonnet-4-6"), "Sonnet 4.6")

    def test_normalize_model_haiku_prefix(self):
        self.assertEqual(collect.normalize_model("claude-haiku-4-5-20251001"), "Haiku 4.5")
        self.assertEqual(collect.normalize_model("claude-haiku-4-5-anything"), "Haiku 4.5")

    def test_normalize_model_unknown_verbatim(self):
        self.assertEqual(collect.normalize_model("claude-opus-4-7"), "claude-opus-4-7")
        self.assertEqual(collect.normalize_model("claude-opus-4-6"), "claude-opus-4-6")

    def test_normalize_model_synthetic_and_empty(self):
        self.assertIsNone(collect.normalize_model("<synthetic>"))
        self.assertIsNone(collect.normalize_model(None))
        self.assertIsNone(collect.normalize_model(""))

    def test_normalize_model_non_string_skipped(self):
        # §0 amended: model NOT A STRING -> skip (never AttributeError).
        self.assertIsNone(collect.normalize_model(123))
        self.assertIsNone(collect.normalize_model(["claude-opus-4-8"]))
        self.assertIsNone(collect.normalize_model({"model": "x"}))

    def test_safe_int_coercion(self):
        # §0 amended: non-coercible usage values count as 0, keep the line.
        self.assertEqual(collect.safe_int(5), 5)
        self.assertEqual(collect.safe_int("7"), 7)
        self.assertEqual(collect.safe_int("nope"), 0)
        self.assertEqual(collect.safe_int(None), 0)
        self.assertEqual(collect.safe_int([1]), 0)

    def test_fallback_warning_threshold_30_percent(self):
        # Review item 8: warn only above the 30% escalation threshold
        # (§4 amended baseline is ~20%), never at the accepted baseline.
        import io
        from contextlib import redirect_stdout

        def summary_output(chain, fallback):
            data = {
                "top_level_files_seen": 1, "files_with_data": 1,
                "files_nested_scanned": 0, "files_nested_orphaned": 0,
                "lines_skipped": 0,
                "turn_attribution": {"chain": chain, "fallback": fallback, "dropped": 0},
                "models_seen": [], "rows": [],
            }
            buf = io.StringIO()
            with redirect_stdout(buf):
                collect.print_summary(data, 0.0)
            return buf.getvalue()

        # 20% fallback (the accepted baseline) -> no warning
        self.assertNotIn("WARNING", summary_output(chain=80, fallback=20))
        # 25% -> still no warning (below 30%)
        self.assertNotIn("WARNING", summary_output(chain=75, fallback=25))
        # 35% -> warning fires, referencing the spec baseline
        out = summary_output(chain=65, fallback=35)
        self.assertIn("WARNING", out)
        self.assertIn("30%", out)
        self.assertIn("20%", out)

    def test_has_real_text_string(self):
        self.assertTrue(collect.has_real_text("hello"))
        self.assertFalse(collect.has_real_text(""))

    def test_has_real_text_list_text_only(self):
        self.assertTrue(collect.has_real_text([{"type": "text", "text": "hi"}]))

    def test_has_real_text_list_with_tool_result_excluded(self):
        # Even mixed with text, a tool_result block disqualifies (§5).
        self.assertFalse(collect.has_real_text([
            {"type": "text", "text": "hi"},
            {"type": "tool_result", "tool_use_id": "x", "content": "y"},
        ]))
        self.assertFalse(collect.has_real_text([{"type": "tool_result", "content": "y"}]))

    def test_has_real_text_list_no_text_block(self):
        self.assertFalse(collect.has_real_text([{"type": "image", "source": {}}]))

    def test_is_qualifying_user_turn_predicate(self):
        base = {
            "type": "user",
            "message": {"role": "user", "content": "hi"},
            "isSidechain": False,
            "isMeta": False,
        }
        self.assertTrue(collect.is_qualifying_user_turn(base))

        sidechain = dict(base, isSidechain=True)
        self.assertFalse(collect.is_qualifying_user_turn(sidechain))

        meta = dict(base, isMeta=True)
        self.assertFalse(collect.is_qualifying_user_turn(meta))

        tool_result = dict(base, message={"role": "user", "content": [
            {"type": "tool_result", "content": "x"}
        ]})
        self.assertFalse(collect.is_qualifying_user_turn(tool_result))

        wrong_type = dict(base, type="assistant")
        self.assertFalse(collect.is_qualifying_user_turn(wrong_type))

        wrong_role = dict(base, message={"role": "assistant", "content": "hi"})
        self.assertFalse(collect.is_qualifying_user_turn(wrong_role))

    def test_classify_task_category_order(self):
        # debug-fix checked before build-feature — "fix the build" -> debug-fix
        self.assertEqual(collect.classify_task_category("fix the build"), "debug-fix")
        self.assertEqual(collect.classify_task_category("build a new component"), "build-feature")
        self.assertEqual(collect.classify_task_category("write a blog post"), "writing-content")
        self.assertEqual(collect.classify_task_category("research and compare options"), "research-analysis")
        self.assertEqual(collect.classify_task_category("setup CI config"), "config-tooling")
        self.assertEqual(collect.classify_task_category("say hello"), "other")

    def test_classify_task_category_case_insensitive(self):
        self.assertEqual(collect.classify_task_category("FIX THE BUG"), "debug-fix")

    def test_compute_duration_ms_single_message(self):
        self.assertEqual(collect.compute_duration_ms([1000.0]), 0)
        self.assertEqual(collect.compute_duration_ms([]), 0)

    def test_compute_duration_ms_caps_at_five_minutes(self):
        # gap of 10 minutes must cap at 5 minutes (300000ms)
        ts = [0.0, 10 * 60 * 1000]
        self.assertEqual(collect.compute_duration_ms(ts), 300_000)

    def test_compute_duration_ms_sums_multiple_gaps(self):
        ts = [0.0, 1000.0, 3000.0]
        self.assertEqual(collect.compute_duration_ms(ts), 3000)

    def test_parse_ts_valid_and_invalid(self):
        self.assertIsNotNone(collect.parse_ts("2026-07-01T09:00:00.000Z"))
        self.assertIsNone(collect.parse_ts(None))
        self.assertIsNone(collect.parse_ts("not-a-timestamp"))
        self.assertIsNone(collect.parse_ts(""))

    def test_nested_parent_session_id_split_not_dirname(self):
        # Simulate the split rule directly against a workflow-nested path.
        path = "/root/proj/SESSIONID/subagents/workflows/wf_abc/agent-y.jsonl"
        split_marker = os.sep + "subagents" + os.sep
        left = path.split(split_marker, 1)[0]
        parent = os.path.basename(left)
        self.assertEqual(parent, "SESSIONID")
        # A naive dirname would have returned "wf_abc", not "SESSIONID".
        self.assertNotEqual(parent, "wf_abc")


class TestFixtureFiles(unittest.TestCase):
    """Full collector run over the hand-made fixture tree, one assertion
    group per fixture file / spec edge case."""

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.counters = run_collect()

    def test_empty_file_produces_no_rows(self):
        matches = [k for k in self.rows if k[0] == "empty_file"]
        self.assertEqual(matches, [])

    def test_malformed_line_skipped_but_file_still_processed(self):
        row = self.rows[("malformed_line", "Opus 4.8")]
        self.assertEqual(row["main"]["assistant_messages"], 1)
        self.assertEqual(row["main"]["user_turns"], 1)
        # the malformed line itself must have been counted as skipped
        self.assertGreaterEqual(self.counters.lines_skipped, 1)

    def test_synthetic_model_line_skipped(self):
        # Only the real claude-opus-4-8 line should produce a row; the
        # <synthetic> line must never create a row of its own.
        matches = [k for k in self.rows if k[0] == "synthetic_model"]
        self.assertEqual(matches, [("synthetic_model", "Opus 4.8")])
        row = self.rows[("synthetic_model", "Opus 4.8")]
        self.assertEqual(row["main"]["assistant_messages"], 1)

    def test_multi_model_session_attribution(self):
        opus = self.rows[("multi_model_session", "Opus 4.8")]
        fable = self.rows[("multi_model_session", "Fable 5")]
        # Chain-walk (§4 amended): u1 -> att1 -> a1 (Opus) via chain;
        # u2 -> att2 -> att3 -> a2 (Fable) via chain; u3's walk hits u4
        # (a USER line) -> falls back to nearest following assistant in
        # file order, which is a3 (Fable). u4 is tool_result-only and
        # never a qualifying turn itself.
        self.assertEqual(opus["main"]["user_turns"], 1)
        self.assertEqual(fable["main"]["user_turns"], 2)
        self.assertEqual(opus["main"]["assistant_messages"], 1)
        self.assertEqual(fable["main"]["assistant_messages"], 2)
        # never double-counted: total user turns across rows == 3
        self.assertEqual(opus["main"]["user_turns"] + fable["main"]["user_turns"], 3)

    def test_chain_walk_through_intermediate_lines(self):
        # Run the collector on multi_model_session.jsonl alone with fresh
        # counters: u1 and u2 must resolve via CHAIN (walking through
        # attachment / last-prompt intermediates), u3 via FALLBACK (its walk
        # hits a user line). No drops.
        path = os.path.join(FIXTURES_ROOT, "-project-a", "multi_model_session.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        self.assertEqual(counters.chain, 2)
        self.assertEqual(counters.fallback, 1)
        self.assertEqual(counters.dropped, 0)

    def test_chain_walk_user_line_hit_falls_back(self):
        # u3's chain is u3 -> att4 (attachment) -> u4 (USER line): the walk
        # must stop at u4 and fall back to the nearest following assistant
        # (a3, Fable 5) — the turn lands on Fable via fallback, not chain.
        path = os.path.join(FIXTURES_ROOT, "-project-a", "multi_model_session.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        fable = rows[("multi_model_session", "Fable 5")]
        # 1 chain (u2) + 1 fallback (u3) = 2 turns on Fable
        self.assertEqual(fable.main["user_turns"], 2)
        self.assertEqual(counters.fallback, 1)

    def test_chain_walk_fifty_hop_cap(self):
        # chain_hop_cap.jsonl: u1 -> 55 chained attachment lines -> a1 (Opus).
        # The walk must abandon at 50 hops and use the fallback path; the
        # turn still lands on Opus (nearest following assistant) but is
        # counted as fallback, never chain.
        path = os.path.join(FIXTURES_ROOT, "-project-a", "chain_hop_cap.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        self.assertEqual(counters.chain, 0)
        self.assertEqual(counters.fallback, 1)
        self.assertEqual(counters.dropped, 0)
        opus = rows[("chain_hop_cap", "Opus 4.8")]
        self.assertEqual(opus.main["user_turns"], 1)

    def test_sidechain_user_line_excluded_from_user_turns(self):
        row = self.rows[("sidechain_user_line", "Opus 4.8")]
        self.assertEqual(row["main"]["user_turns"], 1)  # only u1, not u2 (sidechain)
        self.assertEqual(row["main"]["assistant_messages"], 1)

    def test_tool_calls_and_tool_error_via_id_join(self):
        row = self.rows[("tool_calls_and_error", "Opus 4.8")]
        self.assertEqual(row["main"]["tool_calls"], {"Read": 1, "Bash": 1})
        self.assertEqual(row["main"]["tool_errors"], 1)
        # u2 is tool_result-only -> not a qualifying user turn
        self.assertEqual(row["main"]["user_turns"], 1)

    def test_cache_tokens_never_summed_into_input(self):
        row = self.rows[("cache_token_separation", "Sonnet 5")]
        self.assertEqual(row["main"]["input_tokens"], 1000)
        self.assertEqual(row["main"]["cache_read_tokens"], 50000)
        self.assertEqual(row["main"]["cache_creation_tokens"], 3000)
        self.assertEqual(row["main"]["output_tokens"], 200)

    def test_single_message_session_duration_zero(self):
        row = self.rows[("single_message_session", "Opus 4.8")]
        self.assertEqual(row["duration_active_ms"], 0)
        self.assertEqual(row["main"]["assistant_messages"], 1)

    def test_missing_timestamp_dropped_from_duration_only(self):
        row = self.rows[("missing_timestamp", "Opus 4.8")]
        # Both assistant lines + both user turns still count for messages/turns
        # (missing timestamp only drops a line from duration, not from other
        # metrics).
        self.assertEqual(row["main"]["assistant_messages"], 2)
        self.assertEqual(row["main"]["user_turns"], 2)
        # Only u1 (09:00:00) and a1 (09:00:05) have parseable timestamps;
        # u2/a2 have none and are dropped from the duration calc only, so
        # exactly one 5000ms gap is counted (not the missing-ts pair).
        self.assertEqual(row["duration_active_ms"], 5000)
        self.assertEqual(row["start_ts"], "2026-07-01T09:00:00Z")
        self.assertEqual(row["end_ts"], "2026-07-01T09:00:05Z")

    def test_missing_session_id_field_uses_filename(self):
        # The line has no "sessionId" field at all; the collector must derive
        # session_id from the top-level filename, not crash, not depend on it.
        row = self.rows[("missing_session_id", "Opus 4.8")]
        self.assertEqual(row["session_id"], "missing_session_id")
        self.assertEqual(row["main"]["assistant_messages"], 1)

    def test_unknown_model_verbatim(self):
        matches = [k for k in self.rows if k[0] == "unknown_model"]
        self.assertEqual(matches, [("unknown_model", "claude-opus-4-7")])

    def test_missing_cwd_project_unknown(self):
        row = self.rows[("missing_cwd", "Opus 4.8")]
        self.assertEqual(row["project"], "unknown")

    def test_task_category_debug_fix_before_build_feature(self):
        row = self.rows[("task_category", "Opus 4.8")]
        self.assertEqual(row["task_category"], "debug-fix")

    def test_subagent_only_model_row_carries_real_dates(self):
        # subagent_only_parent: main session is Sonnet 5 only; the nested
        # agent-z.jsonl introduces Haiku 4.5 with NO main-chain lines at all.
        haiku_row = self.rows[("subagent_only_parent", "Haiku 4.5")]
        self.assertEqual(haiku_row["main"]["assistant_messages"], 0)
        self.assertEqual(haiku_row["main"]["user_turns"], 0)
        self.assertEqual(haiku_row["main"]["output_tokens"], 0)
        self.assertEqual(haiku_row["duration_active_ms"], 0)
        # MUST carry real dates from subagent timestamps, never null.
        self.assertIsNotNone(haiku_row["start_ts"])
        self.assertIsNotNone(haiku_row["end_ts"])
        self.assertEqual(haiku_row["start_ts"], "2026-07-02T10:05:30Z")
        self.assertEqual(haiku_row["subagent"]["messages"], 1)
        self.assertEqual(haiku_row["subagent"]["output_tokens"], 12)
        self.assertEqual(haiku_row["subagent"]["input_tokens"], 25)
        self.assertEqual(haiku_row["subagent"]["cache_read_tokens"], 3)
        self.assertEqual(haiku_row["subagent"]["cache_creation_tokens"], 1)

        sonnet_row = self.rows[("subagent_only_parent", "Sonnet 5")]
        self.assertEqual(sonnet_row["main"]["assistant_messages"], 1)
        self.assertEqual(sonnet_row["subagent"]["messages"], 0)

    def test_subagent_only_row_inherits_session_project_and_category(self):
        # Review MF-1: project and task_category are SESSION-level (§5/§5b).
        # The Haiku subagent-only row must inherit them from the parent
        # session (cwd .../project-a; first prompt "build a feature and
        # delegate part of it" -> build-feature), NOT default to
        # "unknown"/"other" just because the row was created from a nested
        # file after the top-level file was processed.
        haiku_row = self.rows[("subagent_only_parent", "Haiku 4.5")]
        sonnet_row = self.rows[("subagent_only_parent", "Sonnet 5")]
        self.assertEqual(haiku_row["project"], "project-a")
        self.assertEqual(haiku_row["task_category"], "build-feature")
        # both rows of the session carry identical session-level fields
        self.assertEqual(haiku_row["project"], sonnet_row["project"])
        self.assertEqual(haiku_row["task_category"], sonnet_row["task_category"])

    def test_main_wins_start_end_ts_over_same_model_subagent(self):
        # Review item 2 (Codex): a row that HAS main lines must take
        # start_ts/end_ts from MAIN lines only — a same-model subagent line
        # at 10:00 must not stretch end_ts past the last main line (09:00:05).
        row = self.rows[("main_wins_ts", "Opus 4.8")]
        self.assertEqual(row["main"]["assistant_messages"], 1)
        self.assertEqual(row["subagent"]["messages"], 1)  # subagent counted
        self.assertEqual(row["start_ts"], "2026-07-03T09:00:00Z")
        self.assertEqual(row["end_ts"], "2026-07-03T09:00:05Z")  # not 10:00

    def test_orphaned_nested_file_skipped_entirely(self):
        # Review item 3: orphan_session/subagents/agent-o.jsonl has NO
        # matching top-level orphan_session.jsonl. It must create no rows
        # and be counted in files_nested_orphaned.
        matches = [k for k in self.rows if k[0] == "orphan_session"]
        self.assertEqual(matches, [], "orphaned nested file must never create a session row")
        self.assertEqual(self.counters.files_nested_orphaned, 1)

    def test_hostile_lines_no_crash_and_correct_skips(self):
        # Review item 4 (§0 amended crash hardening), file processed in
        # isolation for exact counter assertions:
        #  - assistant with non-string model (123)     -> line skipped
        #  - assistant with usage output_tokens="nope" -> kept, field = 0
        #  - assistant with unhashable tool_use name/id -> line skipped
        path = os.path.join(FIXTURES_ROOT, "-project-a", "hostile_lines.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        row = rows[("hostile_lines", "Opus 4.8")]
        self.assertEqual(row.main["assistant_messages"], 1)  # only the bad-usage line
        self.assertEqual(row.main["input_tokens"], 5)        # good field kept
        self.assertEqual(row.main["output_tokens"], 0)       # "nope" -> 0
        self.assertEqual(row.main["tool_calls"], {})         # bad line contributed nothing
        self.assertEqual(counters.lines_skipped, 2)

    def test_tool_error_result_before_use_main(self):
        # Review item 5: tool_result (is_error) BEFORE its tool_use in file
        # order must still join (order-independent within the file).
        row = self.rows[("error_before_use", "Opus 4.8")]
        self.assertEqual(row["main"]["tool_errors"], 1)
        self.assertEqual(row["main"]["tool_calls"], {"Bash": 1})

    def test_tool_error_result_before_use_nested(self):
        # Same ordering robustness inside a nested subagent file.
        row = self.rows[("error_before_use", "Fable 5")]
        self.assertEqual(row["subagent"]["tool_errors"], 1)
        self.assertEqual(row["subagent"]["tool_calls"], {"Read": 1})

    def test_duplicate_uuid_positional_attribution(self):
        # Review item 6 (Opus reviewer repro): two user turns share
        # uuid="dup"; first is replied to by Opus, second by Fable. With a
        # last-writer/first-writer dict the split comes out 2/0; the
        # positional rule (§0 amended: nearest matching line at or after the
        # referencing line) must give 1/1, both via chain.
        path = os.path.join(FIXTURES_ROOT, "-project-a", "dup_uuid.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        opus = rows[("dup_uuid", "Opus 4.8")]
        fable = rows[("dup_uuid", "Fable 5")]
        self.assertEqual(opus.main["user_turns"], 1)
        self.assertEqual(fable.main["user_turns"], 1)
        self.assertEqual(counters.chain, 2)
        self.assertEqual(counters.fallback, 0)

    def test_duplicate_tool_use_id_first_wins_and_counted(self):
        # Review item 7: duplicate tool_use.id -> first occurrence in file
        # order (Opus) wins the join; the collision is counted.
        path = os.path.join(FIXTURES_ROOT, "-project-a", "dup_tool_id.jsonl")
        rows = {}
        counters = collect.Counters()
        collect.process_top_level_file(path, rows, counters)
        opus = rows[("dup_tool_id", "Opus 4.8")]
        fable = rows[("dup_tool_id", "Fable 5")]
        self.assertEqual(opus.main["tool_errors"], 1)
        self.assertEqual(fable.main["tool_errors"], 0)
        self.assertEqual(counters.tool_id_collisions, 1)

    def test_workflow_nested_subagent_path_parent_session_id(self):
        # agent-y.jsonl lives at
        # subagent_parent/subagents/workflows/wf_test/agent-y.jsonl
        # It MUST attribute to "subagent_parent", never "wf_test".
        matches = [k for k in self.rows if k[0] == "wf_test"]
        self.assertEqual(matches, [], "workflow dir name must never become a session id")

        fable_row = self.rows[("subagent_parent", "Fable 5")]
        self.assertEqual(fable_row["subagent"]["messages"], 2)
        self.assertEqual(fable_row["subagent"]["output_tokens"], 30)
        self.assertEqual(fable_row["subagent"]["input_tokens"], 55)

    def test_subagent_tool_error_joined_within_nested_file(self):
        # agent-y.jsonl: one tool_use (Bash) + one is_error:true tool_result
        # referencing it, joined within that nested file only.
        fable_row = self.rows[("subagent_parent", "Fable 5")]
        self.assertEqual(fable_row["subagent"]["tool_calls"], {"Bash": 1})
        self.assertEqual(fable_row["subagent"]["tool_errors"], 1)

    def test_subagent_nested_direct_path_and_tool_call(self):
        # agent-x.jsonl: direct (non-workflow) nested subagent, Haiku model,
        # one tool_use (Read), no errors.
        haiku_row = self.rows[("subagent_parent", "Haiku 4.5")]
        self.assertEqual(haiku_row["subagent"]["messages"], 2)
        self.assertEqual(haiku_row["subagent"]["tool_calls"], {"Read": 1})
        self.assertEqual(haiku_row["subagent"]["tool_errors"], 0)
        self.assertEqual(haiku_row["main"]["assistant_messages"], 0)  # never in main

    def test_main_chain_row_unaffected_by_its_subagents(self):
        # The top-level Opus row in subagent_parent must not include any of
        # the subagent contributions in its MAIN block.
        opus_row = self.rows[("subagent_parent", "Opus 4.8")]
        self.assertEqual(opus_row["main"]["assistant_messages"], 1)
        self.assertEqual(opus_row["subagent"]["messages"], 0)

    def test_journal_jsonl_skipped_entirely(self):
        # journal.jsonl sits in subagent_parent/subagents/ alongside
        # agent-x.jsonl. It must contribute nothing: no extra model rows,
        # no extra lines_skipped attributable to it being treated as data.
        # (Its lines are type "started"/"result" with no message at all —
        # if they were processed as a nested agent file they'd either crash
        # or inflate subagent counts; neither happens.)
        # Verify no stray "started"/"result"-only row exists and Opus/Haiku
        # counts in subagent_parent match exactly the two real agent files.
        opus_row = self.rows[("subagent_parent", "Opus 4.8")]
        haiku_row = self.rows[("subagent_parent", "Haiku 4.5")]
        fable_row = self.rows[("subagent_parent", "Fable 5")]
        total_subagent_messages = (
            opus_row["subagent"]["messages"]
            + haiku_row["subagent"]["messages"]
            + fable_row["subagent"]["messages"]
        )
        # agent-x.jsonl contributes 2 (Haiku), agent-y.jsonl contributes 2
        # (Fable) = 4 total. If journal.jsonl were double-counted or crashed
        # the run, this would differ or the test run would have errored.
        self.assertEqual(total_subagent_messages, 4)

    def test_no_double_counting_of_user_turns_across_all_rows(self):
        # Global invariant across the whole fixture tree: sum of user_turns
        # in multi_model_session must equal exactly 3 (already checked above,
        # re-verified here at the aggregate level for regression safety).
        total = sum(r["main"]["user_turns"] for k, r in self.rows.items() if k[0] == "multi_model_session")
        self.assertEqual(total, 3)

    def test_no_absolute_paths_in_project_field(self):
        for row in self.rows.values():
            self.assertNotIn("/Users/", row["project"])
            self.assertFalse(row["project"].startswith("/"))

    def test_turn_attribution_counters_consistent(self):
        # chain + fallback + dropped should be >= the qualifying user turns
        # observed in multi_model_session (2 chain + 1 fallback there).
        self.assertGreaterEqual(self.counters.chain, 2)
        self.assertGreaterEqual(self.counters.fallback, 1)


class TestBuildDataSchema(unittest.TestCase):
    """Verify build_data() output matches METRIC-RULES.md §6 schema shape."""

    @classmethod
    def setUpClass(cls):
        rows, counters = collect.collect(FIXTURES_ROOT)
        cls.data = collect.build_data(rows, counters)

    def test_top_level_schema_keys(self):
        expected_keys = {
            "generated_at", "top_level_files_seen", "files_with_data",
            "files_nested_scanned", "files_nested_orphaned", "lines_skipped",
            "turn_attribution", "models_seen", "rows",
        }
        self.assertEqual(set(self.data.keys()), expected_keys)

    def test_files_nested_orphaned_field_present(self):
        # §0 amended: orphaned nested trees counted in data.json.
        self.assertEqual(self.data["files_nested_orphaned"], 1)

    def test_turn_attribution_shape(self):
        self.assertEqual(set(self.data["turn_attribution"].keys()), {"chain", "fallback", "dropped"})

    def test_row_schema_keys(self):
        row = self.data["rows"][0]
        expected = {
            "session_id", "model", "project", "task_category",
            "start_ts", "end_ts", "duration_active_ms", "main", "subagent",
        }
        self.assertEqual(set(row.keys()), expected)
        self.assertEqual(
            set(row["main"].keys()),
            {"assistant_messages", "user_turns", "output_tokens", "input_tokens",
             "cache_read_tokens", "cache_creation_tokens", "tool_calls", "tool_errors"},
        )
        self.assertEqual(
            set(row["subagent"].keys()),
            {"messages", "output_tokens", "input_tokens", "cache_read_tokens",
             "cache_creation_tokens", "tool_calls", "tool_errors"},
        )

    def test_integers_default_zero_never_null(self):
        for row in self.data["rows"]:
            for block_name in ("main", "subagent"):
                block = row[block_name]
                for key, val in block.items():
                    if key == "tool_calls":
                        self.assertIsInstance(val, dict)
                    else:
                        self.assertIsInstance(val, int)

    def test_no_absolute_paths_anywhere_in_json(self):
        import json
        blob = json.dumps(self.data)
        self.assertNotIn("/Users/", blob)


class TestCLI(unittest.TestCase):
    """Smoke test the CLI entry point end-to-end against the fixture tree."""

    def test_main_writes_output_file(self):
        import subprocess
        import tempfile

        script = os.path.join(os.path.dirname(__file__), "..", "collect.py")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "data.json")
            result = subprocess.run(
                [sys.executable, script, "--root", FIXTURES_ROOT, "--out", out_path],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                content = f.read()
            self.assertNotIn("/Users/", content)


if __name__ == "__main__":
    unittest.main()
