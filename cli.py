"""
cli.py - Command-line interface for the Claude Code usage dashboard.

Commands:
  scan      - Scan JSONL files and update the database
  today     - Print today's usage summary
  stats     - Print all-time usage statistics
  dashboard - Scan + start dashboard server at a local URL
"""

import os
import shutil
import subprocess
import sys
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime, date

DB_PATH = Path.home() / ".claude" / "usage.db"

PRICING = {
    "claude-opus-4-6":   {"input":  5.00, "output": 25.00},
    "claude-opus-4-5":   {"input":  5.00, "output": 25.00},
    "claude-sonnet-4-6": {"input":  3.00, "output": 15.00},
    "claude-sonnet-4-5": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input":  1.00, "output":  5.00},
    "claude-haiku-4-6":  {"input":  1.00, "output":  5.00},
}

def get_pricing(model):
    if not model:
        return None
    if model in PRICING:
        return PRICING[model]
    for key in PRICING:
        if model.startswith(key):
            return PRICING[key]
    # Substring fallback: match model family by keyword
    m = model.lower()
    if "opus" in m:
        return PRICING["claude-opus-4-6"]
    if "sonnet" in m:
        return PRICING["claude-sonnet-4-6"]
    if "haiku" in m:
        return PRICING["claude-haiku-4-5"]
    return None

def calc_cost(model, inp, out, cache_read, cache_creation):
    p = get_pricing(model)
    if not p:
        return 0.0
    return (
        inp          * p["input"]  / 1_000_000 +
        out          * p["output"] / 1_000_000 +
        cache_read   * p["input"]  * 0.10 / 1_000_000 +
        cache_creation * p["input"] * 1.25 / 1_000_000
    )

def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def fmt_cost(c):
    return f"${c:.4f}"

def hr(char="-", width=60):
    print(char * width)

def require_db():
    if not DB_PATH.exists():
        print("Database not found. Run: python cli.py scan")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def get_dashboard_host():
    return os.environ.get("HOST", "127.0.0.1")


def get_dashboard_port():
    return int(os.environ["PORT"]) if "PORT" in os.environ else 0


def copy_to_clipboard(text):
    clipboard_commands = [
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["clip"],
    ]
    for command in clipboard_commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, input=text, text=True, check=True)
            return command[0]
        except Exception:
            continue
    return None


def read_single_key():
    if not sys.stdin.isatty():
        return None

    if os.name == "nt":
        try:
            import msvcrt
            ch = msvcrt.getwch()
            return "\n" if ch == "\r" else ch
        except Exception:
            return None

    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return None


def build_prompt_line(spinner_frame=None):
    prompt = "Press Enter to open in your default browser, or Esc/Ctrl+C to abort."
    if spinner_frame is None:
        return prompt
    status = f"\033[1;36mBeaming usage data {spinner_frame}\033[0m"
    return f"{prompt}  {status}"


def prompt_for_browser(url, open_browser=None):
    print()
    print(f"Dashboard URL: {url}")
    copied_by = copy_to_clipboard(url)
    if copied_by:
        print(f"Copied to clipboard via {copied_by}.")
    else:
        print("Clipboard copy unavailable on this system.")

    if not sys.stdin.isatty():
        print("Open that URL manually. Press Ctrl+C to stop the server.")
        return

    stop_spinner = threading.Event()

    def spinner():
        frames = "|/-\\"
        idx = 0
        while not stop_spinner.is_set():
            sys.stdout.write("\r" + build_prompt_line(frames[idx % len(frames)]))
            sys.stdout.flush()
            idx += 1
            time.sleep(0.12)
        sys.stdout.write("\r" + build_prompt_line() + " " * 24)
        sys.stdout.flush()

    spinner_thread = threading.Thread(target=spinner, daemon=True)
    spinner_thread.start()
    try:
        while True:
            ch = read_single_key()
            if ch in ("\n", "\r"):
                if open_browser is not None:
                    open_browser(url)
            if ch in ("\x1b", "\x03"):
                raise KeyboardInterrupt
    finally:
        stop_spinner.set()
        spinner_thread.join(timeout=0.5)
        sys.stdout.write("\r" + build_prompt_line() + "\n")
        sys.stdout.flush()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_scan(projects_dir=None):
    from scanner import scan
    scan(projects_dir=Path(projects_dir) if projects_dir else None)


def cmd_today():
    conn = require_db()
    conn.row_factory = sqlite3.Row
    today = date.today().isoformat()

    rows = conn.execute("""
        SELECT
            COALESCE(model, 'unknown') as model,
            SUM(input_tokens)          as inp,
            SUM(output_tokens)         as out,
            SUM(cache_read_tokens)     as cr,
            SUM(cache_creation_tokens) as cc,
            COUNT(*)                   as turns
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
        GROUP BY model
        ORDER BY inp + out DESC
    """, (today,)).fetchall()

    sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as cnt
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
    """, (today,)).fetchone()

    print()
    hr()
    print(f"  Today's Usage  ({today})")
    hr()

    if not rows:
        print("  No usage recorded today.")
        print()
        return

    total_inp = total_out = total_cr = total_cc = total_turns = 0
    total_cost = 0.0

    for r in rows:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        total_cost += cost
        total_inp += r["inp"] or 0
        total_out += r["out"] or 0
        total_cr  += r["cr"]  or 0
        total_cc  += r["cc"]  or 0
        total_turns += r["turns"]
        print(f"  {r['model']:<30}  turns={r['turns']:<4}  in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost={fmt_cost(cost)}")

    hr()
    print(f"  {'TOTAL':<30}  turns={total_turns:<4}  in={fmt(total_inp):<8}  out={fmt(total_out):<8}  cost={fmt_cost(total_cost)}")
    print()
    print(f"  Sessions today:   {sessions['cnt']}")
    print(f"  Cache read:       {fmt(total_cr)}")
    print(f"  Cache creation:   {fmt(total_cc)}")
    hr()
    print()
    conn.close()


def cmd_stats():
    conn = require_db()
    conn.row_factory = sqlite3.Row

    # Session-level info (count, date range)
    session_info = conn.execute("""
        SELECT
            COUNT(*)                  as sessions,
            MIN(first_timestamp)      as first,
            MAX(last_timestamp)       as last
        FROM sessions
    """).fetchone()

    # All-time totals from turns (more accurate — per-turn model attribution)
    totals = conn.execute("""
        SELECT
            SUM(input_tokens)             as inp,
            SUM(output_tokens)            as out,
            SUM(cache_read_tokens)        as cr,
            SUM(cache_creation_tokens)    as cc,
            COUNT(*)                      as turns
        FROM turns
    """).fetchone()

    # By model from turns (each turn has the actual model used)
    by_model = conn.execute("""
        SELECT
            COALESCE(model, 'unknown') as model,
            SUM(input_tokens)          as inp,
            SUM(output_tokens)         as out,
            SUM(cache_read_tokens)     as cr,
            SUM(cache_creation_tokens) as cc,
            COUNT(*)                   as turns,
            COUNT(DISTINCT session_id) as sessions
        FROM turns
        GROUP BY model
        ORDER BY inp + out DESC
    """).fetchall()

    # Top 5 projects from turns (join with sessions for project name)
    top_projects = conn.execute("""
        SELECT
            COALESCE(s.project_name, 'unknown') as project_name,
            SUM(t.input_tokens)  as inp,
            SUM(t.output_tokens) as out,
            COUNT(*)             as turns,
            COUNT(DISTINCT t.session_id) as sessions
        FROM turns t
        LEFT JOIN sessions s ON t.session_id = s.session_id
        GROUP BY s.project_name
        ORDER BY inp + out DESC
        LIMIT 5
    """).fetchall()

    # Daily average (last 30 days)
    daily_avg = conn.execute("""
        SELECT
            AVG(daily_inp) as avg_inp,
            AVG(daily_out) as avg_out,
            AVG(daily_cost) as avg_cost
        FROM (
            SELECT
                substr(timestamp, 1, 10) as day,
                SUM(input_tokens) as daily_inp,
                SUM(output_tokens) as daily_out,
                0.0 as daily_cost
            FROM turns
            WHERE timestamp >= datetime('now', '-30 days')
            GROUP BY day
        )
    """).fetchone()

    # Build total cost across all models
    total_cost = sum(
        calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        for r in by_model
    )

    print()
    hr("=")
    print("  Claude Code Usage - All-Time Statistics")
    hr("=")

    first_date = (session_info["first"] or "")[:10]
    last_date = (session_info["last"] or "")[:10]
    print(f"  Period:           {first_date} to {last_date}")
    print(f"  Total sessions:   {session_info['sessions'] or 0:,}")
    print(f"  Total turns:      {fmt(totals['turns'] or 0)}")
    print()
    print(f"  Input tokens:     {fmt(totals['inp'] or 0):<12}  (raw prompt tokens)")
    print(f"  Output tokens:    {fmt(totals['out'] or 0):<12}  (generated tokens)")
    print(f"  Cache read:       {fmt(totals['cr'] or 0):<12}  (90% cheaper than input)")
    print(f"  Cache creation:   {fmt(totals['cc'] or 0):<12}  (25% premium on input)")
    print()
    print(f"  Est. total cost:  ${total_cost:.4f}")
    hr()

    print("  By Model:")
    for r in by_model:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        print(f"    {r['model']:<30}  sessions={r['sessions']:<4}  turns={fmt(r['turns'] or 0):<6}  "
              f"in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost={fmt_cost(cost)}")

    hr()
    print("  Top Projects:")
    for r in top_projects:
        print(f"    {(r['project_name'] or 'unknown'):<40}  sessions={r['sessions']:<3}  "
              f"turns={fmt(r['turns'] or 0):<6}  tokens={fmt((r['inp'] or 0)+(r['out'] or 0))}")

    if daily_avg["avg_inp"]:
        hr()
        print("  Daily Average (last 30 days):")
        print(f"    Input:   {fmt(int(daily_avg['avg_inp'] or 0))}")
        print(f"    Output:  {fmt(int(daily_avg['avg_out'] or 0))}")

    hr("=")
    print()
    conn.close()


def cmd_dashboard(projects_dir=None):
    import webbrowser
    import threading

    print("Running scan first...")
    cmd_scan(projects_dir=projects_dir)

    print("\nStarting dashboard server...")
    from dashboard import create_server

    host = get_dashboard_host()
    port = get_dashboard_port()
    server = create_server(host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    url = f"http://{bound_host}:{bound_port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        prompt_for_browser(url, open_browser=webbrowser.open)
        thread.join()
    except KeyboardInterrupt:
        print("Aborted.")
    finally:
        server.shutdown()
        server.server_close()


# ── Entry point ───────────────────────────────────────────────────────────────

USAGE = """
Claude Code Usage Dashboard

Usage:
  python cli.py scan [--projects-dir PATH]       Scan JSONL files and update database
  python cli.py today                            Show today's usage summary
  python cli.py stats                            Show all-time statistics
  python cli.py dashboard [--projects-dir PATH]  Scan + start dashboard at a free local port
"""

COMMANDS = {
    "scan": cmd_scan,
    "today": cmd_today,
    "stats": cmd_stats,
    "dashboard": cmd_dashboard,
}

def parse_projects_dir(args):
    """Extract --projects-dir value from argument list."""
    for i, arg in enumerate(args):
        if arg == "--projects-dir" and i + 1 < len(args):
            return args[i + 1]
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(USAGE)
        sys.exit(0)

    command = sys.argv[1]
    projects_dir = parse_projects_dir(sys.argv[2:])

    if command in ("scan", "dashboard") and projects_dir:
        COMMANDS[command](projects_dir=projects_dir)
    else:
        COMMANDS[command]()
