"""How much ruler a McNemar comparison needs before its answer is decidable.

WHY THIS EXISTS. ADR-023 measured the `global`-boundary clause at n=295 and got
region 88.5% -> 92.2% with discordant pairs 19/8 -- **McNemar p=0.0522** against a
pre-registered p<0.05. The rule said revert, and it was honored. The ADR then named
the one thing that would change the answer: *"a higher-power ruler, and essentially
nothing else."*

That claim deserves a number rather than a feeling. This module computes the exact
power of the repo's own two-sided exact McNemar test (``baseline_ml.mcnemar_exact``,
the same function ``paired_compare`` scores every A/B through), so the follow-up's
sample size is derived rather than guessed, and so the derivation is re-runnable by
anyone who doubts it:

    uv run python src/mcnemar_power.py

HOW THE POWER IS COMPUTED, EXACTLY. McNemar's test conditions on the discordant
pairs, so the calculation is two nested binomials and no approximation is needed:

1. The number of discordant pairs ``D`` out of ``n`` is ``Binomial(n, p_b + p_c)``,
   where ``p_b`` is the per-row probability the candidate is right and the baseline
   wrong, and ``p_c`` the reverse.
2. Conditional on ``D = d``, the count favoring the candidate is
   ``Binomial(d, p_b / (p_b + p_c))``.
3. For each ``d`` there is a critical count ``c_d``: the largest minority count whose
   two-sided exact p-value is still below alpha (``-1`` when no split at that ``d``
   can reach significance -- at alpha=0.05, ``d <= 5`` can never reject).

Power is then the probability-weighted sum over ``d`` of landing in that rejection
region. **No normal approximation, no continuity correction, no simulation** -- which
matters, because the whole reason this repo is doing arithmetic instead of eyeballing
is that the last verdict turned on 0.0022.

THE ONE HONEST CAVEAT, STATED UP FRONT. Feeding this the *observed* 19/8 and reading
the result as "the power the completed run had" is post-hoc power, which is a
monotone transform of the p-value already reported and therefore says nothing new
(Hoenig & Heisey 2001). That is not what this is for. This is a **design**
calculation: it answers "if the true rates are X, how many rows does a decidable
answer need", and X is an assumption whose consequences are shown across a
sensitivity band -- never a fact recovered from the run that motivated it.

WHAT MORE ROWS CANNOT BUY. Power is a variance instrument. ADR-022 and ADR-023
documented a *bias* in the same ruler -- byte-identical snippets the answer key
labels differently (s024/s025), the EUCOM cluster's six rows answered inconsistently,
the Dahlgren cluster's five. Sampling more rows from the same source reproduces that
inconsistency at the same rate; it shrinks the interval around a slightly wrong
center. The spec says so where the numbers are quoted, and so does this docstring,
because a power table is exactly the artifact that invites the opposite reading.
"""

from __future__ import annotations

import argparse
import functools
import math
from dataclasses import dataclass

from baseline_ml import mcnemar_exact

# The ADR-023 region result, which every scenario below is anchored on.
OBSERVED_N = 295
OBSERVED_CANDIDATE_WINS = 19
OBSERVED_BASELINE_WINS = 8

ALPHA = 0.05

# How far into the tails of D the outer sum runs before the remaining mass is
# numerically irrelevant. Six sigma either side of the mean leaves < 1e-9 unswept,
# which is four orders below the precision any of these numbers are read to.
_SIGMA_SPAN = 6.0


@dataclass(frozen=True)
class Scenario:
    """One assumed truth about the effect, and the rates that encode it.

    Attributes:
        label: How the scenario is named in the rendered table.
        p_b: Per-row probability the candidate is right where the baseline is wrong.
        p_c: Per-row probability the baseline is right where the candidate is wrong.
    """

    label: str
    p_b: float
    p_c: float

    @property
    def discordant_rate(self) -> float:
        """Probability that a row is discordant at all."""
        return self.p_b + self.p_c

    @property
    def net_lift(self) -> float:
        """Expected accuracy difference per row: the number the A/B reports as `lift`."""
        return self.p_b - self.p_c


def scale_effect(fraction: float, label: str) -> Scenario:
    """Build a scenario holding the discordant RATE fixed and scaling the SIGNAL.

    This is the sensitivity parameterization, and the choice is deliberate. An A/B's
    difficulty is set by two things -- how often the two arms disagree at all (noise)
    and how lopsidedly those disagreements fall (signal). Scaling both together would
    describe a *quieter* experiment as well as a smaller effect, which flatters the
    sample size. Holding ``p_b + p_c`` at the observed 27/295 and shrinking
    ``p_b - p_c`` asks the harder and more realistic question: what if the clause is
    genuinely less good than it looked, on a ruler exactly as noisy as this one?

    Args:
        fraction: Multiplier on the observed net lift (1.0 reproduces the observation).
        label: Display label for the scenario.

    Returns:
        The scenario with the rescaled rates.
    """
    total = (OBSERVED_CANDIDATE_WINS + OBSERVED_BASELINE_WINS) / OBSERVED_N
    diff = fraction * (OBSERVED_CANDIDATE_WINS - OBSERVED_BASELINE_WINS) / OBSERVED_N
    return Scenario(label=label, p_b=(total + diff) / 2, p_c=(total - diff) / 2)


@functools.cache
def critical_count(discordants: int, alpha: float = ALPHA) -> int:
    """The largest minority count at which the exact test still rejects.

    Computed by asking ``baseline_ml.mcnemar_exact`` itself rather than
    reimplementing its tail, so this power calculation can never drift from the
    function that actually decides the verdict. The p-value is monotone increasing in
    the minority count -- it is a cumulative binomial tail -- so the boundary is found
    by bisection rather than by scanning up from zero. That matters at the sample
    sizes this module reaches: ``mcnemar_exact`` re-sums its whole tail on every call,
    so a linear scan is quadratic in the discordant count and turns the table into a
    minutes-long computation.

    Memoized because the sample-size search re-asks the same few hundred questions
    thousands of times: the critical count depends only on ``(discordants, alpha)``,
    never on ``n`` or on the scenario. It is the difference between a table that
    renders in a second and one that renders in ten minutes.

    Args:
        discordants: Number of discordant pairs.
        alpha: Two-sided significance level.

    Returns:
        The largest ``m`` with ``mcnemar_exact(m, discordants - m) < alpha``, or
        ``-1`` when no split of this many discordants can reach significance.
    """
    if discordants < 1 or mcnemar_exact(0, discordants) >= alpha:
        return -1
    low, high = 0, discordants // 2
    while low < high:
        middle = (low + high + 1) // 2
        if mcnemar_exact(middle, discordants - middle) < alpha:
            low = middle
        else:
            high = middle - 1
    return low


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    """Log of the binomial pmf, in log space so large ``n`` cannot overflow."""
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


@functools.cache
def _rejection_probability(discordants: int, q: float, alpha: float) -> float:
    """P(the exact test rejects, in the candidate's favor), given the discordant count.

    Memoized, and that is not a micro-optimization: ``power`` sums over a window of
    discordant counts around ``n * rate``, and consecutive sample sizes ask about
    almost exactly the same counts, so a sample-size search re-derives each one
    hundreds of times. ``q`` and ``alpha`` are fixed per scenario, so the cache is
    effectively keyed on the discordant count alone.

    Only the candidate-favoring tail counts. A two-sided test can also reject with the
    *baseline* ahead, and calling that "power" would credit the design for reaching a
    conclusion opposite to the one it is powered for. Under any scenario here that
    tail is negligible, so this is a definitional nicety rather than a numerical one --
    which is precisely why it costs nothing to get right.

    Args:
        discordants: Number of discordant pairs.
        q: Probability a discordant pair favors the candidate.
        alpha: Two-sided significance level.

    Returns:
        The conditional probability of a significant, candidate-favoring result.
    """
    critical = critical_count(discordants, alpha)
    if critical < 0:
        return 0.0
    # Candidate-favoring rejection means the BASELINE holds the minority count, i.e.
    # candidate wins >= discordants - critical. The tail is walked by the binomial
    # recurrence pmf(k+1) = pmf(k) * (d-k)/(k+1) * q/(1-q) from a single log-space
    # anchor, rather than one log-gamma evaluation per term.
    start = discordants - critical
    term = math.exp(_log_binom_pmf(start, discordants, q))
    total = term
    if q <= 0.0 or q >= 1.0:
        return sum(
            math.exp(_log_binom_pmf(wins, discordants, q))
            for wins in range(start, discordants + 1)
        )
    odds = q / (1.0 - q)
    for wins in range(start, discordants):
        term *= (discordants - wins) / (wins + 1) * odds
        total += term
    return total


@functools.cache
def power(n: int, scenario: Scenario, alpha: float = ALPHA) -> float:
    """Exact power of the two-sided McNemar test at sample size ``n``.

    Memoized on ``(n, scenario, alpha)`` -- ``Scenario`` is a frozen dataclass, so it
    hashes by value. :func:`required_n` re-asks the same sample sizes as it brackets
    and then walks the sawtooth, and each answer costs a few thousand log-gamma
    evaluations.

    Args:
        n: Number of paired, independent observations (post-deduplication).
        scenario: The assumed per-row discordance rates.
        alpha: Two-sided significance level.

    Returns:
        Probability of a significant result in the candidate's favor.
    """
    rate = scenario.discordant_rate
    if n <= 0 or rate <= 0:
        return 0.0
    q = scenario.p_b / rate
    mean, sigma = n * rate, math.sqrt(n * rate * (1 - rate))
    low = max(0, int(mean - _SIGMA_SPAN * sigma))
    high = min(n, int(math.ceil(mean + _SIGMA_SPAN * sigma)))
    return sum(
        math.exp(_log_binom_pmf(discordants, n, rate))
        * _rejection_probability(discordants, q, alpha)
        for discordants in range(low, high + 1)
    )


def required_n(
    target: float,
    scenario: Scenario,
    alpha: float = ALPHA,
    ceiling: int = 20000,
) -> int | None:
    """Smallest ``n`` whose power reaches ``target``.

    Power in ``n`` is *not* perfectly monotone for an exact discrete test -- it
    saw-tooths as the critical count steps with each new discordant pair -- so a plain
    binary search can land on a tooth and report an ``n`` whose neighbours fail. This
    brackets by doubling, binary-searches for the crossing on the *qualifying*
    predicate (power at ``n`` and the next three rows), and then walks downward while
    that predicate still holds, which recovers any tooth the search stepped over.
    Scanning the whole bracket instead would be correct and about fifty times slower.

    Args:
        target: Power to reach, e.g. 0.80.
        scenario: The assumed per-row discordance rates.
        alpha: Two-sided significance level.
        ceiling: Give up beyond this ``n``.

    Returns:
        The smallest qualifying ``n``, or ``None`` if the ceiling is reached first.
    """

    def clears(n: int) -> bool:
        return power(n, scenario, alpha) >= target and all(
            power(n + ahead, scenario, alpha) >= target for ahead in (1, 2, 3)
        )

    high = 32
    while high <= ceiling and not clears(high):
        high *= 2
    if high > ceiling:
        return None

    low = max(1, high // 2)
    while low < high:
        middle = (low + high) // 2
        if clears(middle):
            high = middle
        else:
            low = middle + 1
    while low > 1 and clears(low - 1):
        low -= 1
    return low


def scenarios() -> list[Scenario]:
    """The observed effect and the two shrunken variants the spec reports."""
    return [
        scale_effect(1.00, "observed (19/8)"),
        scale_effect(0.75, "75% of observed"),
        scale_effect(0.50, "50% of observed"),
    ]


def table(rows: list[Scenario] | None = None, alpha: float = ALPHA) -> str:
    """Render the sample-size table the spec quotes.

    Args:
        rows: Scenarios to report. Defaults to :func:`scenarios`.
        alpha: Two-sided significance level.

    Returns:
        The rendered report text.
    """
    rows = scenarios() if rows is None else rows
    out = [
        "=" * 78,
        "McNEMAR SAMPLE SIZE -- exact two-sided test, alpha = " f"{alpha}",
        "=" * 78,
        "",
        f"Anchor: ADR-023 region arm, n={OBSERVED_N}, discordants "
        f"{OBSERVED_CANDIDATE_WINS}/{OBSERVED_BASELINE_WINS}, p="
        f"{mcnemar_exact(OBSERVED_BASELINE_WINS, OBSERVED_CANDIDATE_WINS):.4f}.",
        "",
        "Scenarios hold the discordant RATE at the observed 27/295 and shrink the",
        "net lift, so a smaller effect is not also modelled as a quieter experiment.",
        "",
        f"{'scenario':<18}{'net lift':>10}{'n for 80%':>11}{'disc.':>8}"
        f"{'n for 90%':>11}{'disc.':>8}{'power@295':>11}{'power@595':>11}",
    ]
    for scenario in rows:
        n80 = required_n(0.80, scenario, alpha)
        n90 = required_n(0.90, scenario, alpha)
        disc80 = f"{n80 * scenario.discordant_rate:.0f}" if n80 else "-"
        disc90 = f"{n90 * scenario.discordant_rate:.0f}" if n90 else "-"
        out.append(
            f"{scenario.label:<18}{scenario.net_lift:>+9.2%}"
            f"{(str(n80) if n80 else '>20000'):>11}{disc80:>8}"
            f"{(str(n90) if n90 else '>20000'):>11}{disc90:>8}"
            f"{power(OBSERVED_N, scenario, alpha):>11.3f}"
            f"{power(595, scenario, alpha):>11.3f}"
        )
    out += [
        "",
        "`disc.` is the expected number of discordant pairs at that n -- the count",
        "the test actually consumes. `power@595` is what one more 300-snippet",
        "collection buys on top of the existing 295.",
        "",
        "Power is a variance instrument. It does not touch the answer key's",
        "documented disagreements with itself (ADR-023, section 2.1); those reproduce",
        "at the same rate in a larger sample from the same source.",
        "=" * 78,
    ]
    return "\n".join(out)


def main() -> None:
    """CLI entrypoint. Offline, free, and repeatable -- no client and no key."""
    parser = argparse.ArgumentParser(
        description="Exact McNemar power / sample size for the ADR-023 follow-up."
    )
    parser.add_argument(
        "--alpha", type=float, default=ALPHA, help="two-sided significance level"
    )
    args = parser.parse_args()
    print(table(alpha=args.alpha))


if __name__ == "__main__":
    main()
