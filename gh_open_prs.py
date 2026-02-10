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
            title
            url
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
                all_prs.append(
                    {
                        "repo": repo["name"],
                        "title": pr["title"],
                        "url": pr["url"],
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


def render_html(prs: list[dict], org: str) -> str:
    rows = ""
    for pr in prs:
        repo = html.escape(pr["repo"])
        title = html.escape(pr["title"])
        url = html.escape(pr["url"])
        rows += f"""            <tr class="border-b border-gray-200 hover:bg-gray-50">
              <td class="px-4 py-3 text-sm text-gray-700">{repo}</td>
              <td class="px-4 py-3 text-sm"><a href="{url}" class="text-blue-600 hover:underline">{title}</a></td>
            </tr>
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
    <div class="max-w-4xl mx-auto">
      <h1 class="text-3xl font-bold mb-1">{html.escape(org)}</h1>
      <p class="text-gray-500 mb-6">{len(prs)} open pull request{"" if len(prs) == 1 else "s"}</p>
      {empty_msg}
      <table class="w-full bg-white rounded-lg shadow overflow-hidden">
        <thead>
          <tr class="bg-gray-100 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
            <th class="px-4 py-3">Repo</th>
            <th class="px-4 py-3">Pull Request</th>
          </tr>
        </thead>
        <tbody>
{rows}        </tbody>
      </table>
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