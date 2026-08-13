#!/usr/bin/env python3
"""
Nickel dashboard data updater — runs locally on schedule.
Updates data.json in nickel_gh_static/ with fresh data from Zhiji + akshare + AI.
Also syncs to GitHub repo for GitHub Actions Pages.
"""
import subprocess
import sys
import os
from datetime import datetime

# Set up environment
SCRIPT_DIR = "/home/ubuntu/nickel_dashboard_gh"
VENV_PYTHON = "/home/ubuntu/nickel_dashboard_gh/venv/bin/python3"
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")

# Load .env
for line in open(ENV_FILE):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

OUTPUT = "/home/ubuntu/nickel_gh_static/data.json"
os.environ["OUTPUT"] = OUTPUT

log = lambda msg: print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def main():
    log("Starting nickel data update...")
    
    # Run fetch_data.py with venv that has akshare
    cmd = [VENV_PYTHON, os.path.join(SCRIPT_DIR, "fetch_data.py")]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=os.environ)
    
    if result.returncode != 0:
        log(f"FAILED: {result.stderr[:500]}")
        sys.exit(1)
    
    # Parse output
    output_lines = result.stdout.strip().split('\n')
    for line in output_lines:
        log(line)
    
    # Sync to GitHub repo
    log("Syncing data.json to GitHub repo...")
    import shutil
    gh_data = os.path.join(SCRIPT_DIR, "data.json")
    shutil.copy2(OUTPUT, gh_data)
    
    # Try git commit & push (non-blocking)
    try:
        subprocess.run(
            ["git", "add", "data.json"],
            cwd=SCRIPT_DIR, capture_output=True, timeout=10
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=SCRIPT_DIR, capture_output=True, timeout=10
        )
        if diff.returncode != 0:  # has changes
            subprocess.run(
                ["git", "commit", "-m", f"update data {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                cwd=SCRIPT_DIR, capture_output=True, timeout=10,
                env={**os.environ, "GIT_AUTHOR_NAME": "ni-bot", "GIT_AUTHOR_EMAIL": "ni-bot@github.com",
                     "GIT_COMMITTER_NAME": "ni-bot", "GIT_COMMITTER_EMAIL": "ni-bot@github.com"}
            )
            # Push in background (don't block)
            subprocess.Popen(
                ["git", "push"],
                cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            log("Git push started in background")
        else:
            log("No data changes to commit")
    except Exception as e:
        log(f"Git sync skipped: {e}")
    
    log("Done!")

if __name__ == "__main__":
    main()
