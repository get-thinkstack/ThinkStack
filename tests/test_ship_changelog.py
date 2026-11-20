"""scripts/_ship_changelog.sh, run by ship.sh before beta is merged into main.

It renames CHANGELOG's `[Unreleased]` to the version being shipped, on beta,
and carries the same commit to dev by cherry-pick (never a backwards merge).
Before this, only the unused release.sh promoted the changelog, so it never
happened. Known cost, accepted: an entry added on dev in the window before the
next dev -> beta merge conflicts there (ADR 2026-11-20).

Runs the real script against throwaway repositories with a bare "origin".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "_ship_changelog.sh"
CHANGELOG = ("# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Encryption covers the PDF.\n\n"
             "## [2.3.5] - 2026-08-15\n\n- Old.\n")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "dev", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "CHANGELOG.md").write_text(CHANGELOG)
    git(work, "add", ".")
    git(work, "commit", "-qm", "init")
    git(work, "push", "-q", "origin", "HEAD:refs/heads/dev")
    git(work, "push", "-q", "origin", "HEAD:refs/heads/beta")
    return work


def run_step(work, version="2.4.0"):
    return subprocess.run(["bash", str(SCRIPT), version], cwd=work, text=True,
                          capture_output=True)


def changelog_on(work, branch):
    git(work, "fetch", "-q", "origin")
    return git(work, "show", f"origin/{branch}:CHANGELOG.md")


def test_beta_gets_the_version_section(repo):
    r = run_step(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    text = changelog_on(repo, "beta")
    section = text.split("## [2.4.0]")[1].split("## [2.3.5]")[0]
    assert "- Encryption covers the PDF." in section
    assert text.index("## [Unreleased]") < text.index("## [2.4.0]")


def test_dev_gets_the_same_change(repo):
    run_step(repo)
    assert "## [2.4.0]" in changelog_on(repo, "dev")


def test_the_next_promotion_merges_cleanly_when_dev_added_no_entry(repo):
    run_step(repo)
    git(repo, "checkout", "-q", "-B", "dev", "origin/dev")
    (repo / "code.py").write_text("x = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "next")
    git(repo, "checkout", "-q", "-B", "beta", "origin/beta")
    merged = subprocess.run(["git", "merge", "--no-ff", "--no-edit", "dev"], cwd=repo,
                            capture_output=True, text=True)
    assert merged.returncode == 0, merged.stdout + merged.stderr


def test_nothing_pending_makes_no_commit(repo):
    run_step(repo)
    before = git(repo, "rev-parse", "origin/beta")
    assert run_step(repo, "2.4.1").returncode == 0
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/beta") == before
