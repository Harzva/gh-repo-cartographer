from pathlib import Path

import gh_repo_cartographer as cartographer


def test_normalize_repo_key_handles_common_github_remote_forms():
    cases = {
        "https://github.com/Harzva/gh-repo-cartographer.git": "harzva/gh-repo-cartographer",
        "http://github.com/Harzva/gh-repo-cartographer": "harzva/gh-repo-cartographer",
        "git@github.com:Harzva/gh-repo-cartographer.git": "harzva/gh-repo-cartographer",
        "ssh://git@github.com/Harzva/gh-repo-cartographer.git": "harzva/gh-repo-cartographer",
        "Harzva/gh-repo-cartographer": "harzva/gh-repo-cartographer",
    }

    for remote, expected in cases.items():
        assert cartographer.normalize_repo_key(remote) == expected


def test_normalize_repo_key_ignores_non_github_urls():
    assert cartographer.normalize_repo_key("https://gitlab.com/Harzva/example.git") is None
    assert cartographer.normalize_repo_key("not-enough-parts") is None
    assert cartographer.normalize_repo_key(None) is None


def test_unique_preserves_order_case_insensitively():
    assert cartographer.unique(["Harzva", "harzva", "saihao", "SaiHao"]) == ["Harzva", "saihao"]


def test_github_login_from_url_extracts_owner_login():
    assert cartographer.github_login_from_url("https://github.com/Just-Agent") == "Just-Agent"
    assert cartographer.github_login_from_url("https://github.com/Just-Agent/Just-Thumbnail") == "Just-Agent"
    assert cartographer.github_login_from_url("https://example.com/Just-Agent") is None


def test_discover_scan_roots_uses_existing_roots(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    existing = tmp_path / "repo-root"
    existing.mkdir()
    monkeypatch.delenv("GH_REPO_CARTOGRAPHER_ROOTS", raising=False)

    assert cartographer.discover_scan_roots([str(missing), str(existing), str(existing)]) == [existing.resolve()]


def test_render_markdown_includes_summary_and_unmatched_local_repo(tmp_path):
    inventory = {
        "remoteCount": 1,
        "pagesCount": 1,
        "releaseCount": 1,
        "localRepoCount": 1,
        "matchedRemoteCount": 0,
        "rows": [
            {
                "remote": {
                    "nameWithOwner": "Harzva/example",
                    "accountAlias": "harzva",
                    "isPrivate": False,
                    "pages": {"url": "https://harzva.github.io/example/"},
                    "release": {
                        "hasAnyRelease": True,
                        "latest": {"url": "https://github.com/Harzva/example/releases/tag/v1.0.0"},
                    },
                    "pushedAt": "2026-05-14T00:00:00Z",
                },
                "localMatches": [],
                "localStatus": "no-local-copy",
                "defaultBranch": "main",
            }
        ],
        "localOnly": [
            {
                "path": str(tmp_path),
                "branch": "main",
                "status": "synced",
                "remotes": [{"url": "https://github.com/other/example.git"}],
            }
        ],
    }

    markdown = cartographer.render_markdown(inventory, [Path(".")], fetched=False)

    assert "# GitHub Repo Cartography" in markdown
    assert "Harzva/example" in markdown
    assert "Repositories with GitHub Pages: 1" in markdown
    assert "Repositories with releases: 1" in markdown
    assert "https://harzva.github.io/example/" in markdown
    assert "https://github.com/Harzva/example/releases/tag/v1.0.0" in markdown
    assert "Local Repositories Without Managed GitHub Match" in markdown
