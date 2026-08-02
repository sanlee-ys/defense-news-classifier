"""Tests for src/mcnemar_power.py.

The sample-size table in ``docs/specs/global-boundary-clause-rerun.md`` is a
pre-registration input: it is what the follow-up's n and its floor were chosen from.
So the tests that matter are the ones that would catch the table being quietly wrong --
that the critical region is the repo's own ``mcnemar_exact`` and not a normal
approximation of it, that power moves the way power must move, and that the two headline
numbers the spec quotes are reproducible from this code rather than transcribed.

Offline and free; there is nothing here a network could help with.
"""

import math

import pytest

import mcnemar_power as mp
from baseline_ml import mcnemar_exact


def test_critical_count_agrees_with_the_function_that_decides_the_verdict():
    """Every count at or below the critical value rejects; the next one does not.

    This is the whole contract. If the critical region drifted from
    ``mcnemar_exact`` -- the function ``paired_compare`` scores the real A/B through --
    the power table would describe a test this repo does not run.
    """
    for discordants in range(1, 60):
        critical = mp.critical_count(discordants)
        if critical >= 0:
            assert mcnemar_exact(critical, discordants - critical) < mp.ALPHA
        following = critical + 1
        if following <= discordants // 2:
            assert mcnemar_exact(following, discordants - following) >= mp.ALPHA


def test_no_split_of_five_or_fewer_discordants_can_ever_reach_significance():
    """The exact test's floor: 2 * 0.5**5 = 0.0625 > 0.05, even at a 0/5 split."""
    for discordants in range(0, 6):
        assert mp.critical_count(discordants) == -1
    assert mp.critical_count(6) == 0


def test_power_rises_with_n_and_reaches_certainty():
    """Monotone in the large, and it must not saturate below 1."""
    scenario = mp.scale_effect(1.00, "observed")
    powers = [mp.power(n, scenario) for n in (100, 300, 600, 1200)]
    assert powers == sorted(powers)
    assert powers[0] < 0.5 < powers[-1]
    assert mp.power(5000, scenario) > 0.999


def test_power_is_zero_without_an_effect_or_without_rows():
    """A scenario with no lift cannot reject in the candidate's favour beyond alpha."""
    flat = mp.scale_effect(0.0, "no effect")
    assert flat.net_lift == 0.0
    assert mp.power(400, flat) < mp.ALPHA
    assert mp.power(0, mp.scale_effect(1.0, "x")) == 0.0


def test_scale_effect_shrinks_the_signal_and_holds_the_noise():
    """The sensitivity parameterization the spec relies on.

    Scaling both discordant rates together would model a *quieter* experiment as well
    as a smaller effect, which understates the sample size a smaller true effect needs.
    """
    observed = mp.scale_effect(1.00, "observed")
    half = mp.scale_effect(0.50, "half")
    assert observed.discordant_rate == pytest.approx(half.discordant_rate)
    assert half.net_lift == pytest.approx(observed.net_lift / 2)
    assert observed.p_b > half.p_b > half.p_c > observed.p_c


def test_the_observed_scenario_reproduces_adr023s_arm():
    """The anchor: 19/8 out of 295, and the p-value the ADR reported."""
    observed = mp.scale_effect(1.00, "observed")
    assert observed.p_b * mp.OBSERVED_N == pytest.approx(19)
    assert observed.p_c * mp.OBSERVED_N == pytest.approx(8)
    assert mcnemar_exact(8, 19) == pytest.approx(0.0522, abs=5e-5)


def test_the_two_numbers_the_spec_quotes_are_reproducible():
    """ADR-023 ran at ~49% power, and 80% needs n=545.

    Both are quoted in the spec and the report header, so they are pinned here rather
    than trusted -- a silently changed constant would move a pre-registered floor.
    """
    observed = mp.scale_effect(1.00, "observed")
    assert mp.power(mp.OBSERVED_N, observed) == pytest.approx(0.490, abs=0.005)
    assert mp.required_n(0.80, observed) == 545
    assert mp.required_n(0.90, observed) == 713


def test_required_n_answers_hold_for_the_rows_that_follow():
    """Exact tests saw-tooth in n; a reported n whose neighbours fail is a trap."""
    observed = mp.scale_effect(1.00, "observed")
    n = mp.required_n(0.80, observed)
    assert n is not None
    for ahead in range(0, 4):
        assert mp.power(n + ahead, observed) >= 0.80
    assert mp.power(n - 1, observed) < 0.80


def test_required_n_gives_up_rather_than_looping_forever():
    """A ceiling that cannot be reached returns None, not a wrong number."""
    assert mp.required_n(0.99, mp.scale_effect(0.05, "tiny"), ceiling=200) is None


def test_rejection_probability_counts_only_candidate_favouring_outcomes():
    """A two-sided test can reject with the BASELINE ahead; that is not power.

    Under a strongly candidate-favouring alternative the wrong-direction tail is
    negligible, so the check is that it is excluded at all -- verified by flipping the
    alternative and seeing the probability collapse.
    """
    forward = mp._rejection_probability(30, q=0.90, alpha=mp.ALPHA)
    backward = mp._rejection_probability(30, q=0.10, alpha=mp.ALPHA)
    assert forward > 0.9
    assert backward < 1e-6


def test_log_binom_pmf_matches_the_exact_binomial():
    """The log-space pmf exists to survive large n; it must still be the pmf."""
    for k in range(0, 8):
        expected = math.comb(7, k) * 0.3**k * 0.7 ** (7 - k)
        assert math.exp(mp._log_binom_pmf(k, 7, 0.3)) == pytest.approx(expected)
    assert mp._log_binom_pmf(1, 3, 0.0) == -math.inf
    assert mp._log_binom_pmf(0, 3, 0.0) == 0.0


def test_table_renders_every_scenario_with_its_sample_sizes():
    """The rendered artifact the spec quotes, and its honest caveat."""
    text = mp.table()
    for scenario in mp.scenarios():
        assert scenario.label in text
    assert "545" in text
    assert "variance instrument" in text
