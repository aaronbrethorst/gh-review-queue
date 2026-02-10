# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A collection of standalone Python scripts for GitHub organization management tasks. Each script is a self-contained [uv inline script](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies) with embedded dependency metadata — no virtual environment or `requirements.txt` needed.

## Running Scripts

Scripts are executed directly via `uv run`:

```
GITHUB_TOKEN=ghp_xxx uv run gh_open_prs.py <org>
```

Each script declares its own dependencies in a PEP 723 `/// script` block at the top of the file. uv resolves and installs them automatically on first run.

## Conventions

- Python 3.12+ required
- Scripts use `#!/usr/bin/env -S uv --quiet run --script` shebang so they can also be run directly (`./script.py`)
- `GITHUB_TOKEN` environment variable provides GitHub API authentication
- GitHub API access uses GraphQL (`https://api.github.com/graphql`)
