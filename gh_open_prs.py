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
    GITHUB_TOKEN=ghp_xxx ./gh_open_prs.py OneBusAway
    GITHUB_TOKEN=ghp_xxx ./gh_open_prs.py OneBusAway --output html

Environment variables:
    GITHUB_TOKEN - GitHub personal access token with repo scope
"""

import argparse
import html
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
import requests

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

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
            reviews(first: 1) { totalCount }
            commits(last: 1) {
              nodes {
                commit {
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


def render_html(prs: list[dict], org: str) -> str:
    rows = ""
    for pr in prs:
        repo = html.escape(pr["repo"])
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

        rows += f"""      <div class="flex items-start gap-3 px-4 py-3 border-b border-gray-200 hover:bg-gray-50">
        <div class="{pr_color} mt-0.5">{_SVG_PR}</div>
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-x-1">
            <a href="https://github.com/{html.escape(org)}/{repo}" class="text-sm font-semibold text-gray-700 hover:text-blue-600">{html.escape(org)}/{repo}</a>
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
    parser.add_argument("org", help="GitHub organization name")
    parser.add_argument("--output", choices=["html"], help="Output format (default: table)")
    args = parser.parse_args()

    prs = fetch_open_prs(token, args.org)

    if args.output == "html":
        filename = f"{args.org}_open_prs.html"
        with open(filename, "w") as f:
            f.write(render_html(prs, args.org))
        print(f"Wrote {filename}")
    else:
        print_table(prs)


if __name__ == "__main__":
    main()