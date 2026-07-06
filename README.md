# Model Compare

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/isas1)

A local, zero-dependency dashboard that shows **how you use different Claude models** in [Claude Code](https://claude.com/claude-code) — mined entirely from the transcript files already sitting on your machine.

Ever wondered whether you reach for Opus for different work than Sonnet? Whether one model's sessions run longer, use more tools, delegate more to subagents, or one-shot more of your requests? This answers that — for *your* sessions, on *your* machine, with nothing uploaded anywhere.

## What you get

- **Overview** — session counts, median output tokens, active duration, and user turns per model, with toggleable model chips
- **Interaction shape** — messages per turn, tool calls per turn, one-shot rate (autonomy/verbosity proxies, medianed per session so one giant session can't dominate)
- **Tool-mix fingerprint** — each model's tool calls bucketed into explore / edit / execute / orchestrate
- **Comparison table** — 20+ metrics side by side, filterable by recency, date range, and task category
- **Category × model heatmap** — what kind of work each model actually got used for
- **Output tokens over time** — every session as a point on a timeline, linear or log scale
- **Tool usage** — top 10 tools per model
- **Message patterns** — thinking-block frequency, text length per block, stop-reason mix, quick-follow-up cadence
- **Download JSON / CSV** — one click exports all computed summary stats

## Quick start

Requires Python 3.8+ (standard library only — no pip installs) and any modern browser.

```bash
git clone https://github.com/isas1/claude-model-compare.git
cd claude-model-compare

# 1. Scan your local Claude Code transcripts (read-only) and build data.json
python3 collect.py

# 2. Serve the dashboard and open it
python3 -m http.server 8850
# then open http://localhost:8850
```

`collect.py` reads from `~/.claude/projects` by default. Options:

```
--root ROOT   Root directory to scan (default: ~/.claude/projects)
--out OUT     Output path for data.json (default: ./data.json)
```

Re-run `collect.py` any time to refresh the data.

## Privacy — by design, not by promise

This tool is built for a hard rule: **no conversation text, ever.**

- `collect.py` opens your transcripts **read-only** and aggregates **numbers only**: token counts, message counts, tool-call counts, durations, character *counts* (integers — never the characters themselves).
- `data.json` contains session IDs, model names, project directory names, timestamps, and numeric stats. No prompts, no responses, no code, no file contents.
- `data.json` is **gitignored** — your stats never leave your machine even if you fork and push this repo.
- The dashboard is static HTML/JS served locally. No analytics, no network calls, no CDN — view source and check.
- The JSON/CSV export contains the same summary numbers, nothing else.

## What this is *not*

The dashboard is **descriptive, not causal**. Differences between models mostly reflect routing, task mix, and personal habit — which model you happened to pick for which kind of work — not model capability. It never ranks, scores, or recommends models, and you shouldn't read it as a benchmark. It's a mirror of your own usage.

## How it works

- Walks `~/.claude/projects/**/*.jsonl`, streams each transcript line by line, and aggregates one row per (session, model) pair.
- Separates the **main conversation chain** from **subagent** activity via transitive `parentUuid` chain-walking, so delegation shows up as its own metric instead of polluting the main stats.
- Ratio metrics are **per-session medians**, never pooled across sessions (except two documented pooled rates), so a single monster session can't skew a model's profile.
- Every metric's exact definition lives in [METRIC-RULES.md](METRIC-RULES.md) and [METRIC-RULES-V2.md](METRIC-RULES-V2.md) — the binding spec the collector and dashboard are tested against.

## Tests

```bash
python3 -m pytest tests/ -q
```

64 tests cover the collector against synthetic fixture transcripts (malformed lines, duplicate UUIDs, hostile input, multi-model sessions, subagent attribution, and more). Fixtures are fully synthetic — no real transcript data in this repo.

## Repo notes

- `PLAN.md`, `SCHEMA-NOTES.md`, `REVIEW-PHASE*.md` — working documents from development (schema research, adversarial review rounds). Kept for transparency; session IDs in examples are redacted placeholders.
- Transcript format is undocumented and may drift between Claude Code versions. The collector fails soft (skips malformed lines, reports fallback rates in the footer), but if a new version changes the schema, open an issue.

## Support

If this saved you an evening of curiosity-scripting, you can [buy me a coffee](https://buymeacoffee.com/isas1). ☕

## License

MIT
