# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A collection of standalone Python scripts for GitHub organization management tasks. Each script is a self-contained [uv inline script](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies) with embedded dependency metadata — no virtual environment or `requirements.txt` needed.

## Running Scripts

Scripts are executed directly via `uv run` or the shebang (`./script.py`). Each script declares its own dependencies in a PEP 723 `/// script` block at the top of the file. uv resolves and installs them automatically on first run.

### gh_review_queue.py

Lists all open pull requests for a GitHub organization.

```
./gh_review_queue.py OneBusAway
./gh_review_queue.py --config settings.json
./gh_review_queue.py --config settings.json --output html
./gh_review_queue.py OneBusAway --ignore "repo-a, repo-b"
```

- `--config <file>` — JSON config file with keys: `org`, `output`, `ignore` (array of repo names)
- `--output html` — Generate a Tailwind-styled HTML report (`<org>_review_queue.html`)
- `--ignore <list>` — Comma-separated repo names to exclude
- CLI args override values from the config file

## Conventions

- Python 3.12+ required
- `GITHUB_TOKEN` is read from the environment or a `.env` file (via python-dotenv)
- GitHub API access uses GraphQL (`https://api.github.com/graphql`)
