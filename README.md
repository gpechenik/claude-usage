# Claude Code Usage Dashboard

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![claude-code](https://img.shields.io/badge/claude--code-black?style=flat-square)](https://claude.ai/code)

**Pro and Max subscribers get a progress bar. This gives you the full picture.**

Claude Code writes detailed usage logs locally — token counts, models, sessions, projects — regardless of your plan. This dashboard reads those logs and turns them into charts and cost estimates. Works on API, Pro, and Max plans.

![Claude Usage Dashboard](docs/screenshot.png)

**Created by:** [The Product Compass Newsletter](https://www.productcompass.pm)

---

## What this tracks

Works on **API, Pro, and Max plans** — Claude Code writes local usage logs regardless of subscription type. This tool reads those logs and gives you visibility that Anthropic's UI doesn't provide.

Captures usage from:
- **Claude Code CLI** (`claude` command in terminal)
- **VS Code extension** (Claude Code sidebar)
- **Dispatched Code sessions** (sessions routed through Claude Code)

**Not captured:**
- **Cowork sessions** — these run server-side and do not write local JSONL transcripts

---

## Requirements

- Python 3.8+
- No third-party packages — uses only the standard library (`sqlite3`, `http.server`, `json`, `pathlib`)

> Anyone running Claude Code already has Python installed.

## Quick Start

No `pip install`, no virtual environment, no build step.

### Windows
```
git clone https://github.com/phuryn/claude-usage
cd claude-usage
python cli.py dashboard
```

### macOS / Linux
```
git clone https://github.com/phuryn/claude-usage
cd claude-usage
python3 cli.py dashboard
```

---

## Usage

> On macOS/Linux, use `python3` instead of `python` in all commands below.

```
# Scan JSONL files and populate the database (~/.claude/usage.db)
python cli.py scan

# Show today's usage summary by model (in terminal)
python cli.py today

# Show all-time statistics (in terminal)
python cli.py stats

# Scan + start dashboard at a free local port
python cli.py dashboard

# Pin a specific loopback bind and port if you want one
HOST=127.0.0.1 PORT=9000 python cli.py dashboard

# Deliberately expose remotely only if you really want to
ALLOW_REMOTE=1 HOST=0.0.0.0 PORT=9000 python cli.py dashboard

# Scan a custom projects directory
python cli.py scan --projects-dir /path/to/transcripts

# Scan a custom projects directory and launch the dashboard from it
python cli.py dashboard --projects-dir /path/to/transcripts
```

The scanner is incremental — it tracks each file's path and modification time, so re-running `scan` is fast and only processes new or changed files.

By default, the scanner checks both `~/.claude/projects/` and the Xcode Claude integration directory (`~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/projects/`), skipping any that don't exist. Use `--projects-dir` to scan a custom location instead.

---

## How it works

Claude Code writes one JSONL file per session to `~/.claude/projects/`. Each line is a JSON record; `assistant`-type records contain:
- `message.usage.input_tokens` — raw prompt tokens
- `message.usage.output_tokens` — generated tokens
- `message.usage.cache_creation_input_tokens` — tokens written to prompt cache
- `message.usage.cache_read_input_tokens` — tokens served from prompt cache
- `message.model` — the model used (e.g. `claude-sonnet-4-6`)

`scanner.py` parses those files and stores the data in a SQLite database at `~/.claude/usage.db`.

`dashboard.py` serves a single-page dashboard on a local loopback address with Chart.js served locally from the repo, so the browser does not need to fetch chart code from a CDN. By default, if `PORT` is unset, it asks the OS for a free local port. It auto-refreshes every 30 seconds, supports model filtering with bookmarkable URLs, and includes session drill-down for branch, cwd, tools, and turn history.

When you run `python cli.py dashboard`, the CLI now:
- prints the dashboard URL
- copies the URL to your clipboard when possible
- lets you press `Enter` any time to open it in your default browser again
- lets you hit `Esc` or `Ctrl+C` to abort instead of auto-opening a browser window

By default, the dashboard refuses to bind to non-loopback hosts. If you really want remote access, set `ALLOW_REMOTE=1` explicitly.

---

## Cost estimates

Costs are calculated using **Anthropic API pricing as of April 2026** ([claude.com/pricing#api](https://claude.com/pricing#api)).

**Only models whose name contains `opus`, `sonnet`, or `haiku` are included in cost calculations.** Local models, unknown models, and any other model names are excluded (shown as `n/a`).

| Model | Input | Output | Cache Write | Cache Read |
|-------|-------|--------|------------|-----------|
| claude-opus-4-6 | $5.00/MTok | $25.00/MTok | $6.25/MTok | $0.50/MTok |
| claude-sonnet-4-6 | $3.00/MTok | $15.00/MTok | $3.75/MTok | $0.30/MTok |
| claude-haiku-4-5 | $1.00/MTok | $5.00/MTok | $1.25/MTok | $0.10/MTok |

> **Note:** These are API prices. If you use Claude Code via a Max or Pro subscription, your actual cost structure is different (subscription-based, not per-token).

---

## Files

| File | Purpose |
|------|---------|
| `scanner.py` | Parses JSONL transcripts, writes to `~/.claude/usage.db` |
| `dashboard.py` | HTTP server + single-page HTML/JS dashboard |
| `cli.py` | `scan`, `today`, `stats`, `dashboard` commands |
| `vendor/chart.umd.min.js` | Vendored Chart.js bundle served locally by the dashboard |
