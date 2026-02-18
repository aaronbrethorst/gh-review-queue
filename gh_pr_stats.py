#!/usr/bin/env -S uv --quiet run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv",
#     "requests",
# ]
# ///

"""
List all pull requests (open and closed) for a GitHub repository.

Usage:
    GITHUB_TOKEN=ghp_xxx ./gh_pr_stats.py onebusaway/maglev

Environment variables:
    GITHUB_TOKEN - GitHub personal access token with repo scope
"""

import argparse
import csv
import io
import itertools
import os
import sys
import threading
import time
from contextlib import contextmanager

from dotenv import load_dotenv
import requests

_BRAILLE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@contextmanager
def spinner(message: str):
    """Show a braille spinner with a message while work is in progress."""
    done = threading.Event()

    def _spin():
        for frame in itertools.cycle(_BRAILLE_FRAMES):
            if done.is_set():
                break
            print(f"\r{frame} {message}", end="", flush=True, file=sys.stderr)
            time.sleep(0.08)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join()
        print(f"\r\033[2K\r", end="", file=sys.stderr)


def status(message: str):
    """Print a completed-step status line."""
    print(f"  {message}", file=sys.stderr)


def fetch_all_prs(token: str, owner: str, repo: str) -> list[dict]:
    """Fetch all pull requests (open + closed) using the GitHub REST API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    all_prs = []
    page = 1

    while True:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            params={"state": "all", "per_page": 100, "page": page},
            headers=headers,
        )
        if resp.status_code >= 500:
            print(
                f"GitHub API error: {resp.status_code} {resp.reason}\n"
                f"GitHub may be experiencing an outage. Check https://www.githubstatus.com for details.",
                file=sys.stderr,
            )
            sys.exit(1)
        resp.raise_for_status()

        results = resp.json()
        for pr in results:
            all_prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "author": (pr.get("user") or {}).get("login", "ghost"),
                "created_at": pr["created_at"],
                "closed_at": pr["closed_at"],
            })

        if len(results) < 100:
            break
        page += 1

    return all_prs


def write_csv(prs: list[dict], out: io.TextIOBase) -> None:
    writer = csv.writer(out)
    writer.writerow(["#", "Title", "Author", "Created", "Closed"])
    for pr in prs:
        writer.writerow([
            pr["number"],
            pr["title"],
            pr["author"],
            pr["created_at"][:10] if pr["created_at"] else "",
            pr["closed_at"][:10] if pr["closed_at"] else "",
        ])


def main() -> None:
    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="List all pull requests for a GitHub repository."
    )
    parser.add_argument("repo", help="Repository in owner/repo format (e.g. onebusaway/maglev)")
    parser.add_argument("-o", "--output", metavar="FILE", help="Write CSV to FILE instead of stdout")
    args = parser.parse_args()

    parts = args.repo.split("/")
    if len(parts) != 2:
        parser.error("repo must be in owner/repo format (e.g. onebusaway/maglev)")
    owner, repo = parts

    with spinner(f"Fetching PRs for {owner}/{repo}…"):
        prs = fetch_all_prs(token, owner, repo)
    status(f"Fetched {len(prs)} PR{'s' if len(prs) != 1 else ''}")

    if args.output:
        with open(args.output, "w", newline="") as f:
            write_csv(prs, f)
        status(f"Wrote {args.output}")
    else:
        write_csv(prs, sys.stdout)


if __name__ == "__main__":
    main()
