#!/usr/bin/env python3
"""Inventory managed GitHub repositories and map them to local Git checkouts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROUTER = Path(
    os.environ.get(
        "GH_ACCOUNT_ROUTER",
        Path.home() / ".codex" / "skills" / "gh-account-router" / "scripts" / "gh_account_router.py",
    )
)
DEFAULT_SCAN_ROOTS = [Path.cwd()]
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".cache",
}
TOKEN_IN_TEXT_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)")


@dataclass
class LocalRemote:
    name: str
    url: str
    repo_key: str | None


@dataclass
class LocalRepo:
    path: Path
    branch: str | None = None
    head: str | None = None
    remotes: list[LocalRemote] = field(default_factory=list)
    upstream: str | None = None
    upstream_sha: str | None = None
    ahead: int | None = None
    behind: int | None = None
    dirty: bool = False
    status: str = "unknown"
    error: str | None = None


def redact(text: str) -> str:
    return TOKEN_IN_TEXT_RE.sub("[REDACTED_TOKEN]", text)


def run(cmd: list[str], cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(redact(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(cmd)}"))
    return proc


def is_transient_network_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            "timeout",
            "tls handshake",
            "connection reset",
            "connection refused",
            "503",
            "502",
            "504",
        ]
    )


def gh(account: str | None, args: list[str], retries: int = 2) -> subprocess.CompletedProcess[str]:
    if account and ROUTER.exists():
        cmd = [sys.executable, str(ROUTER), "--account", account, "--", *args]
    else:
        cmd = ["gh", *args]

    proc = run(cmd)
    attempt = 0
    while proc.returncode != 0 and attempt < retries and is_transient_network_error(proc.stderr + proc.stdout):
        attempt += 1
        time.sleep(1.5 * attempt)
        proc = run(cmd)
    return proc


def github_login_from_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else None


def parse_router_account_hints() -> dict[str, str]:
    if not ROUTER.exists():
        return {}
    proc = run([sys.executable, str(ROUTER), "--list"])
    if proc.returncode != 0:
        return {}

    hints: dict[str, str] = {}
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        parts = [part.strip() for part in line[1:].split(",") if part.strip()]
        login_hint: str | None = None
        aliases: list[str] = []
        for part in parts:
            if part.startswith(("http://", "https://")):
                login_hint = github_login_from_url(part)
            else:
                aliases.append(part)
        if login_hint:
            for alias in aliases:
                hints[alias.lower()] = login_hint
    return hints


def parse_router_accounts() -> list[str]:
    if not ROUTER.exists():
        return []
    proc = run([sys.executable, str(ROUTER), "--list"])
    if proc.returncode != 0:
        return []

    accounts: list[str] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        aliases = [part.strip() for part in line[1:].split(",") if part.strip()]
        simple_aliases = [alias for alias in aliases if not alias.startswith(("http://", "https://"))]
        if simple_aliases:
            accounts.append(simple_aliases[-1])
    return unique(accounts)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def normalize_repo_key(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    if value.startswith("git@github.com:"):
        path = value.split(":", 1)[1]
    elif value.startswith("ssh://git@github.com/"):
        path = value.split("ssh://git@github.com/", 1)[1]
    elif value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        if parsed.netloc.lower() != "github.com":
            return None
        path = parsed.path.lstrip("/")
    else:
        path = value

    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    return f"{parts[0].lower()}/{parts[1].lower()}"


def discover_scan_roots(values: list[str]) -> list[Path]:
    raw_roots: list[str] = []
    env_roots = os.environ.get("GH_REPO_CARTOGRAPHER_ROOTS")
    if env_roots:
        raw_roots.extend([part for part in env_roots.split(os.pathsep) if part.strip()])
    raw_roots.extend(values)
    if not raw_roots:
        raw_roots.extend(str(path) for path in DEFAULT_SCAN_ROOTS)

    roots: list[Path] = []
    for raw in raw_roots:
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        if resolved.exists() and resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def find_git_roots(scan_roots: list[Path], max_depth: int) -> list[Path]:
    repos: set[Path] = set()
    for root in scan_roots:
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - base_depth
            has_git_marker = ".git" in dirs or ".git" in files
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".cache")]
            if depth >= max_depth:
                dirs[:] = []

            if has_git_marker:
                repo_root_proc = run(["git", "rev-parse", "--show-toplevel"], cwd=current_path)
                if repo_root_proc.returncode == 0:
                    repos.add(Path(repo_root_proc.stdout.strip()).resolve())
    return sorted(repos, key=lambda p: str(p).lower())


def git_output(repo: Path, args: list[str]) -> str | None:
    proc = run(["git", *args], cwd=repo)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def inspect_local_repo(path: Path, fetch: bool) -> LocalRepo:
    info = LocalRepo(path=path)
    try:
        if fetch:
            run(["git", "fetch", "--all", "--prune", "--quiet"], cwd=path)

        info.branch = git_output(path, ["branch", "--show-current"])
        info.head = git_output(path, ["rev-parse", "HEAD"])
        info.upstream = git_output(path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        info.upstream_sha = git_output(path, ["rev-parse", "@{u}"]) if info.upstream else None

        remote_text = git_output(path, ["remote", "-v"]) or ""
        seen_remotes: set[tuple[str, str]] = set()
        for line in remote_text.splitlines():
            parts = line.split()
            if len(parts) < 2 or "(fetch)" not in line:
                continue
            key = (parts[0], parts[1])
            if key in seen_remotes:
                continue
            seen_remotes.add(key)
            info.remotes.append(LocalRemote(parts[0], parts[1], normalize_repo_key(parts[1])))

        dirty_text = git_output(path, ["status", "--porcelain"]) or ""
        info.dirty = bool(dirty_text.strip())

        if info.upstream:
            counts = git_output(path, ["rev-list", "--left-right", "--count", "HEAD...@{u}"])
            if counts:
                left, right = counts.split()[:2]
                info.ahead = int(left)
                info.behind = int(right)
                if info.ahead == 0 and info.behind == 0:
                    info.status = "synced"
                elif info.ahead and info.behind:
                    info.status = "diverged"
                elif info.ahead:
                    info.status = "ahead"
                elif info.behind:
                    info.status = "behind"
        else:
            info.status = "no-upstream"
    except Exception as exc:
        info.status = "error"
        info.error = str(exc)
    return info


def repo_json_fields() -> str:
    return ",".join(
        [
            "nameWithOwner",
            "url",
            "description",
            "isPrivate",
            "isArchived",
            "isFork",
            "primaryLanguage",
            "pushedAt",
            "updatedAt",
            "defaultBranchRef",
        ]
    )


def list_remote_repos_rest(account: str) -> tuple[list[dict[str, Any]], str | None]:
    jq = (
        ".[] | {"
        "nameWithOwner:.full_name,"
        "url:.html_url,"
        "description:.description,"
        "isPrivate:.private,"
        "isArchived:.archived,"
        "isFork:.fork,"
        "primaryLanguage:(if .language == null then null else {name:.language} end),"
        "pushedAt:.pushed_at,"
        "updatedAt:.updated_at,"
        "defaultBranchRef:{name:.default_branch}"
        "}"
    )
    proc = gh(account, ["api", "--paginate", "/user/repos?affiliation=owner&per_page=100", "--jq", jq])
    if proc.returncode != 0:
        return [], redact(proc.stderr.strip() or proc.stdout.strip())

    repos: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        repos.append(json.loads(line))
    return repos, None


def list_remote_repos_public(login: str) -> tuple[list[dict[str, Any]], str | None]:
    proc = gh(None, ["api", f"/users/{login}/repos?per_page=100&type=owner&sort=pushed"])
    if proc.returncode != 0:
        return [], redact(proc.stderr.strip() or proc.stdout.strip())
    repo_items = json.loads(proc.stdout or "[]")
    repos: list[dict[str, Any]] = []
    for repo in repo_items:
        repos.append(
            {
                "nameWithOwner": repo.get("full_name"),
                "url": repo.get("html_url"),
                "description": repo.get("description"),
                "isPrivate": repo.get("private"),
                "isArchived": repo.get("archived"),
                "isFork": repo.get("fork"),
                "primaryLanguage": {"name": repo.get("language")} if repo.get("language") else None,
                "pushedAt": repo.get("pushed_at"),
                "updatedAt": repo.get("updated_at"),
                "defaultBranchRef": {"name": repo.get("default_branch")},
                "homepageUrl": repo.get("homepage"),
                "stargazerCount": repo.get("stargazers_count"),
                "forkCount": repo.get("forks_count"),
                "topics": repo.get("topics", []),
            }
        )
    return repos, None


def gh_json(account: str | None, path: str, none_on_404: bool = False) -> Any:
    proc = gh(account, ["api", path])
    if proc.returncode != 0:
        output = proc.stderr + proc.stdout
        if none_on_404 and ("HTTP 404" in output or '"status":"404"' in output or '"status":"409"' in output):
            return None
        if account:
            proc = gh(None, ["api", path])
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout)
            output = proc.stderr + proc.stdout
            if none_on_404 and ("HTTP 404" in output or '"status":"404"' in output or '"status":"409"' in output):
                return None
        return None
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def fetch_pages(account: str | None, name_with_owner: str) -> dict[str, Any] | None:
    pages = gh_json(account, f"/repos/{name_with_owner}/pages", none_on_404=True)
    if not pages:
        return None
    return {
        "url": pages.get("html_url"),
        "status": pages.get("status"),
        "cname": pages.get("cname"),
        "custom404": pages.get("custom_404"),
        "source": pages.get("source"),
        "buildType": pages.get("build_type"),
    }


def fetch_release(account: str | None, name_with_owner: str) -> dict[str, Any]:
    latest = gh_json(account, f"/repos/{name_with_owner}/releases/latest", none_on_404=True)
    sample = gh_json(account, f"/repos/{name_with_owner}/releases?per_page=1", none_on_404=True) or []
    return {
        "hasAnyRelease": bool(latest or sample),
        "latest": None
        if not latest
        else {
            "name": latest.get("name"),
            "tagName": latest.get("tag_name"),
            "url": latest.get("html_url"),
            "publishedAt": latest.get("published_at"),
            "prerelease": latest.get("prerelease"),
            "draft": latest.get("draft"),
        },
    }


def enrich_remote_metadata(remote_repos: list[dict[str, Any]], include_pages: bool, include_releases: bool) -> None:
    if not include_pages and not include_releases:
        return
    for repo in remote_repos:
        account = repo.get("accountAlias")
        name_with_owner = repo.get("nameWithOwner")
        if not name_with_owner:
            continue
        if include_pages:
            repo["pages"] = fetch_pages(account, name_with_owner)
        if include_releases:
            repo["release"] = fetch_release(account, name_with_owner)


def list_remote_repos(accounts: list[str]) -> list[dict[str, Any]]:
    remotes: list[dict[str, Any]] = []
    seen: set[str] = set()
    router_hints = parse_router_account_hints()

    for account in accounts:
        user_proc = gh(account, ["api", "user", "--jq", ".login"])
        if user_proc.returncode != 0:
            login = router_hints.get(account.lower())
            if not login:
                public_repos, public_error = list_remote_repos_public(account)
                if public_error:
                    print(f"warning: cannot resolve GitHub login for {account}: {redact(user_proc.stderr.strip())}", file=sys.stderr)
                    continue
                login = account
                repo_items = public_repos
            else:
                repo_items, public_error = list_remote_repos_public(login)
                if public_error:
                    print(f"warning: cannot list repos for {login}: {public_error}", file=sys.stderr)
                    continue
        else:
            login = user_proc.stdout.strip()
            repo_proc = gh(
                account,
                [
                    "repo",
                    "list",
                    login,
                    "--limit",
                    "1000",
                    "--json",
                    repo_json_fields(),
                ],
            )
            if repo_proc.returncode != 0:
                fallback_repos, fallback_error = list_remote_repos_rest(account)
                if fallback_error:
                    public_repos, public_error = list_remote_repos_public(login)
                    if public_error:
                        print(f"warning: cannot list repos for {login}: {fallback_error}", file=sys.stderr)
                        continue
                    repo_items = public_repos
                else:
                    repo_items = fallback_repos
            else:
                repo_items = json.loads(repo_proc.stdout or "[]")

        for repo in repo_items:
            key = normalize_repo_key(repo.get("nameWithOwner"))
            if not key or key in seen:
                continue
            seen.add(key)
            repo["accountAlias"] = account
            repo["accountLogin"] = login
            repo["repoKey"] = key
            remotes.append(repo)

    return sorted(remotes, key=lambda item: item["nameWithOwner"].lower())


def local_to_json(local: LocalRepo) -> dict[str, Any]:
    return {
        "path": str(local.path),
        "branch": local.branch,
        "head": local.head,
        "upstream": local.upstream,
        "upstreamSha": local.upstream_sha,
        "ahead": local.ahead,
        "behind": local.behind,
        "dirty": local.dirty,
        "status": local.status,
        "error": local.error,
        "remotes": [
            {"name": remote.name, "url": remote.url, "repoKey": remote.repo_key}
            for remote in local.remotes
        ],
    }


def merge_inventory(remote_repos: list[dict[str, Any]], local_repos: list[LocalRepo]) -> dict[str, Any]:
    locals_by_key: dict[str, list[LocalRepo]] = {}
    for local in local_repos:
        for remote in local.remotes:
            if remote.repo_key:
                locals_by_key.setdefault(remote.repo_key, []).append(local)

    rows: list[dict[str, Any]] = []
    for repo in remote_repos:
        matches = locals_by_key.get(repo["repoKey"], [])
        default_branch = repo.get("defaultBranchRef") or {}
        rows.append(
            {
                "remote": repo,
                "localMatches": [local_to_json(match) for match in matches],
                "localStatus": matches[0].status if matches else "no-local-copy",
                "defaultBranch": default_branch.get("name"),
            }
        )

    local_only: list[dict[str, Any]] = []
    remote_keys = {repo["repoKey"] for repo in remote_repos}
    for local in local_repos:
        if not any(remote.repo_key in remote_keys for remote in local.remotes if remote.repo_key):
            local_only.append(local_to_json(local))

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "remoteCount": len(remote_repos),
        "pagesCount": sum(1 for repo in remote_repos if repo.get("pages")),
        "releaseCount": sum(1 for repo in remote_repos if (repo.get("release") or {}).get("hasAnyRelease")),
        "localRepoCount": len(local_repos),
        "matchedRemoteCount": sum(1 for row in rows if row["localMatches"]),
        "rows": rows,
        "localOnly": local_only,
    }


def cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text


def render_markdown(inventory: dict[str, Any], scan_roots: list[Path], fetched: bool) -> str:
    rows = inventory["rows"]
    has_pages_column = any((row["remote"].get("pages") for row in rows))
    has_release_column = any(((row["remote"].get("release") or {}).get("hasAnyRelease") for row in rows))
    headers = ["Repository", "Account", "Visibility"]
    if has_pages_column:
        headers.append("Pages")
    if has_release_column:
        headers.append("Release")
    headers.extend(["Local path", "Branch", "Sync", "Ahead", "Behind", "Dirty", "Last pushed"])
    summary = [
        "# GitHub Repo Cartography",
        "",
        f"- Remote repositories: {inventory['remoteCount']}",
        f"- Repositories with GitHub Pages: {inventory.get('pagesCount', 0)}",
        f"- Repositories with releases: {inventory.get('releaseCount', 0)}",
        f"- Local Git repositories scanned: {inventory['localRepoCount']}",
        f"- Remote repositories with local matches: {inventory['matchedRemoteCount']}",
        f"- Version check used fetch: {'yes' if fetched else 'no'}",
        f"- Scan roots: {', '.join(str(root) for root in scan_roots)}",
        "",
        "## Remote to Local Map",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        remote = row["remote"]
        matches = row["localMatches"] or [None]
        for index, local in enumerate(matches):
            repo_name = remote["nameWithOwner"] if index == 0 else ""
            visibility = "private" if remote.get("isPrivate") else "public"
            values = [
                cell(repo_name),
                cell(remote.get("accountAlias")),
                cell(visibility),
            ]
            if has_pages_column:
                pages = remote.get("pages")
                values.append(cell(pages.get("url") if pages else ""))
            if has_release_column:
                release = remote.get("release") or {}
                latest = release.get("latest") or {}
                values.append(cell(latest.get("url") if latest else "yes" if release.get("hasAnyRelease") else ""))
            values.extend(
                [
                    cell(local.get("path") if local else ""),
                    cell(local.get("branch") if local else row.get("defaultBranch")),
                    cell(local.get("status") if local else "no-local-copy"),
                    cell(local.get("ahead") if local else ""),
                    cell(local.get("behind") if local else ""),
                    cell("yes" if local and local.get("dirty") else "no" if local else ""),
                    cell(remote.get("pushedAt")),
                ]
            )
            summary.append(
                "| " + " | ".join(values) + " |"
            )

    if inventory["localOnly"]:
        summary.extend(
            [
                "",
                "## Local Repositories Without Managed GitHub Match",
                "",
                "| Local path | Branch | Sync | Remotes |",
                "|---|---|---:|---|",
            ]
        )
        for local in inventory["localOnly"]:
            remotes = ", ".join(remote["url"] for remote in local["remotes"])
            summary.append(
                "| "
                + " | ".join(
                    [
                        cell(local["path"]),
                        cell(local.get("branch")),
                        cell(local.get("status")),
                        cell(remotes),
                    ]
                )
                + " |"
            )

    summary.append("")
    return "\n".join(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", action="append", help="Managed account alias to query. Repeatable.")
    parser.add_argument("--scan-root", action="append", default=[], help="Directory to scan for local Git repositories. Repeatable.")
    parser.add_argument("--max-depth", type=int, default=6, help="Maximum directory depth to scan under each root.")
    parser.add_argument("--no-fetch", action="store_true", help="Skip git fetch before comparing local and upstream commits.")
    parser.add_argument("--include-pages", action="store_true", help="Fetch GitHub Pages status and public URL for each repository.")
    parser.add_argument("--include-releases", action="store_true", help="Fetch latest release metadata for each repository.")
    parser.add_argument("--output", help="Write Markdown report to this path instead of stdout.")
    parser.add_argument("--json-output", help="Write machine-readable JSON inventory to this path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    accounts = unique(args.account or parse_router_accounts())
    if not accounts:
        print("error: no managed GitHub accounts found. Pass --account or configure gh-account-router.", file=sys.stderr)
        return 2

    scan_roots = discover_scan_roots(args.scan_root)
    if not scan_roots:
        print("error: no scan roots exist. Pass --scan-root.", file=sys.stderr)
        return 2

    remote_repos = list_remote_repos(accounts)
    enrich_remote_metadata(remote_repos, include_pages=args.include_pages, include_releases=args.include_releases)
    git_roots = find_git_roots(scan_roots, args.max_depth)
    local_repos = [inspect_local_repo(path, fetch=not args.no_fetch) for path in git_roots]
    inventory = merge_inventory(remote_repos, local_repos)
    markdown = render_markdown(inventory, scan_roots, fetched=not args.no_fetch)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
