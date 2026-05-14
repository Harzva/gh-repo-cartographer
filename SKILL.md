---
name: gh-repo-cartographer
description: Inventory locally configured GitHub accounts and repositories, map online GitHub repositories to local Git project folders, verify whether local branches match fetched upstream commits, and produce Markdown/JSON reports for README optimization, repository cleanup, publishing audits, or account migration work. Use when the user asks to list all GitHub repos, find local project locations for GitHub repos, check local-vs-remote version status, audit README targets, or organize repos across Harzva/saihao/Just-Agent style managed accounts.
---

# GH Repo Cartographer

## Quick Start

Use the bundled script for deterministic inventory work. From this skill or repository directory:

```powershell
python scripts\gh_repo_cartographer.py --output github-repo-map.md --json-output github-repo-map.json
```

The script:

- Reads managed account aliases from `gh-account-router` when available.
- Resolves each alias to its canonical GitHub login with `gh api user`.
- Lists repositories owned by each resolved login, with a REST API fallback when `gh repo list` GraphQL calls time out.
- Scans local Git repositories under configured roots.
- Matches local remotes to `github.com/owner/repo`.
- Fetches remotes by default, then compares `HEAD` with `@{u}` to report `synced`, `behind`, `ahead`, `diverged`, `no-upstream`, or `no-local-copy`.

## Common Options

- Add scan roots with repeated `--scan-root <path>`. If omitted, the script uses `GH_REPO_CARTOGRAPHER_ROOTS` when set, otherwise the current directory.
- Add account aliases with repeated `--account <alias>`. If omitted, aliases are discovered from `gh-account-router`.
- Set `GH_ACCOUNT_ROUTER` when `gh-account-router` is installed somewhere other than `~/.codex/skills/gh-account-router/scripts/gh_account_router.py`.
- Use `--no-fetch` only when the user explicitly wants a faster offline check; mark results as based on stale local remote refs.
- Use `--max-depth <n>` to widen or narrow local scanning.
- Use `--output <file>` for a Markdown report and `--json-output <file>` for downstream README automation.

## Reporting Guidance

Summarize the Markdown report in the final answer:

- Number of remote repositories found.
- Number matched to local folders.
- Repositories that are `behind`, `ahead`, `diverged`, dirty, or missing local copies.
- Local repositories with GitHub remotes outside the managed accounts.
- The report paths created.

Never print raw tokens or access-file contents. If authentication fails, report the account alias/login and the GitHub error after token redaction.

## README Optimization Workflow

After generating the map, use it to prioritize README work:

1. Start with repositories that have local matches and are `synced`.
2. For `behind` or `diverged` repos, ask before editing README content unless the user clearly asked to update local branches.
3. For `no-local-copy` repos, recommend cloning before README optimization.
4. Use the JSON report when batching README audits or generating dashboards.
