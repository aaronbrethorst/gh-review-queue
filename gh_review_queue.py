#!/usr/bin/env -S uv --quiet run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv",
#     "requests",
# ]
# ///

"""
List all open pull requests for a GitHub organization.

Usage:
    GITHUB_TOKEN=ghp_xxx ./gh_review_queue.py OneBusAway
    GITHUB_TOKEN=ghp_xxx ./gh_review_queue.py OneBusAway --output html

Environment variables:
    GITHUB_TOKEN - GitHub personal access token with repo scope
"""

import argparse
import html
import itertools
import json
import os
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

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


GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

VIEWER_QUERY = "{ viewer { login } }"

QUERY = """
query($org: String!, $cursor: String) {
  organization(login: $org) {
    repositories(first: 100, after: $cursor, isFork: false, isArchived: false, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        pullRequests(states: OPEN, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            number
            title
            url
            createdAt
            isDraft
            author { login }
            labels(first: 10) { nodes { name color } }
            comments { totalCount }
            reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
            reviews(last: 10) { totalCount nodes { author { login } createdAt } }
            commits(last: 1) {
              nodes {
                commit {
                  committedDate
                  statusCheckRollup { state }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_viewer_login(token: str) -> str:
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        GITHUB_GRAPHQL_URL,
        json={"query": VIEWER_QUERY},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()["data"]["viewer"]["login"]


def fetch_open_prs(token: str, org: str) -> list[dict]:
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }

    all_prs = []
    cursor = None

    while True:
        variables = {"org": org, "cursor": cursor}
        resp = requests.post(
            GITHUB_GRAPHQL_URL,
            json={"query": QUERY, "variables": variables},
            headers=headers,
        )
        if resp.status_code >= 500:
            print(
                f"GitHub API error: {resp.status_code} {resp.reason}\n"
                f"URL: {GITHUB_GRAPHQL_URL}\n"
                "GitHub may be experiencing an outage. Check https://www.githubstatus.com for details.",
                file=sys.stderr,
            )
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            print(f"GraphQL errors: {data['errors']}", file=sys.stderr)
            sys.exit(1)

        repos = data["data"]["organization"]["repositories"]
        for repo in repos["nodes"]:
            for pr in repo["pullRequests"]["nodes"]:
                commits = pr.get("commits", {}).get("nodes", [])
                last_commit = commits[0]["commit"] if commits else {}
                rollup = last_commit.get("statusCheckRollup") or {}
                requested_reviewers = [
                    node["requestedReviewer"]["login"]
                    for node in pr.get("reviewRequests", {}).get("nodes", [])
                    if node.get("requestedReviewer") and node["requestedReviewer"].get("login")
                ]
                reviews = [
                    {"author": (r.get("author") or {}).get("login", "ghost"), "created_at": r["createdAt"]}
                    for r in pr.get("reviews", {}).get("nodes", [])
                ]
                all_prs.append(
                    {
                        "repo": repo["name"],
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["url"],
                        "created_at": pr["createdAt"],
                        "is_draft": pr["isDraft"],
                        "author": (pr.get("author") or {}).get("login", "ghost"),
                        "labels": [
                            {"name": l["name"], "color": l["color"]}
                            for l in pr.get("labels", {}).get("nodes", [])
                        ],
                        "comment_count": pr["comments"]["totalCount"],
                        "review_count": pr["reviews"]["totalCount"],
                        "requested_reviewers": requested_reviewers,
                        "reviews": reviews,
                        "last_commit_date": last_commit.get("committedDate"),
                        "ci_state": rollup.get("state"),
                    }
                )

        if repos["pageInfo"]["hasNextPage"]:
            cursor = repos["pageInfo"]["endCursor"]
        else:
            break

    return all_prs


def print_table(prs: list[dict]) -> None:
    if not prs:
        print("No open pull requests found.")
        return

    repo_w = max(len(pr["repo"]) for pr in prs)
    title_w = max(len(pr["title"]) for pr in prs)
    url_w = max(len(pr["url"]) for pr in prs)

    repo_w = max(repo_w, 4)
    title_w = max(title_w, 8)
    url_w = max(url_w, 6)

    header = f"| {'Repo':<{repo_w}} | {'PR Title':<{title_w}} | {'PR URL':<{url_w}} |"
    separator = f"|{'-' * (repo_w + 2)}|{'-' * (title_w + 2)}|{'-' * (url_w + 2)}|"

    print(header)
    print(separator)
    for pr in prs:
        print(f"| {pr['repo']:<{repo_w}} | {pr['title']:<{title_w}} | {pr['url']:<{url_w}} |")

    print(f"\nTotal: {len(prs)} open PR(s)")


def _time_ago(iso_ts: str) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _ci_icon(state: str | None) -> str:
    if state == "SUCCESS":
        return '<span class="text-green-600" title="Checks passing">&#10003;</span>'
    if state in ("FAILURE", "ERROR"):
        return '<span class="text-red-600" title="Checks failing">&#10007;</span>'
    if state == "PENDING":
        return '<span class="text-yellow-500" title="Checks pending">&#9679;</span>'
    return ""


def _label_badge(name: str, color: str) -> str:
    r, g, b = int(color[:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    text_color = "#fff" if lum < 0.6 else "#24292f"
    return (
        f'<span class="inline-block px-2 py-0.5 text-xs font-medium rounded-full mr-1" '
        f'style="background-color:#{html.escape(color)};color:{text_color}">'
        f'{html.escape(name)}</span>'
    )


def _count_badge(count: int, icon_svg: str, title: str) -> str:
    if count == 0:
        return ""
    return (
        f'<span class="inline-flex items-center gap-1 text-xs text-gray-500" title="{title}">'
        f'{icon_svg} {count}</span>'
    )


# Inline SVGs kept minimal
_SVG_COMMENT = (
    '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
    'd="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>'
    '</svg>'
)
_SVG_REVIEW = (
    '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
    'd="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
    'd="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>'
    '</svg>'
)
_SVG_PR = (
    '<svg class="w-5 h-5 shrink-0" viewBox="0 0 16 16" fill="currentColor">'
    '<path d="M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z"/>'
    '</svg>'
)


def _needs_attention(pr: dict, viewer: str) -> bool:
    # Rule 1: viewer is a pending requested reviewer
    if viewer in pr["requested_reviewers"]:
        return True
    # Rule 2: no reviews from anyone
    if pr["review_count"] == 0:
        return True
    # Rule 3: new commits since viewer's last review
    my_reviews = [r for r in pr["reviews"] if r["author"] == viewer]
    if my_reviews:
        last_review = max(r["created_at"] for r in my_reviews)
        if pr["last_commit_date"] and pr["last_commit_date"] > last_review:
            return True
    return False


def render_html(prs: list[dict], org: str) -> str:
    # Group PRs by repo, sorted alphabetically
    grouped: dict[str, list[dict]] = {}
    for pr in prs:
        grouped.setdefault(pr["repo"], []).append(pr)

    rows = ""
    for repo_name in sorted(grouped, key=str.casefold):
        repo = html.escape(repo_name)
        repo_url = f"https://github.com/{html.escape(org)}/{repo}"
        rows += f"""      <div class="sticky top-0 flex items-center bg-gray-50/90 px-4 py-3 text-sm font-semibold text-gray-900 ring-1 ring-gray-900/10 backdrop-blur-sm dark:bg-gray-700/90 dark:text-gray-200 dark:ring-black/10">
        <a href="{repo_url}" class="hover:text-blue-600">{repo}</a>
      </div>
"""
        for pr in grouped[repo_name]:
            title = html.escape(pr["title"])
            url = html.escape(pr["url"])
            author = html.escape(pr["author"])
            number = pr["number"]
            ago = _time_ago(pr["created_at"])
            ci = _ci_icon(pr["ci_state"])
            pr_color = "text-gray-500" if pr["is_draft"] else "text-green-600"

            labels_html = "".join(_label_badge(l["name"], l["color"]) for l in pr["labels"])
            if labels_html:
                labels_html = f'<div class="mt-1">{labels_html}</div>'

            counters = []
            rev = _count_badge(pr["review_count"], _SVG_REVIEW, "Reviews")
            cmt = _count_badge(pr["comment_count"], _SVG_COMMENT, "Comments")
            if rev:
                counters.append(rev)
            if cmt:
                counters.append(cmt)
            counters_html = f'<div class="flex items-center gap-3">{" ".join(counters)}</div>' if counters else ""

            attention_cls = "border-l-4 border-l-blue-500" if pr.get("needs_attention") else "border-l-4 border-l-transparent"
            rows += f"""      <div class="pr-row flex items-start gap-3 px-4 py-3 border-b border-gray-200 hover:bg-gray-50 {attention_cls}" data-pr-url="{url}">
        <div class="{pr_color} mt-0.5">{_SVG_PR}</div>
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-x-1">
            <a href="{url}" class="text-base font-semibold text-gray-900 hover:text-blue-600">{title}</a>
            {ci}
          </div>
          {labels_html}
          <div class="text-xs text-gray-500 mt-0.5">#{number} opened {ago} by {author}</div>
        </div>
        {counters_html}
      </div>
"""

    empty_msg = ""
    if not prs:
        empty_msg = '<p class="text-gray-500 mt-4">No open pull requests found.</p>'

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <title>Open PRs – {html.escape(org)}</title>
  </head>
  <body class="bg-gray-50 p-8">
    <div class="max-w-5xl mx-auto">
      <h1 class="text-3xl font-bold mb-1">{html.escape(org)}</h1>
      <p class="text-gray-500 mb-6">{len(prs)} open pull request{"" if len(prs) == 1 else "s"}</p>
      {empty_msg}
      <div class="bg-white rounded-lg shadow border border-gray-200">
{rows}      </div>
    </div>
    <script>
      const KEY = "seen_prs";
      const seen = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
      function markSeen(row) {{
        row.classList.remove("border-l-blue-500");
        row.classList.add("border-l-transparent");
      }}
      document.querySelectorAll(".pr-row").forEach(row => {{
        const url = row.dataset.prUrl;
        if (seen.has(url)) markSeen(row);
        row.querySelectorAll("a").forEach(a => {{
          a.addEventListener("click", () => {{
            seen.add(url);
            localStorage.setItem(KEY, JSON.stringify([...seen]));
            markSeen(row);
          }});
        }});
      }});
    </script>
  </body>
</html>
"""


def main() -> None:
    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="List open PRs for a GitHub organization.")
    parser.add_argument("org", nargs="?", help="GitHub organization name")
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--output", choices=["html"], help="Output format (default: table)")
    parser.add_argument("--ignore", help="Comma-separated list of repo names to ignore")
    parser.add_argument("--no-open", action="store_true", help="Don't open HTML report in default browser")
    args = parser.parse_args()

    # Load config file as defaults, CLI args override
    config_path = args.config
    if not config_path and not args.org:
        default = Path(__file__).resolve().parent / "settings.json"
        if not default.exists():
            parser.error(f"No arguments given and {default} not found")
        config_path = str(default)

    config = {}
    if config_path:
        with open(config_path) as f:
            config = json.load(f)

    org = args.org or config.get("org")
    if not org:
        parser.error("org is required (via argument or --config)")

    output = args.output or config.get("output")
    if args.ignore:
        ignore = {name.strip() for name in args.ignore.split(",")}
    else:
        ignore = set(config.get("ignore", []))

    with spinner(f"Fetching open PRs for {org}…"):
        prs = fetch_open_prs(token, org)
    prs = [pr for pr in prs if pr["repo"] not in ignore]
    status(f"Found {len(prs)} open PR{'s' if len(prs) != 1 else ''}")

    with spinner("Identifying reviewer…"):
        viewer = fetch_viewer_login(token)
    status(f"Logged in as {viewer}")

    with spinner("Sorting by review priority…"):
        for pr in prs:
            pr["needs_attention"] = _needs_attention(pr, viewer)
        prs.sort(key=lambda pr: (not pr["needs_attention"], pr["created_at"]))
    needs = sum(1 for pr in prs if pr["needs_attention"])
    status(f"{needs} PR{'s' if needs != 1 else ''} need{'s' if needs == 1 else ''} your attention")

    open_browser = not args.no_open and config.get("open", True)

    if output == "html":
        with spinner("Generating HTML report…"):
            filepath = Path(tempfile.gettempdir()) / f"{org}_review_queue.html"
            filepath.write_text(render_html(prs, org))
        status(f"Report written to {filepath}")
        print(filepath)
        if open_browser:
            webbrowser.open(filepath.as_uri())
    else:
        print_table(prs)


if __name__ == "__main__":
    main()