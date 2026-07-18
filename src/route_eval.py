"""v2.2.0 routing experiment: measure whether tiered tech/ops escalation still pays.

Stated hypothesis, up front: it likely does NOT. ADR-011 aimed routing at the
technology->operations cluster, but the PR #79 prompt fix cleared that cluster on the
human-graded gold set (technology recall 1.000) before routing was ever built. This
harness measures the verdict instead of assuming it -- the same posture as the BM25
grounding retirement (ADR-012).

How the measurement stays cheap and honest:

- **One live pass, zero new Opus spend.** The only new calls are one workhorse pass
  with the runner-up schema over the gold (n=54) and scale (n=300) sets. The
  escalation target is the Opus judge running classify()'s exact call shape -- which
  is what produced the stored ``judge_*`` columns in evals/gold_predictions.csv and
  evals/scale_predictions.csv. So an escalated row's answer is REPLAYED from the
  stored judge prediction rather than re-bought.
- **Quality is graded on human labels only** (the n=54 gold set). The scale set's
  answer key IS the Opus judge -- the same model routing escalates to -- so grading
  escalated rows against it would show improvement by construction. On the scale set
  this reports only the escalation rate, label changes, and cost; never "accuracy".
- **The schema perturbation is measured, not assumed away.** Adding the runner-up
  field changes the call, so the runner-up pass's own labels are compared against the
  stored baseline predictions on every row.

Run (after the stored predictions exist -- they ship in the repo):
    uv run --env-file .env python src/route_eval.py            # ~354 workhorse calls
    uv run --env-file .env python src/route_eval.py --batch    # one Message Batch

Writes the report to evals/route_eval.txt.
"""

from __future__ import annotations

import argparse
import os
import time

import anthropic
import pandas as pd
from anthropic.types import TextBlockParam
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

import gold_eval
import scale_eval
from classify import (
    OUTPUT_CONFIG,
    BatchItemError,
    InvalidLabelError,
    parse_batch_result,
)
from eval import wilson_interval
from route import (
    ESCALATION_MODEL,
    ESCALATION_PAIR,
    ROUTE_SYSTEM_PROMPT,
    ROUTE_TOOL,
    _validate_runner_up,
    classify_with_runner_up,
)

GOLD_RUNNER_PATH = "evals/route_runner_up_gold.csv"
SCALE_RUNNER_PATH = "evals/route_runner_up_scale.csv"
REPORT_PATH = "evals/route_eval.txt"

# List-price ratio of the escalation tier to the workhorse tier (Opus vs Sonnet; the
# ratio holds for both input and output tokens). Used only to express the routed
# pipeline's expected cost in workhorse-call units -- not a billing calculation.
OPUS_SONNET_PRICE_RATIO = 5.0

# (axis label, runner-up-pass column, stored workhorse column, stored judge column).
AXES = [
    ("category", "rp_category", "pred_category", "judge_category"),
    (
        "operational_domain",
        "rp_operational_domain",
        "pred_operational_domain",
        "judge_operational_domain",
    ),
]


def _classify_runner_up_retry(
    client: anthropic.Anthropic, text: str, max_retries: int = 3
) -> dict:
    """classify_with_runner_up() with the same backoff policy as gold_eval's loop.

    Args:
        client: Authenticated Anthropic client.
        text: Article snippet to classify.
        max_retries: Maximum attempts before re-raising.

    Returns:
        Dict with ``category``, ``operational_domain``, ``runner_up_category``.

    Raises:
        anthropic.InternalServerError: If all retries are exhausted on a 500.
        anthropic.RateLimitError: If all retries are exhausted on a 429.
    """
    for attempt in range(max_retries):
        try:
            return classify_with_runner_up(client, text)
        except (anthropic.InternalServerError, anthropic.RateLimitError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise ValueError("max_retries must be >= 1")


def run_runner_up_predictions(
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    done_ids: set,
    preds_path: str,
) -> None:
    """One workhorse pass with the runner-up schema, appending rows as they complete.

    Args:
        client: Authenticated Anthropic client.
        df: Snippet frame with at least ``id`` and ``text``.
        done_ids: IDs already predicted (resume support).
        preds_path: CSV the runner-up predictions are appended to.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    write_header = not os.path.exists(preds_path)
    for i, (_, row) in enumerate(todo.iterrows()):
        print(f"[{i + 1:3d}/{len(todo)}] {row['id']}", flush=True)
        result = _classify_runner_up_retry(client, row["text"])
        out = {
            "id": row["id"],
            "rp_category": result["category"],
            "rp_operational_domain": result["operational_domain"],
            "runner_up_category": result["runner_up_category"],
        }
        pd.DataFrame([out]).to_csv(
            preds_path, mode="a", header=write_header, index=False
        )
        write_header = False
        time.sleep(gold_eval.SLEEP_BETWEEN_CALLS)


def _build_route_batch_request(custom_id: str, text: str) -> Request:
    """One Message Batches request with classify_with_runner_up()'s exact call shape.

    The custom_id is the bare row id (g001/s001) -- one model per row here, so no
    separator scheme is needed, and the ids already satisfy the API's
    ``^[a-zA-Z0-9_-]{1,64}$`` custom_id pattern.

    Args:
        custom_id: Row id used to match the result back once the batch completes.
        text: Raw article snippet to classify.

    Returns:
        A ``Request`` ready for ``client.messages.batches.create``.
    """
    system_block: TextBlockParam = {
        "type": "text",
        "text": ROUTE_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
    params: MessageCreateParamsNonStreaming = {
        "model": gold_eval.WORKHORSE_MODEL,
        "max_tokens": 256,
        "system": [system_block],
        "tools": [ROUTE_TOOL],
        "tool_choice": {"type": "tool", "name": "classify_article"},
        "messages": [{"role": "user", "content": text}],
        "output_config": OUTPUT_CONFIG,
    }
    return Request(custom_id=custom_id, params=params)


def run_runner_up_predictions_batch(
    client: anthropic.Anthropic,
    df: pd.DataFrame,
    done_ids: set,
    preds_path: str,
    poll_interval: float = 30.0,
) -> None:
    """The runner-up pass as ONE Message Batch (~50% cheaper, non-interactive).

    Args:
        client: Authenticated Anthropic client.
        df: Snippet frame with at least ``id`` and ``text``.
        done_ids: IDs already predicted (resume support).
        preds_path: CSV the runner-up predictions are appended to.
        poll_interval: Seconds between polls of the batch status.
    """
    todo = df[~df["id"].isin(done_ids)].reset_index(drop=True)
    if todo.empty:
        return
    requests = [
        _build_route_batch_request(str(row["id"]), row["text"])
        for _, row in todo.iterrows()
    ]
    print(f"Submitting a batch of {len(requests)} runner-up requests...", flush=True)
    batch = client.messages.batches.create(requests=requests)
    print(f"Batch {batch.id} submitted; polling every {poll_interval:.0f}s...")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        print(
            f"  status={batch.processing_status}  "
            f"processing={batch.request_counts.processing}",
            flush=True,
        )
        time.sleep(poll_interval)

    print("Batch ended; retrieving results...", flush=True)
    write_header = not os.path.exists(preds_path)
    for result in client.messages.batches.results(batch.id):
        try:
            pred = _validate_runner_up(parse_batch_result(result))
        except (BatchItemError, InvalidLabelError) as exc:
            # Leave the row out of the CSV -- it stays todo for a later run.
            print(f"  [skip] id={result.custom_id}: {exc}", flush=True)
            continue
        out = {
            "id": result.custom_id,
            "rp_category": pred["category"],
            "rp_operational_domain": pred["operational_domain"],
            "runner_up_category": pred["runner_up_category"],
        }
        pd.DataFrame([out]).to_csv(
            preds_path, mode="a", header=write_header, index=False
        )
        write_header = False


def escalated_mask(runner: pd.DataFrame) -> pd.Series:
    """Row-wise routing decision: True where the top-two categories are the pair.

    Args:
        runner: Runner-up pass frame (``rp_category``, ``runner_up_category``).

    Returns:
        Boolean Series aligned to ``runner`` -- the vectorized ``should_escalate``.
    """
    pair = set(ESCALATION_PAIR)
    return runner.apply(
        lambda r: {r["rp_category"], r["runner_up_category"]} == pair, axis=1
    )


def compose_routed(runner: pd.DataFrame, stored: pd.DataFrame) -> pd.DataFrame:
    """Replay routing offline: escalated rows take the stored judge prediction.

    The escalation call is classify() on the judge model with the shipped prompt --
    exactly what produced the stored ``judge_*`` columns -- so no new Opus calls are
    needed to know what escalation would have answered.

    Args:
        runner: Runner-up pass frame (``id``, ``rp_*``, ``runner_up_category``).
        stored: Stored predictions frame (``id``, ``pred_*``, ``judge_*``).

    Returns:
        ``runner`` merged with ``stored``, plus ``escalated`` (bool) and the final
        ``routed_category`` / ``routed_operational_domain`` columns.
    """
    merged = runner.merge(stored, on="id", validate="one_to_one")
    merged["escalated"] = escalated_mask(merged)
    for _, rp_col, _pred_col, judge_col in AXES:
        routed_col = rp_col.replace("rp_", "routed_")
        merged[routed_col] = merged[rp_col].where(
            ~merged["escalated"], merged[judge_col]
        )
    return merged


def _system_row(truth: pd.Series, preds: pd.Series) -> dict:
    """Accuracy of one system against human truth, with a 95% Wilson CI.

    Args:
        truth: Human labels.
        preds: The system's predictions, aligned to ``truth``.

    Returns:
        Dict with ``n``, ``correct``, ``accuracy``, ``ci_low``, ``ci_high``.
    """
    correct = int((truth == preds).sum())
    n = len(truth)
    low, high = wilson_interval(correct, n)
    return {
        "n": n,
        "correct": correct,
        "accuracy": correct / n if n else 0.0,
        "ci_low": low,
        "ci_high": high,
    }


def gold_metrics(gold: pd.DataFrame, composed: pd.DataFrame) -> dict:
    """The quality verdict: baseline vs routed vs all-Opus, on human labels.

    Args:
        gold: Human-labeled gold frame (``id``, ``category``, ``domain``).
        composed: ``compose_routed`` output for the gold set.

    Returns:
        Dict with per-axis system rows, the escalation count, and the row-level
        effect of routing on escalated rows (fixed / broke / unchanged vs human).
    """
    truth = gold.rename(columns={"domain": "operational_domain"})
    merged = truth.merge(composed, on="id", validate="one_to_one")
    out: dict = {
        "n": len(merged),
        "escalated": int(merged["escalated"].sum()),
        "escalated_ids": sorted(merged.loc[merged["escalated"], "id"]),
    }
    for axis, rp_col, pred_col, _judge_col in AXES:
        routed_col = rp_col.replace("rp_", "routed_")
        out[axis] = {
            "baseline": _system_row(merged[axis], merged[pred_col]),
            "routed": _system_row(merged[axis], merged[routed_col]),
            "all_opus": _system_row(merged[axis], merged[_judge_col]),
        }
    # Row-level effect on the escalated rows only, category axis (the routed pair).
    esc = merged[merged["escalated"]]
    was_right = esc["category"] == esc["rp_category"]
    now_right = esc["category"] == esc["routed_category"]
    out["escalation_effect"] = {
        "fixed": int((~was_right & now_right).sum()),
        "broke": int((was_right & ~now_right).sum()),
        "unchanged": int((was_right == now_right).sum()),
    }
    return out


def perturbation_check(composed: pd.DataFrame) -> dict:
    """How much the runner-up schema itself moved the workhorse's labels.

    Args:
        composed: ``compose_routed`` output (carries both ``rp_*`` and ``pred_*``).

    Returns:
        Dict of per-axis agreement between the runner-up pass and the stored
        baseline workhorse pass, with the number of rows that moved.
    """
    out = {}
    for axis, rp_col, pred_col, _judge_col in AXES:
        same = int((composed[rp_col] == composed[pred_col]).sum())
        out[axis] = {"agree": same, "n": len(composed), "moved": len(composed) - same}
    return out


def scale_metrics(composed: pd.DataFrame) -> dict:
    """What the scale set can honestly say: escalation rate and label movement.

    No accuracy is computed here -- the scale set's only answer key is the Opus
    judge, which is the escalation target itself, so escalated rows would "agree"
    with it by construction.

    Args:
        composed: ``compose_routed`` output for the scale set.

    Returns:
        Dict with n, escalation count/rate, and how many escalations changed the
        category label relative to the workhorse's own answer.
    """
    esc = composed[composed["escalated"]]
    changed = int((esc["rp_category"] != esc["routed_category"]).sum())
    return {
        "n": len(composed),
        "escalated": int(len(esc)),
        "rate": len(esc) / len(composed) if len(composed) else 0.0,
        "category_changed": changed,
        "escalated_ids": sorted(esc["id"]),
    }


def cost_lines(rate: float) -> list[str]:
    """Expected relative cost of the three pipelines, in workhorse-call units.

    Args:
        rate: Measured escalation rate (fraction of articles escalated).

    Returns:
        Report lines comparing workhorse-only, routed, and all-Opus costs.
    """
    routed = 1.0 + rate * OPUS_SONNET_PRICE_RATIO
    return [
        f"Cost model (list-price ratio Opus:Sonnet = {OPUS_SONNET_PRICE_RATIO:.0f}:1),"
        " per article, in workhorse-call units:",
        "  workhorse only : 1.00x",
        f"  routed         : {routed:.2f}x   (1 + {rate:.1%} escalation rate x "
        f"{OPUS_SONNET_PRICE_RATIO:.0f})",
        f"  all-Opus       : {OPUS_SONNET_PRICE_RATIO:.2f}x",
    ]


def build_report(gm: dict, sm: dict, perturb: dict) -> str:
    """Assemble the human-readable routing-experiment report.

    Args:
        gm: ``gold_metrics`` output.
        sm: ``scale_metrics`` output.
        perturb: ``perturbation_check`` output (for the gold set).

    Returns:
        The report as a string.
    """
    pair = "/".join(sorted(ESCALATION_PAIR))
    lines = [
        "=" * 62,
        "v2.2.0 ROUTING EXPERIMENT -- tiered tech/ops escalation",
        "=" * 62,
        "",
        "Trigger : workhorse self-reports its runner-up category; escalate to",
        f"          {ESCALATION_MODEL} iff the top-two categories are {{{pair}}}.",
        "Hypothesis going in: the PR #79 prompt fix already cleared this cluster",
        "(ADR-011 gate), so routing likely no longer pays. This measures it.",
        "",
        f"-- Quality verdict: human-graded gold set (n={gm['n']}) ---------",
        f"Escalations fired: {gm['escalated']}/{gm['n']}"
        + (f"   ids: {', '.join(gm['escalated_ids'])}" if gm["escalated_ids"] else ""),
        "",
    ]
    name = {"category": "Category", "operational_domain": "Domain  "}
    for axis in ("category", "operational_domain"):
        rows = gm[axis]
        lines.append(f"{name[axis]} accuracy vs human, 95% Wilson CI:")
        for system, label in (
            ("baseline", "workhorse only"),
            ("routed", "routed        "),
            ("all_opus", "all-Opus      "),
        ):
            r = rows[system]
            lines.append(
                f"  {label} : {r['accuracy']:.1%}  "
                f"[{r['ci_low']:.1%}, {r['ci_high']:.1%}]  ({r['correct']}/{r['n']})"
            )
        delta = rows["routed"]["correct"] - rows["baseline"]["correct"]
        lines.append(f"  routing moved the {axis} count by {delta:+d} rows")
        lines.append("")
    eff = gm["escalation_effect"]
    lines += [
        "Escalated rows, category axis: "
        f"fixed {eff['fixed']}, broke {eff['broke']}, unchanged {eff['unchanged']}.",
        "",
        "-- Schema perturbation check (gold set) -------------------",
        "Adding the runner_up_category field changes the call; the runner-up pass's",
        "own labels vs the stored baseline workhorse pass:",
    ]
    for axis in ("category", "operational_domain"):
        p = perturb[axis]
        lines.append(
            f"  {name[axis].strip()}: {p['agree']}/{p['n']} unchanged"
            f" ({p['moved']} moved)"
        )
    lines += [
        "",
        f"-- Scale set (n={sm['n']}): rate and cost only ---------------",
        "No accuracy here BY DESIGN: the scale set's answer key is the Opus judge,",
        "which is the escalation target itself -- escalated rows would agree with",
        "it by construction. Rate and cost are what this set can honestly measure.",
        "",
        f"Escalations fired: {sm['escalated']}/{sm['n']} ({sm['rate']:.1%})"
        f"; category label changed by escalation: {sm['category_changed']}",
        "",
        *cost_lines(sm["rate"]),
        "=" * 62,
    ]
    return "\n".join(lines)


def _load_runner(path: str) -> pd.DataFrame:
    """Load a runner-up predictions CSV, with NaN-safe runner-up values."""
    df = pd.read_csv(path)
    df["runner_up_category"] = df["runner_up_category"].fillna("none")
    return df


def main() -> None:
    """Run the runner-up passes (resume-safe), replay routing offline, and report."""
    parser = argparse.ArgumentParser(
        description="v2.2.0 tiered-routing experiment (runner-up trigger)."
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="submit via the Message Batches API (~50%% cheaper, non-interactive).",
    )
    args = parser.parse_args()
    os.makedirs("evals", exist_ok=True)

    gold = gold_eval.load_gold()
    scale = scale_eval.load_scale_set()
    run = run_runner_up_predictions_batch if args.batch else run_runner_up_predictions

    client = None
    for df, path, label in (
        (gold, GOLD_RUNNER_PATH, "gold"),
        (scale, SCALE_RUNNER_PATH, "scale"),
    ):
        done = set(pd.read_csv(path)["id"]) if os.path.exists(path) else set()
        todo = set(df["id"]) - done
        print(f"{label}: {len(df)} rows, {len(done)} done, {len(todo)} to run.")
        if todo:
            if client is None:
                from classify import make_client

                client = make_client()
            run(client, df, done, preds_path=path)

    gold_composed = compose_routed(
        _load_runner(GOLD_RUNNER_PATH), pd.read_csv(gold_eval.PREDS_PATH)
    )
    scale_composed = compose_routed(
        _load_runner(SCALE_RUNNER_PATH), pd.read_csv(scale_eval.SCALE_PREDS_PATH)
    )
    report = build_report(
        gold_metrics(gold, gold_composed),
        scale_metrics(scale_composed),
        perturbation_check(gold_composed),
    )
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()
