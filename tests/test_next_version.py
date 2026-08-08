"""Version derivation, exercised against real git repositories.

Nothing here is mocked. Each test builds an actual repo, makes actual commits
and merges, and runs scripts/next_version.py as a subprocess exactly the way
promote.sh and the release workflows run it. A mocked git log would have
happily confirmed the two bugs these tests exist to prevent:

  * the base was the newest STABLE tag, so with beta on 1.6.7 and stable on
    1.0.0 a patch bump produced 1.0.1 -- a version lower than what testers
    already had installed.
  * a fast-forward merge leaves no merge commit, so the branch name is gone
    and the landing is invisible. The version then depended on how someone
    merged rather than on what they merged.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "next_version.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one commit on `main`."""
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "f").write_text("0")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "chore: initial")
    return r


def land(repo: Path, branch: str, *, ff: bool = False) -> None:
    """Create `branch`, commit on it, and merge it back into main."""
    git(repo, "checkout", "-q", "-b", branch)
    (repo / "f").write_text(branch)
    git(repo, "commit", "-qam", f"work on {branch}")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff" if ff else "--no-ff", "--no-edit", branch)


def next_version(repo: Path) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT),"--next"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def bump(repo: Path, kind: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--bump", kind],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def current(repo: Path) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT),"--current"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


class TestBaseNeverGoesBackwards:
    def test_a_beta_tag_outranks_an_older_stable_tag(self, repo):
        # The regression that shipped: stable 1.0.0, beta 1.6.7.
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        git(repo, "tag", "-a", "v1.6.7-beta.1", "-m", "b")
        assert current(repo) == "1.6.7"

    def test_stable_outranks_the_betas_that_led_to_it(self, repo):
        git(repo, "tag", "-a", "v2.0.0-beta.3", "-m", "b")
        git(repo, "tag", "-a", "v2.0.0", "-m", "s")
        assert current(repo) == "2.0.0"

    def test_no_tags_at_all_starts_from_zero(self, repo):
        assert current(repo) == "0.0.0"

    def test_the_result_is_never_below_the_newest_tag(self, repo):
        git(repo, "tag", "-a", "v1.6.7-beta.1", "-m", "b")
        land(repo, "fix/a")
        assert next_version(repo) == "1.6.8"


class TestEveryLandingMovesZ:
    """X and Y are a decision; Z is a consequence.

    Deciding that a set of landings amounts to a minor version, or to a
    release, is editorial. A script reading branch prefixes cannot make that
    judgement -- it can only guess consistently, which is what it used to do
    (feat/ -> minor) and what produced version numbers nobody had chosen.

    Z is automatic for the opposite reason: it is not a judgement. Something
    landed, so the number moves. It has to move, or the build matches a tag
    that already exists, is skipped as published, and never reaches a tester.
    """

    def test_a_fix_moves_z(self, repo):
        git(repo, "tag", "-a", "v2.0.0", "-m", "s")
        land(repo, "fix/parser")
        assert next_version(repo) == "2.0.1"

    def test_a_feature_also_moves_z_and_nothing_else(self, repo):
        # It used to bump the minor. Landing work is not the same event as
        # deciding the result is a minor version.
        git(repo, "tag", "-a", "v2.0.0", "-m", "s")
        land(repo, "feat/litgraph")
        assert next_version(repo) == "2.0.1"

    def test_order_no_longer_changes_the_answer(self, repo):
        # Previously a fix-then-feature gave a different number from a
        # feature-then-fix. With one rule for both, sequencing is irrelevant --
        # three landings are three landings.
        git(repo, "tag", "-a", "v2.0.0", "-m", "s")
        land(repo, "fix/a"); land(repo, "feat/b"); land(repo, "fix/c")
        assert next_version(repo) == "2.0.3"

    def test_several_landings_each_count_once(self, repo):
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        for b in ("feat/a", "feat/b", "feat/c"):
            land(repo, b)
        assert next_version(repo) == "1.0.3"

    def test_feature_and_hotfix_aliases_are_recognised(self, repo):
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        land(repo, "feature/x"); land(repo, "hotfix/y")
        assert next_version(repo) == "1.0.2"


class TestXAndYAreDeclared:
    """The bump a human asks for, and the carry that is not negotiable."""

    def test_minor_bumps_y_and_clears_z(self, repo):
        git(repo, "tag", "-a", "v2.0.7", "-m", "s")
        assert bump(repo, "minor") == "2.1.0"

    def test_major_bumps_x_and_clears_the_rest(self, repo):
        git(repo, "tag", "-a", "v2.4.7", "-m", "s")
        assert bump(repo, "major") == "3.0.0"

    def test_y_carries_into_x_at_ten(self, repo):
        # the whole point of the scheme: no version ever shows a two-digit Y
        git(repo, "tag", "-a", "v2.9.3", "-m", "s")
        assert bump(repo, "minor") == "3.0.0"

    def test_the_carry_holds_at_every_scale(self, repo):
        git(repo, "tag", "-a", "v9.9.9", "-m", "s")
        assert bump(repo, "minor") == "10.0.0"

    def test_a_declared_bump_always_increases(self, repo):
        # the property the updater depends on: a build must never advertise a
        # number lower than one already installed.
        for before, kind in [("2.0.9", "minor"), ("2.9.9", "minor"),
                             ("2.4.1", "major"), ("9.9.9", "minor")]:
            r = repo
            git(r, "tag", "-a", f"v{before}", "-m", "s", "-f")
            after = bump(r, kind)
            key = lambda v: tuple(int(x) for x in v.split("."))
            assert key(after) > key(before), f"{before} --bump {kind} -> {after}"

    def test_landings_do_not_move_y_however_many_there_are(self, repo):
        git(repo, "tag", "-a", "v2.0.0", "-m", "s")
        for i in range(12):
            land(repo, f"feat/thing-{i}")
        assert next_version(repo) == "2.0.12"


class TestWhatMustNotMoveTheVersion:
    def test_chore_and_docs_branches_are_ignored(self, repo):
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        land(repo, "chore/deps")
        land(repo, "docs/readme")
        assert next_version(repo) == "1.6.7"

    def test_direct_commits_do_not_count_even_with_a_fix_prefix(self, repo):
        # A merge is what "landing" means. Counting direct commits is how the
        # number drifted: every fix(ci): commit bumped the patch.
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        (repo / "f").write_text("x")
        git(repo, "commit", "-qam", "fix(ci): tweak the lint config")
        (repo / "f").write_text("y")
        git(repo, "commit", "-qam", "feat: something typed directly on the branch")
        assert next_version(repo) == "1.6.7"

    def test_a_fast_forward_merge_is_invisible(self, repo):
        # Documents the limitation the --no-ff rule exists to prevent. If this
        # ever starts returning 1.6.8, the merge strategy stopped mattering and
        # the --no-ff enforcement in promote.sh can be reconsidered.
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        land(repo, "fix/ff", ff=True)
        assert next_version(repo) == "1.6.7"

    def test_the_same_branch_merged_twice_counts_twice(self, repo):
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        land(repo, "fix/a")
        git(repo, "checkout", "-q", "fix/a")
        (repo / "g").write_text("more")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "more work")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "fix/a")
        assert next_version(repo) == "1.0.2"


class TestOnlyCountsSinceTheNewestTag:
    def test_landings_before_the_tag_are_not_recounted(self, repo):
        land(repo, "feat/old")
        land(repo, "fix/old")
        git(repo, "tag", "-a", "v3.0.0", "-m", "s")
        land(repo, "fix/new")
        assert next_version(repo) == "3.0.1"

    def test_a_new_tag_rebaselines_the_count(self, repo):
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        land(repo, "feat/a")
        assert next_version(repo) == "1.0.1"
        git(repo, "tag", "-a", "v1.0.1", "-m", "s")
        land(repo, "fix/b")
        assert next_version(repo) == "1.0.2"


class TestMergeSubjectFormats:
    def test_a_github_pull_request_merge_is_parsed(self, repo):
        git(repo, "tag", "-a", "v1.0.0", "-m", "s")
        git(repo, "checkout", "-q", "-b", "feat/via-pr")
        (repo / "f").write_text("pr")
        git(repo, "commit", "-qam", "work")
        git(repo, "checkout", "-q", "main")
        # exactly what GitHub writes when a PR is merged
        git(repo, "merge", "-q", "--no-ff", "-m",
            "Merge pull request #48 from get-thinkstack/feat/via-pr", "feat/via-pr")
        assert next_version(repo) == "1.0.1"


class TestWorkArrivingThroughAnotherBranch:
    """dev is where work lands; beta and main receive it as a single merge.

    Replaying with --first-parent from beta sees only "Merge branch 'dev'" --
    every feat/ and fix/ merge hangs off the second parent and is invisible.
    That made beta rebuild the version it had already published, so the update
    advertised a number testers already ran and was correctly never offered.
    """

    def test_a_fix_merged_via_dev_still_counts_on_beta(self, repo):
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        git(repo, "checkout", "-q", "-b", "dev")
        land(repo, "fix/parser")                      # fix/ -> dev
        git(repo, "checkout", "-q", "-b", "beta", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "dev")   # dev -> beta
        assert next_version(repo) == "1.6.8"

    def test_a_feature_merged_via_dev_still_counts_on_beta(self, repo):
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        git(repo, "checkout", "-q", "-b", "dev")
        land(repo, "feat/litgraph")
        git(repo, "checkout", "-q", "-b", "beta", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "dev")
        # Z, not Y: landing a feature is not the same event as declaring the
        # result a minor version. The point this test guards is that the
        # landing is SEEN at all through the dev merge, not which digit moves.
        assert next_version(repo) == "1.6.8"

    def test_the_dev_merge_itself_does_not_count(self, repo):
        # "Merge branch 'dev'" is not a feat/ or fix/ landing.
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        git(repo, "checkout", "-q", "-b", "dev")
        land(repo, "chore/tidy")
        git(repo, "checkout", "-q", "-b", "beta", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "dev")
        assert next_version(repo) == "1.6.7"

    def test_a_fix_is_not_counted_twice_when_it_reaches_beta(self, repo):
        # It is one merge commit, reachable once in the range.
        git(repo, "tag", "-a", "v1.6.7", "-m", "s")
        git(repo, "checkout", "-q", "-b", "dev")
        land(repo, "fix/one")
        git(repo, "checkout", "-q", "-b", "beta", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "dev")
        assert next_version(repo) == "1.6.8"   # not 1.6.9
