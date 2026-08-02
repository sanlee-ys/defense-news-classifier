"""v3.2.0 scaled region eval: grade the REGION axis at n=300 with the validated Opus judge.

The v3.0.0 gold run measured region at 87.0% on n=54 (47/54) -- a headline whose 95%
Wilson CI runs [75.6%, 93.6%], 18 points wide. That interval is too wide to tell a real
regression from noise, and too wide to decide whether the one named error cluster (all
seven misses were gold-``global`` rows pulled to a specific region by inferring a theater
from the US *actor*) is a systematic behavior or seven coincidences. This eval closes
that: the same measurement at n=300, where 87.0% would carry an 8-point CI instead --
[82.7%, 90.3%]. Shrinking the ruler is the deliverable; the accuracy itself is whatever
it is.

**Why the judge is allowed to be the answer key here.** Hand-labeling doesn't scale, so
the Opus judge grades the 300. ADR-014 set an explicit gate for that role on this axis --
the judge had to validate against the human gold labels first -- and it did, at **100.0%
region agreement** on the n=54 gold set (``evals/gold_eval_v3.txt``). The judge
configuration is therefore FROZEN: same prompt (``classify.SYSTEM_PROMPT``), same model
ids, same ``classify()`` call path as the run that cleared the gate. "Improving" the judge
would invalidate the validation it passed, so this module deliberately adds no judge logic
of its own -- it reuses ``gold_eval.run_predictions`` unchanged.

**What this is NOT.** A second human answer key. Accuracy here is the workhorse agreeing
with the *judge*; on region the judge's measured disagreement-with-human was 0/54, but 0/54
is itself a wide interval (95% CI [93.4%, 100%]), so read these numbers ALONGSIDE the
human-graded n=54 figures in ``evals/gold_eval_v3.txt``, not instead of them.

**Same snippets as v2.1.0, deliberately.** The set is ``data/scale/scale_set.csv``
unchanged -- the same 300 DVIDS snippets, the same ids, built with the same corpus+gold
exclusions so the judge never grades its own validation data. It is NOT resampled for
region balance: stacking the set toward thin regions would measure a wire that does not
exist, and the honest move is to report the judge's region distribution and flag the skew
(see the limitations block) rather than engineer it away. Reusing the ids also means every
row here lines up with the frozen v2.1.0 snapshot for anyone who later wants a paired view.

Artifacts (all ``_v3``-named; the v2 scale outputs are frozen records, never overwritten):

- ``evals/scale_predictions_v3.csv``           three-axis workhorse + judge predictions
- ``evals/scale_predictions_v3.provenance.json``  which prompt and models produced them
- ``evals/scale_eval_v3.txt``                  the report
- ``evals/scale_confusion_v3_region.csv``      region confusion, workhorse vs judge

Run -- the live pass is owner-driven (it spends ~600 calls); the report is free:

    uv run --env-file .env python src/scale_region_eval.py --run
    uv run --env-file .env python src/scale_region_eval.py --run --batch
    uv run python src/scale_region_eval.py --report

Both ``--run`` forms are resume-safe: predictions append as they land, and a re-run skips
ids already present. A resume across a prompt or model change is refused rather than
blended (see :func:`assert_resume_is_honest`).

No threshold is added to ``evals/thresholds.toml`` by this module. Floors in this repo are
derived from measured runs only; the measured run does not exist until the commands above
are executed, so proposing one now would be exactly the aspirational threshold the repo's
escalation rules forbid.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

import provenance
import scale_eval
from classify import SYSTEM_PROMPT, make_client
from eval import confusion_matrix, macro_average, wilson_interval
from gold_eval import (
    GOLD_PATH,
    JUDGE_MODEL,
    WORKHORSE_MODEL,
    run_predictions,
    run_predictions_batch,
)
from run_isolation import atomic_write_text

SCALE_SET_PATH = scale_eval.SCALE_SET_PATH
PREDS_PATH = "evals/scale_predictions_v3.csv"
PROVENANCE_PATH = "evals/scale_predictions_v3.provenance.json"
REPORT_PATH = "evals/scale_eval_v3.txt"
REGION_CONFUSION_PATH = "evals/scale_confusion_v3_region.csv"

# The frozen v3 gold snapshot the noise-floor-shrink block compares against. Unlike
# v2.1.0's reference (which had to point at the v2 two-axis file), this IS the
# current-prompt, current-model run -- it is the one that produced the 87.0% region
# number and the 100.0% judge-region agreement that gates this eval.
GOLD_PREDS_PATH = "evals/gold_predictions_v3.csv"

# The judge's agreement with the HUMAN labels on the n=54 gold set -- the validation that
# earns it the answer-key role. Sourced from evals/gold_eval_v3.txt; update together.
# Region is the gated axis (ADR-014): the scaled region eval runs only because it hit 1.000.
JUDGE_HUMAN_AGREEMENT = {"category": 0.926, "domain": 0.981, "region": 1.000}

# (axis label, workhorse column, judge/answer-key column). Region leads: it is what this
# eval exists to measure. Category and domain ride along because the same two calls
# already produce them, and reporting them costs nothing beyond a few lines of formatting.
AXES = [
    ("region", "pred_region", "judge_region"),
    ("category", "pred_category", "judge_category"),
    ("operational_domain", "pred_operational_domain", "judge_operational_domain"),
]

PRIMARY_AXIS = "region"

# The catch-all region label. The named v3.0.0 error cluster is entirely rows whose true
# label is this one, so it gets its own report section rather than being averaged away.
GLOBAL = "global"

_HEADINGS = {
    "region": "Region",
    "category": "Category",
    "operational_domain": "Operational domain",
}

_ACCURACY_LABELS = {
    "region": "Region accuracy  ",
    "category": "Category accuracy",
    "operational_domain": "Domain accuracy  ",
}

REQUIRED_COLUMNS = {
    "id",
    "pred_category",
    "pred_operational_domain",
    "pred_region",
    "judge_category",
    "judge_operational_domain",
    "judge_region",
}


# ---------------------------------------------------------------------------
# Loading + the resume guard.
# ---------------------------------------------------------------------------


def load_predictions(path: str = PREDS_PATH) -> pd.DataFrame:
    """Load the three-axis scale predictions, failing loudly on a two-axis file.

    The v2.1.0 snapshot has the same column names minus the two region columns, so a
    file copied to this path would score every axis except the one this eval is for --
    and would do it silently. Mirrors ``gold_eval``'s equivalent check.

    Args:
        path: Predictions CSV path.

    Returns:
        The predictions frame.

    Raises:
        ValueError: If any required column is absent.
    """
    preds = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(preds.columns)
    if missing:
        raise ValueError(
            f"{path} is missing {sorted(missing)}. If this is the v2.1.0 two-axis "
            "snapshot, it cannot be scored on region -- that file is a frozen record; "
            "run `--run` to produce the v3 three-axis predictions instead."
        )
    return preds


def assert_resume_is_honest(done_ids: set, live: dict[str, str]) -> None:
    """Refuse to append today's classifier's rows onto yesterday's.

    Resuming extends a file an earlier run produced. If the prompt or either model has
    moved since, the finished snapshot would be a silent blend of two classifiers and no
    single provenance fingerprint could honestly describe it. gold_eval.py makes the same
    check against its own sidecar; this is that rule applied to the scale snapshot.

    A fresh run (no rows yet) has nothing to blend and is always allowed.

    Args:
        done_ids: Ids already present in the predictions CSV.
        live: A ``provenance.fingerprint`` of the current prompt and models.

    Raises:
        ValueError: If existing rows were produced by a different prompt or model.
    """
    if not done_ids or not os.path.exists(PROVENANCE_PATH):
        return
    drift = provenance.divergences(provenance.load(PROVENANCE_PATH)["recorded"], live)
    if not drift:
        return
    raise ValueError(
        f"Cannot resume {PREDS_PATH}: the {len(done_ids)} existing rows were produced "
        "by a different prompt or model.\n"
        + "\n".join(drift)
        + f"\n\nResuming would mix two classifiers in one snapshot. Delete {PREDS_PATH} "
        f"and {PROVENANCE_PATH} and re-run from scratch."
    )


# ---------------------------------------------------------------------------
# Scoring.
# ---------------------------------------------------------------------------


def metrics(preds: pd.DataFrame) -> dict:
    """Compute the scaled region eval's headline numbers.

    Computed with ``scale_eval``'s own helpers -- the same accuracy, Wilson interval and
    per-label functions v2.1.0 reported through -- so the two reports' numbers mean the
    same thing.

    Args:
        preds: Frame with ``pred_*`` (workhorse) and ``judge_*`` (answer key) columns.

    Returns:
        Dict keyed by axis, each holding the accuracy row (with Wilson CI), per-label
        metrics, macro-F1, and the judge answer-key label distribution, plus ``n``.
    """
    out: dict = {"n": len(preds)}
    for axis, pred_col, judge_col in AXES:
        acc = scale_eval.accuracy_row(preds, pred_col, judge_col)
        labels = scale_eval.per_label(preds, pred_col, judge_col)
        out[axis] = {
            **acc,
            "macro_f1": macro_average(labels)["f1"],
            "per_label": labels,
            "distribution": preds[judge_col].value_counts().to_dict(),
        }
    return out


def region_confusion(preds: pd.DataFrame) -> pd.DataFrame:
    """Region confusion matrix, judge answer key as rows, workhorse as columns.

    Reuses ``eval.confusion_matrix`` by aliasing the judge column to the ground-truth
    name it expects, so the matrix is built the same way as every other one in the repo.

    Args:
        preds: Predictions frame.

    Returns:
        Confusion matrix DataFrame.
    """
    frame = pd.DataFrame(
        {
            "region": preds["judge_region"].to_numpy(),
            "pred_region": preds["pred_region"].to_numpy(),
        }
    )
    return confusion_matrix(frame, "region")


def global_cluster(preds: pd.DataFrame) -> dict:
    """Quantify the named v3.0.0 error cluster at scale.

    On the n=54 gold set, **all seven** region misses were rows whose true label was
    ``global`` and which the model pulled to a specific region -- inferring a theater
    from the US actor when the snippet states no place (ADR-014; the L4 critic fixed 6
    of the 7, ADR-020). Seven rows cannot distinguish a systematic behavior from a
    coincidence. This counts the same shape over n=300, which is the evidence any
    prompt-clause fix would have to be measured against.

    Args:
        preds: Predictions frame.

    Returns:
        Dict with ``judge_global`` (answer-key ``global`` rows), ``pulled`` (of those,
        how many the workhorse assigned to a specific region), ``pulled_to`` (the
        destination labels and counts), ``over_global`` (the converse error: workhorse
        said ``global`` where the judge named a region), ``region_misses`` (all region
        disagreements), and ``pull_share`` (``pulled`` as a fraction of all region
        misses, or ``None`` when there are none).
    """
    judge_global = preds[preds["judge_region"] == GLOBAL]
    pulled = judge_global[judge_global["pred_region"] != GLOBAL]
    over_global = preds[
        (preds["pred_region"] == GLOBAL) & (preds["judge_region"] != GLOBAL)
    ]
    misses = int((preds["pred_region"] != preds["judge_region"]).sum())
    return {
        "judge_global": len(judge_global),
        "pulled": len(pulled),
        "pulled_to": dict(sorted(pulled["pred_region"].value_counts().items())),
        "over_global": len(over_global),
        "region_misses": misses,
        "pull_share": (len(pulled) / misses) if misses else None,
    }


def gold_reference() -> dict | None:
    """The n=54 human-graded accuracy + CI per axis, for the noise-floor comparison.

    Read from the frozen v3 gold snapshot -- the same prompt and models as this eval, so
    the two intervals are the same measurement at two sample sizes and the shrink is the
    only difference between them.

    Returns:
        ``{axis: {accuracy, ci_low, ci_high, n}}`` vs the human labels, or ``None`` when
        the gold files aren't present.
    """
    if not (os.path.exists(GOLD_PATH) and os.path.exists(GOLD_PREDS_PATH)):
        return None
    gold = pd.read_csv(GOLD_PATH).rename(columns={"domain": "operational_domain"})
    merged = gold.merge(pd.read_csv(GOLD_PREDS_PATH), on="id")
    ref = {}
    for axis, _pred_col, _judge_col in AXES:
        if axis not in merged.columns or f"pred_{axis}" not in merged.columns:
            continue
        correct = int((merged[axis] == merged[f"pred_{axis}"]).sum())
        n = len(merged)
        low, high = wilson_interval(correct, n)
        ref[axis] = {
            "accuracy": correct / n if n else 0.0,
            "ci_low": low,
            "ci_high": high,
            "n": n,
        }
    return ref or None


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------


def _global_cluster_block(preds: pd.DataFrame) -> list[str]:
    """Format the named-cluster section.

    Args:
        preds: Predictions frame.

    Returns:
        Report lines.
    """
    c = global_cluster(preds)
    lines = [
        "",
        "-- The named `global` cluster, at scale -------------------",
        "On the n=54 gold set every region miss was a `global` row pulled to a",
        "specific region (ADR-014). Seven rows cannot tell a systematic behavior",
        "from a coincidence; these counts can.",
        "",
        f"Answer-key `global` rows        : {c['judge_global']}",
        f"  of which pulled to a region   : {c['pulled']}",
        f"Converse (over-called `global`) : {c['over_global']}",
        f"All region disagreements        : {c['region_misses']}",
    ]
    if c["pull_share"] is not None:
        lines.append(
            f"  share that is the global pull : {c['pull_share']:.0%} "
            f"({c['pulled']}/{c['region_misses']})"
        )
    if c["pulled_to"]:
        destinations = ", ".join(f"{k} {v}" for k, v in c["pulled_to"].items())
        lines.append(f"Pulled to                       : {destinations}")
    else:
        lines.append("Pulled to                       : (none -- the cluster did not")
        lines.append("                                  reproduce at this scale)")
    return lines


def build_report(preds: pd.DataFrame) -> str:
    """Assemble the human-readable scaled region eval report.

    Args:
        preds: Predictions frame (workhorse + judge columns).

    Returns:
        The report as a string.
    """
    m = metrics(preds)
    ref = gold_reference()
    lines = [
        "=" * 62,
        "v3.2.0 SCALED REGION EVAL -- workhorse vs validated Opus judge",
        "=" * 62,
        "",
        f"Snippets evaluated : {m['n']}   ({SCALE_SET_PATH})",
        f"Workhorse : {WORKHORSE_MODEL}",
        f"Answer key: {JUDGE_MODEL} judge -- validated vs human on the n=54 gold set",
        f"            (REGION {JUDGE_HUMAN_AGREEMENT['region']:.1%} -- the ADR-014 gate "
        "for this eval;",
        f"            {JUDGE_HUMAN_AGREEMENT['category']:.1%} category / "
        f"{JUDGE_HUMAN_AGREEMENT['domain']:.1%} domain).",
        "",
        "Hand-labeling doesn't scale, so the judge is the answer key here. Accuracy",
        "below is the workhorse agreeing with the judge. On region the judge's",
        "measured disagreement with humans was 0/54 -- but 0/54 is itself a wide",
        "interval, so read these numbers ALONGSIDE the human-graded n=54 figures in",
        "evals/gold_eval_v3.txt, not instead of them.",
        "",
        "-- Workhorse vs judge, with 95% Wilson CIs ----------------",
    ]
    for axis, _pred_col, _judge_col in AXES:
        a = m[axis]
        lines.append(
            f"{_ACCURACY_LABELS[axis]} : {a['accuracy']:.1%}   "
            f"95% CI [{a['ci_low']:.1%}, {a['ci_high']:.1%}]   "
            f"({a['correct']}/{a['n']})   macro-F1 {a['macro_f1']:.3f}"
        )

    if ref is not None:
        lines += [
            "",
            "-- The noise-floor shrink (why this eval exists) ----------",
            f"Same metric, human-graded on n={ref[PRIMARY_AXIS]['n']} "
            "(evals/gold_eval_v3.txt):",
        ]
        for axis, _pred_col, _judge_col in AXES:
            if axis not in ref:
                continue
            r, a = ref[axis], m[axis]
            r_w = (r["ci_high"] - r["ci_low"]) * 100
            a_w = (a["ci_high"] - a["ci_low"]) * 100
            lines.append(
                f"  {_ACCURACY_LABELS[axis].strip()}: {r['accuracy']:.1%} "
                f"CI [{r['ci_low']:.1%}, {r['ci_high']:.1%}] "
                f"(width {r_w:.0f}pts) -> at n={a['n']} width {a_w:.0f}pts"
            )

    lines += _global_cluster_block(preds)

    for axis, _pred_col, _judge_col in AXES:
        a = m[axis]
        lines += [
            "",
            f"{_HEADINGS[axis]} per-label (workhorse vs judge):",
            a["per_label"].to_string(float_format="{:.3f}".format),
            "",
            "Answer-key label distribution (judge): "
            + ", ".join(f"{k} {v}" for k, v in sorted(a["distribution"].items())),
        ]
    lines += scale_eval.limitations_block(
        m, axes=tuple((axis, _HEADINGS[axis]) for axis, _p, _j in AXES)
    )
    lines += [
        "",
        f"Region confusion matrix: {REGION_CONFUSION_PATH}",
        "=" * 62,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry points.
# ---------------------------------------------------------------------------


def run(batch: bool = False) -> None:
    """Run the workhorse+judge pass over the scale set (resume-safe), then record provenance.

    This is the only function here that spends API budget: 2 calls per not-yet-done
    snippet (one workhorse, one judge), reusing ``gold_eval``'s prediction loop
    unchanged so the judge configuration is identical to the one that cleared the gate.

    Args:
        batch: Submit via the Message Batches API (~50% cheaper, non-interactive)
            instead of 2*N synchronous calls.

    Raises:
        ValueError: If resuming would blend two different classifiers.
    """
    os.makedirs("evals", exist_ok=True)
    scale = scale_eval.load_scale_set(SCALE_SET_PATH)
    print(f"Loaded {len(scale)} snippets from {SCALE_SET_PATH}\n")

    done_ids = (
        set(pd.read_csv(PREDS_PATH)["id"]) if os.path.exists(PREDS_PATH) else set()
    )
    if done_ids:
        print(f"Resuming: {len(done_ids)} already predicted.\n")

    if not set(scale["id"]) - done_ids:
        print("All predictions already present -- skipping API calls.\n")
        return

    live = provenance.fingerprint(SYSTEM_PROMPT, WORKHORSE_MODEL, JUDGE_MODEL)
    assert_resume_is_honest(done_ids, live)

    client = make_client()
    if batch:
        run_predictions_batch(client, scale, done_ids, preds_path=PREDS_PATH)
    else:
        run_predictions(client, scale, done_ids, preds_path=PREDS_PATH)

    # Written only on the path that actually made API calls -- a report-only rerun must
    # never re-stamp this file, or it would assert that today's prompt produced
    # yesterday's rows.
    provenance.write(live, PREDS_PATH, path=PROVENANCE_PATH)
    print(f"Recorded run provenance to {PROVENANCE_PATH}\n")


def report() -> str:
    """Score the committed predictions and write the report + confusion matrix.

    Entirely offline: no client, no key, no API call. Safe to re-run any number of times.

    Returns:
        The report text.
    """
    os.makedirs("evals", exist_ok=True)
    # Passed explicitly rather than relying on the default: a default argument binds
    # at definition time, so a caller (or a test) that repoints PREDS_PATH would
    # otherwise be silently ignored.
    preds = load_predictions(PREDS_PATH)
    region_confusion(preds).to_csv(REGION_CONFUSION_PATH)
    text = build_report(preds) + "\n"
    # Whole-file write with no resume behind it: a crash mid-write would otherwise leave
    # a truncated report that still looks like a report (src/run_isolation.py).
    atomic_write_text(REPORT_PATH, text)
    return text


def main() -> None:
    """CLI entrypoint: ``--run`` spends API budget, ``--report`` never does."""
    parser = argparse.ArgumentParser(
        description="v3.2.0 scaled region eval with the validated Opus judge."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="LIVE: classify the scale set with the workhorse and the judge (~2*N calls).",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="with --run, submit via the Message Batches API (~50%% cheaper, non-interactive).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="OFFLINE: score the committed predictions and write the report.",
    )
    args = parser.parse_args()

    if not args.run and not args.report:
        parser.error("nothing to do: pass --run and/or --report")
    if args.batch and not args.run:
        parser.error("--batch only applies to --run")
    if args.run:
        run(batch=args.batch)
    if args.report:
        print(report())


if __name__ == "__main__":
    main()
