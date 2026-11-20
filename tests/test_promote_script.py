"""promote.sh must not tell its operator that a merge into main published.

A push to main builds nothing (ADR 2026-08-06); stable is scripts/ship.sh.
The script used to print "a fix ships to users immediately" and "tagged by
CI" for main, so an operator could walk away believing users had the fix.
"""

from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "scripts" / "promote.sh").read_text()


def test_it_never_claims_main_was_released():
    for claim in ("ships to users immediately", "tag the stable release", "tagging both"):
        assert claim not in SCRIPT, claim


def test_landing_on_main_is_not_reported_as_a_ci_release():
    assert 'released_by_ci "$MAIN_BRANCH"' not in SCRIPT


def test_it_points_at_ship_sh_for_stable():
    assert "scripts/ship.sh" in SCRIPT.split("# ── plan")[1]
