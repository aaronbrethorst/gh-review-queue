#!/usr/bin/env -S uv --quiet run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "requests",
# ]
# ///

"""
List all open pull requests for a GitHub organization.

Usage:
    GITHUB_TOKEN=ghp_xxx uv run gh_open_prs.py OneBusAway

Environment variables:
    GITHUB_TOKEN - GitHub personal access token with repo scope
"""

import os
import sys
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


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print(f"Usage: uv run {sys.argv[0]} <org>", file=sys.stderr)
        sys.exit(1)

    org = sys.argv[1]
    prs = fetch_open_prs(token, org)
    print_table(prs)


if __name__ == "__main__":
    main()