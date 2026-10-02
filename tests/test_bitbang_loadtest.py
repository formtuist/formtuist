"""Tests for the bitbang admission load test in scripts.bitbang_loadtest."""

import asyncio
import contextlib
import functools
import io

import pytest
from bitbang import adapter as bitbang_adapter

from formtuist import publisher
from scripts.bitbang_loadtest import (
    FakePeerConnection,
    Result,
    report,
    run_all,
)

# a class-sized burst, and a group small enough that stock bitbang refuses
# nobody, so both branches of the verdict are exercised
CLASS_SIZE = 30
SMALL_GROUP = 5
CLIENT_COUNTS = (SMALL_GROUP, CLASS_SIZE)
ABANDONED = 10
CAPACITY = bitbang_adapter.MAX_UNAUTH_PEERS
SUCCESS_VERDICT = "RESULT: reproduced the defect, and the fix removes it."
FAILURE_VERDICT = "RESULT: unexpected numbers"
SUCCESS_CODE = 0
FAILURE_CODE = 1
SCENARIOS = ("burst", "burst+auth", "stuck", "reaped")
KINDS = ("baseline", "fixed")


@functools.cache
def load_test_results(clients: int) -> dict[str, dict[str, Result]]:
    """Run every load-test scenario once per client count and cache it."""
    # each run sleeps through the abandoned-session scenarios, so the tests
    # below share one read-only result rather than repeating it; every
    # adapter the load test builds uses an ephemeral identity, so nothing is
    # read from or written to the home directory
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(bitbang_adapter, "RTCPeerConnection", FakePeerConnection)
        return asyncio.run(run_all(clients, ABANDONED, publisher))


def report_quietly(
    results: dict[str, dict[str, Result]], clients: int
) -> tuple[int, str]:
    """Run the report and return its exit code and printed text."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = report(results, clients)
    return code, buffer.getvalue()


def results_with_burst_rejections(
    baseline: int, fixed: int
) -> dict[str, dict[str, Result]]:
    """Build results in which each burst refuses the given number."""
    results: dict[str, dict[str, Result]] = {}
    for kind, rejected in zip(KINDS, (baseline, fixed), strict=True):
        results[kind] = {name: Result(name) for name in SCENARIOS}
        burst = results[kind]["burst"]
        burst.offered = CLASS_SIZE
        burst.admitted = CLASS_SIZE - rejected
    return results


class TestLoadTestScenarios:
    """The load test must show the defect in stock bitbang and not the fix."""

    @pytest.mark.parametrize("clients", CLIENT_COUNTS)
    def test_stock_bitbang_refuses_the_overflow_of_a_burst(
        self, clients: int
    ) -> None:
        """Stock bitbang admits only as many setups as its cap allows."""
        results = load_test_results(clients)
        overflow = max(0, clients - CAPACITY)
        assert results["baseline"]["burst"].rejected == overflow
        assert results["baseline"]["burst+auth"].rejected == overflow

    @pytest.mark.parametrize("clients", CLIENT_COUNTS)
    def test_the_fix_admits_and_authenticates_the_whole_burst(
        self, clients: int
    ) -> None:
        """Every visitor in a burst is admitted and can authenticate."""
        results = load_test_results(clients)
        assert results["fixed"]["burst"].rejected == 0
        assert results["fixed"]["burst+auth"].rejected == 0
        assert results["fixed"]["burst+auth"].authenticated == clients

    @pytest.mark.parametrize("clients", CLIENT_COUNTS)
    def test_stuck_sessions_are_still_refused_by_both(
        self, clients: int
    ) -> None:
        """Genuinely stuck sessions keep the brute-force cap engaged."""
        results = load_test_results(clients)
        for kind in KINDS:
            assert results[kind]["stuck"].rejected == ABANDONED

    @pytest.mark.parametrize("clients", CLIENT_COUNTS)
    def test_reaping_ends_the_lockout(self, clients: int) -> None:
        """Abandoned sessions lock out stock bitbang; the fix reaps them."""
        results = load_test_results(clients)
        baseline = results["baseline"]["reaped"]
        fixed = results["fixed"]["reaped"]
        assert baseline.rejected == ABANDONED
        assert baseline.silent_rejections == ABANDONED
        assert fixed.rejected == 0
        assert fixed.silent_rejections == 0
        assert fixed.reaped == ABANDONED


class TestLoadTestReport:
    """The report's verdict and exit code must match the numbers."""

    @pytest.mark.parametrize("clients", CLIENT_COUNTS)
    def test_measured_results_earn_the_success_verdict(
        self, clients: int
    ) -> None:
        """A real run of the load test reports success and exits cleanly."""
        code, printed = report_quietly(load_test_results(clients), clients)
        assert code == SUCCESS_CODE
        assert SUCCESS_VERDICT in printed

    def test_a_fix_that_refuses_a_burst_is_flagged(self) -> None:
        """Any refusal by the fix turns the verdict into a failure."""
        results = results_with_burst_rejections(CLASS_SIZE - CAPACITY, 1)
        code, printed = report_quietly(results, CLASS_SIZE)
        assert code == FAILURE_CODE
        assert FAILURE_VERDICT in printed

    def test_a_burst_that_stock_bitbang_admits_is_flagged(self) -> None:
        """A class-sized burst that stock bitbang fully admits is suspect."""
        results = results_with_burst_rejections(0, 0)
        code, printed = report_quietly(results, CLASS_SIZE)
        assert code == FAILURE_CODE
        assert FAILURE_VERDICT in printed
