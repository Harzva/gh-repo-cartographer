<div align="center">

# GH Repo Cartographer

Map your GitHub repositories to local project folders, then see which checkouts are synced, ahead, behind, diverged, dirty, or missing.

[![CI](https://github.com/Harzva/gh-repo-cartographer/actions/workflows/ci.yml/badge.svg)](https://github.com/Harzva/gh-repo-cartographer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Codex Skill](https://img.shields.io/badge/Codex-Skill-111827)](SKILL.md)

</div>

## Why This Exists

Developers who maintain many GitHub repositories often lose track of three things:

- which online repositories have local checkouts;
- which local folders are ahead, behind, diverged, dirty, or missing upstreams;
- which local Git repositories point outside the managed GitHub accounts.

GH Repo Cartographer produces a Markdown report for humans and a JSON report for downstream automation. It is especially useful before README cleanup, repository migration, account audits, or bulk maintenance across multiple GitHub accounts.

## Preview

```text
# GitHub Repo Cartography

- Remote repositories: 42
- Local Git repositories scanned: 31
- Remote repositories with local matches: 28
- Version check used fetch: yes

| Repository | Account | Visibility | Local path | Branch | Sync | Ahead | Behind | Dirty |
|---|---|---|---|---|---:|---:|---:|---:|
| Harzva/example | harzva | public | D:\code\example | main | synced | 0 | 0 | no |
```

## Features

| Capability | What it does |
|---|---|
| GitHub inventory | Lists repositories owned by one or more authenticated GitHub accounts. |
| Local discovery | Scans configured roots for Git working trees while skipping heavy folders like `node_modules`, `.venv`, `dist`, and `build`. |
| Remote matching | Normalizes common GitHub remote URL formats and maps them to `owner/repo`. |
| Sync status | Optionally fetches remotes, then reports `synced`, `behind`, `ahead`, `diverged`, `no-upstream`, `error`, or `no-local-copy`. |
| Dual output | Writes a readable Markdown table and a structured JSON file. |
| Codex Skill ready | Includes `SKILL.md` and `agents/openai.yaml` for installing as a local Codex skill. |

## Quick Start

```powershell
git clone https://github.com/Harzva/gh-repo-cartographer.git
cd gh-repo-cartographer
python scripts/gh_repo_cartographer.py --account harzva --scan-root C:\path\to\projects --output github-repo-map.md --json-output github-repo-map.json
```

If you use the companion `gh-account-router` skill, GH Repo Cartographer will automatically look for it at:

```text
~/.codex/skills/gh-account-router/scripts/gh_account_router.py
```

You can override that path:

```powershell
$env:GH_ACCOUNT_ROUTER = "C:\path\to\gh_account_router.py"
```

Without `gh-account-router`, the script falls back to your active `gh` CLI authentication.

## CLI Usage

```powershell
python scripts/gh_repo_cartographer.py `
  --account harzva `
  --account saihao `
  --scan-root C:\path\to\projects `
  --max-depth 6 `
  --output github-repo-map.md `
  --json-output github-repo-map.json
```

Common options:

| Option | Purpose |
|---|---|
| `--account <alias>` | Query a managed account alias. Repeat for multiple accounts. |
| `--scan-root <path>` | Scan a local directory for Git repositories. Repeat for multiple roots. |
| `--max-depth <n>` | Limit recursive scanning depth under each root. |
| `--no-fetch` | Skip `git fetch --all --prune --quiet` for faster offline checks. |
| `--output <file>` | Write the Markdown report. |
| `--json-output <file>` | Write machine-readable inventory JSON. |

You can also set scan roots through an environment variable:

```powershell
$env:GH_REPO_CARTOGRAPHER_ROOTS = "C:\path\to\projects;D:\work"
```

Use the platform path separator for your shell: `;` on Windows PowerShell and `:` on macOS/Linux shells.

## Install As A Codex Skill

Copy or clone this repository into your Codex skills directory:

```powershell
git clone https://github.com/Harzva/gh-repo-cartographer.git "$HOME\.codex\skills\gh-repo-cartographer"
```

Then ask Codex to use:

```text
$gh-repo-cartographer
```

The skill prompt is defined in `SKILL.md`, and the app-facing metadata is in `agents/openai.yaml`.

## Output Model

The JSON report contains:

- `generatedAt`: UTC timestamp for the report;
- `remoteCount`, `localRepoCount`, `matchedRemoteCount`: top-level counts;
- `rows`: remote repositories and any local matches;
- `localOnly`: local Git repositories that do not match the managed GitHub account inventory.

Each local match includes branch, `HEAD`, upstream, ahead/behind counts, dirty state, remote URLs, and sync status.

## Development

```powershell
python -m pip install -e ".[dev]"
pytest -q
```

The project has no runtime Python dependencies beyond the standard library. Tests cover URL normalization, root discovery, ordering behavior, and Markdown rendering.

## Safety

- Tokens are never printed intentionally; token-like strings in command output are redacted.
- Git remotes should stay as normal credential-free HTTPS or SSH URLs.
- Generated reports are ignored by default because local paths and private repository names may be sensitive.
- Use `--no-fetch` when you need a read-only local check without network Git fetches.

## Roadmap

- Add richer JSON schema documentation.
- Add optional CSV output for spreadsheet audits.
- Add repository topic and license summaries.
- Add a compact terminal table for quick interactive checks.

## License

MIT License. See [LICENSE](LICENSE).
