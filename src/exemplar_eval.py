"""kNN-exemplar few-shot experiment: labeled examples instead of neighbor docs.

The third measured test of retrieval augmentation in this repo, and the last
untried shape. BM25 grounding retrieved *unlabeled neighbor documents* as
context and was retired (ADR-012: 0 domain calls fixed, 4 broken). Rung 2's
loop mined *lexical keyword features* and they failed to transfer (ADR-018
amendment: B +6.0, C -8.6). This experiment retrieves the k most similar
**labeled examples** and injects them as few-shot exemplars -- teaching
boundary placement rather than adding topical context. The prior is therefore
double-negative going in, which the design ADR states plainly; either outcome
extends the measured series.

Design (ADR-019):

- **Exemplar pool:** the 300 judge-labeled scale rows (``judge_*`` labels via
  ``baseline_ml.load_train`` -- never ``pred_*``). Category and domain only:
  the pool has no region labels, and the only region-labeled data (the gold
  set) cannot be both exemplar pool and eval set without a leak.
- **Primary measurement:** paired McNemar on the 300-row scale set vs the
  judge labels -- exemplar arm retrieves leave-one-out (a row never retrieves
  itself); the baseline arm is RE-RUN FRESH under the current prompt + model
  rather than reusing ``evals/scale_predictions.csv``'s stored workhorse
  column, because that column predates the v3 prompt -- comparing a
  new-prompt exemplar arm against an old-prompt baseline is exactly the
  unfair-baseline bug PR #81 had to fix for ADR-012.
- **Secondary, directional:** the gold 54, exemplar arm only, against the
  stored ``evals/gold_predictions_v3.csv`` baseline (that run IS
  current-prompt/current-model, so it is a fair anchor). Includes the region
  axis as a **guardrail**: exemplars carry no region labels, and the check is
  that their presence does not degrade region accuracy.
- **Mechanism:** the exemplar block is appended to ``SYSTEM_PROMPT`` and the
  call goes through ``classify()`` unchanged (same tool schema, validation,
  strict enums) via rung 1's ``_classify_retry`` -- baseline and exemplar
  arms differ by exactly the appended block.

Every live row is appended to a CSV immediately and re-runs resume by
skipping already-scored ids, mirroring ``eval.py``'s crash-safety.

Offline (free): ``--report`` builds ``evals/exemplar_eval.txt`` from whatever
arm CSVs exist. Live (San drives; ~600 workhorse calls total across both
scale arms + 54 for gold):

    uv run --env-file .env python src/exemplar_eval.py --run scale-baseline
    uv run --env-file .env python src/exemplar_eval.py --run scale-exemplar
    uv run --env-file .env python src/exemplar_eval.py --run gold-exemplar
    uv run python src/exemplar_eval.py --report
"""

from __future__ import annotations

import argparse
import os

import pandas as pd
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from baseline_ml import mcnemar_exact
from classify import MODEL, SYSTEM_PROMPT, make_client
from eval import wilson_interval
from optimize import UNCLASSIFIED, _classify_retry, _salvage_labels
from retrieve import _tokenize

GOLD_PATH = "data/gold/gold.csv"
GOLD_BASELINE_PATH = "evals/gold_predictions_v3.csv"
REPORT_PATH = "evals/exemplar_eval.txt"

ARM_PATHS = {
    "scale-baseline": "evals/exemplar_scale_baseline.csv",
    "scale-exemplar": "evals/exemplar_scale_exemplar.csv",
    "gold-exemplar": "evals/exemplar_gold_exemplar.csv",
}

DEFAULT_K = 3  # mirrors the retired RAG layer's k, deliberately
EXEMPLAR_SNIPPET_CHARS = 400
AXES = ("category", "operational_domain")


# ---------------------------------------------------------------------------
# Exemplar retrieval + prompt construction.
# ---------------------------------------------------------------------------


class ExemplarIndex:
    """BM25 over the labeled pool; retrieves rows, never the query row itself."""

    def __init__(self, pool: pd.DataFrame) -> None:
        """Index the pool.

        Args:
            pool: Labeled rows (``id``, ``text``, ``category``,
                ``operational_domain``) -- the judge-labeled 300.
        """
        self.pool = pool.reset_index(drop=True)
        self._bm25 = BM25Okapi([_tokenize(t) for t in self.pool["text"]])

    def retrieve(
        self, text: str, k: int = DEFAULT_K, exclude_id: str | None = None
    ) -> pd.DataFrame:
        """Top-k most similar pool rows for ``text``.

        Args:
            text: The query snippet.
            k: Number of exemplars.
            exclude_id: Pool id to never return -- the leave-one-out guard for
                scoring pool rows against their own pool.

        Returns:
            The k selected pool rows, most similar first.
        """
        scores = self._bm25.get_scores(_tokenize(text))
        order = scores.argsort()[::-1]
        picked = []
        for idx in order:
            row = self.pool.iloc[int(idx)]
            if exclude_id is not None and row["id"] == exclude_id:
                continue
            picked.append(row)
            if len(picked) == k:
                break
        return pd.DataFrame(picked)


def exemplar_block(exemplars: pd.DataFrame) -> str:
    """Format retrieved labeled exemplars as a system-prompt suffix.

    States explicitly that the examples carry no region label, so the model
    is not tempted to infer "these examples omit region, so region must not
    matter" -- the region rubric above it stays authoritative.

    Args:
        exemplars: Rows from :meth:`ExemplarIndex.retrieve`.

    Returns:
        The block to append to ``SYSTEM_PROMPT``.
    """
    lines = [
        "",
        "Reference examples -- similar snippets with confirmed category and "
        "operational_domain labels (region labels intentionally not shown; "
        "apply the region rules above independently):",
    ]
    for i, (_, row) in enumerate(exemplars.iterrows(), start=1):
        snippet = " ".join(row["text"][:EXEMPLAR_SNIPPET_CHARS].split())
        lines.append(
            f'{i}. "{snippet}" -> category={row["category"]}, '
            f"operational_domain={row['operational_domain']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live arms (resume-safe).
# ---------------------------------------------------------------------------


def _load_pool() -> pd.DataFrame:
    from baseline_ml import load_train

    return load_train()


def _rows_to_score(arm: str, pool: pd.DataFrame) -> pd.DataFrame:
    if arm.startswith("scale"):
        return pool[["id", "text"]]
    return pd.read_csv(GOLD_PATH)[["id", "text"]]


def pending_rows(rows: pd.DataFrame, out_path: str) -> pd.DataFrame:
    """Rows not yet scored into ``out_path`` -- the resume filter.

    Args:
        rows: All rows the arm should score.
        out_path: The arm's output CSV (may not exist yet).

    Returns:
        The subset of ``rows`` whose ids are absent from the CSV.
    """
    if not os.path.exists(out_path):
        return rows
    done = set(pd.read_csv(out_path)["id"])
    return rows[~rows["id"].isin(done)]


def run_arm(arm: str, k: int = DEFAULT_K) -> None:
    """Run one live arm, appending each scored row immediately.

    Args:
        arm: One of ``ARM_PATHS``' keys.
        k: Exemplar count (exemplar arms only).
    """
    pool = _load_pool()
    rows = _rows_to_score(arm, pool)
    out_path = ARM_PATHS[arm]
    todo = pending_rows(rows, out_path)
    print(f"{arm}: {len(todo)}/{len(rows)} rows to score (resume-safe)", flush=True)
    if todo.empty:
        return
    index = ExemplarIndex(pool) if arm.endswith("exemplar") else None
    client = make_client()
    write_header = not os.path.exists(out_path)
    for n, (_, row) in enumerate(todo.iterrows(), start=1):
        prompt = SYSTEM_PROMPT
        if index is not None:
            exclude = row["id"] if arm == "scale-exemplar" else None
            prompt = SYSTEM_PROMPT + exemplar_block(
                index.retrieve(row["text"], k=k, exclude_id=exclude)
            )
        try:
            pred = _classify_retry(
                client, row["text"], model=MODEL, system_prompt=prompt
            )
            labels = (pred["category"], pred["operational_domain"], pred["region"])
        except Exception as exc:  # InvalidLabelError -> per-axis sentinel
            from classify import InvalidLabelError

            if not isinstance(exc, InvalidLabelError):
                raise
            labels = _salvage_labels(exc)
            print(f"  {row['id']}: invalid label, sentinelled", flush=True)
        record = pd.DataFrame(
            [
                {
                    "id": row["id"],
                    "pred_category": labels[0],
                    "pred_operational_domain": labels[1],
                    "pred_region": labels[2],
                }
            ]
        )
        record.to_csv(out_path, mode="a", header=write_header, index=False)
        write_header = False
        if n % 25 == 0 or n == len(todo):
            print(f"  scored {n}/{len(todo)}", flush=True)


# ---------------------------------------------------------------------------
# Report (offline).
# ---------------------------------------------------------------------------


def _accuracy_line(name: str, correct: int, n: int) -> str:
    lo, hi = wilson_interval(correct, n)
    return f"  {name:9s}: {correct / n:6.1%}  [{lo:.1%}, {hi:.1%}]  ({correct}/{n})"


def _paired_section(
    truth: pd.DataFrame, base: pd.DataFrame, exem: pd.DataFrame, label_cols: dict
) -> list[str]:
    merged = truth.merge(
        base.rename(columns=lambda c: c.replace("pred_", "base_") if c != "id" else c),
        on="id",
    ).merge(
        exem.rename(columns=lambda c: c.replace("pred_", "exem_") if c != "id" else c),
        on="id",
    )
    lines = []
    n = len(merged)
    for axis in AXES:
        truth_col = label_cols[axis]
        base_ok = merged[truth_col] == merged[f"base_{axis}"]
        exem_ok = merged[truth_col] == merged[f"exem_{axis}"]
        base_only_wrong = int((~base_ok & exem_ok).sum())
        exem_only_wrong = int((base_ok & ~exem_ok).sum())
        p = mcnemar_exact(exem_only_wrong, base_only_wrong)
        lines.append(f"-- {axis} (n={n}) " + "-" * (40 - len(axis)))
        lines.append(_accuracy_line("baseline", int(base_ok.sum()), n))
        lines.append(_accuracy_line("exemplar", int(exem_ok.sum()), n))
        lines.append(
            f"  paired: exemplar fixed {base_only_wrong}, broke {exem_only_wrong}"
            f"; McNemar exact p={p:.4f}"
        )
        lines.append("")
    return lines


def build_report() -> str:
    """Assemble ``evals/exemplar_eval.txt`` from whichever arm CSVs exist.

    Returns:
        The report text (also written to disk).
    """
    lines = [
        "=" * 62,
        f"kNN-EXEMPLAR FEW-SHOT EXPERIMENT (k={DEFAULT_K}, ADR-019)",
        "=" * 62,
        "",
        "Pool: 300 judge-labeled scale rows (category+domain only; no region",
        "labels exist in the pool). Prior going in is double-negative:",
        "ADR-012 (neighbor docs) and ADR-018's amendment (keyword features).",
        "",
    ]
    have = {arm: os.path.exists(path) for arm, path in ARM_PATHS.items()}

    if have["scale-baseline"] and have["scale-exemplar"]:
        pool = _load_pool()
        truth = pool[["id", "category", "operational_domain"]]
        base = pd.read_csv(ARM_PATHS["scale-baseline"])
        exem = pd.read_csv(ARM_PATHS["scale-exemplar"])
        lines.append("== PRIMARY: scale set vs judge labels, paired, LOO retrieval ==")
        lines.append("   (baseline arm re-run fresh under the current prompt/model;")
        lines.append("    the stored scale_predictions workhorse column predates v3)")
        lines += _paired_section(truth, base, exem, {axis: axis for axis in AXES})
    else:
        lines.append("== PRIMARY: scale arms not yet run ==\n")

    if have["gold-exemplar"]:
        gold = pd.read_csv(GOLD_PATH).rename(columns={"domain": "operational_domain"})
        base = pd.read_csv(GOLD_BASELINE_PATH)[
            ["id", "pred_category", "pred_operational_domain", "pred_region"]
        ]
        exem = pd.read_csv(ARM_PATHS["gold-exemplar"])
        lines.append("== SECONDARY (directional, n=54): gold vs human labels ==")
        lines.append("   (baseline = stored v3 run, same prompt/model -- fair anchor)")
        lines += _paired_section(
            gold[["id", "category", "operational_domain"]],
            base,
            exem,
            {axis: axis for axis in AXES},
        )
        merged = gold.merge(exem, on="id")
        base_merged = gold.merge(base, on="id", suffixes=("", "_b"))
        exem_region = int((merged["region"] == merged["pred_region"]).sum())
        base_region = int((base_merged["region"] == base_merged["pred_region"]).sum())
        lines.append("-- region GUARDRAIL (exemplars carry no region labels) ----")
        lines.append(_accuracy_line("baseline", base_region, len(base_merged)))
        lines.append(_accuracy_line("exemplar", exem_region, len(merged)))
        lines.append("  pass = no degradation; region is reported, not optimized")
        lines.append("")
    else:
        lines.append("== SECONDARY: gold exemplar arm not yet run ==\n")

    unclassified = []
    for arm, path in ARM_PATHS.items():
        if os.path.exists(path):
            frame = pd.read_csv(path)
            bad = frame[
                (
                    frame[[c for c in frame.columns if c.startswith("pred_")]]
                    == UNCLASSIFIED
                ).any(axis=1)
            ]["id"].tolist()
            if bad:
                unclassified.append(f"  {arm}: {', '.join(bad)}")
    if unclassified:
        lines.append("-- rows sentinelled as unclassified (counted as misses) ----")
        lines += unclassified
        lines.append("")
    lines.append("=" * 62)
    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)
    return report


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=sorted(ARM_PATHS))
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    args = parser.parse_args()
    if args.run:
        run_arm(args.run, k=args.k)
    if args.report:
        print(build_report())
    if not args.run and not args.report:
        parser.error("nothing to do: pass --run <arm> and/or --report")


if __name__ == "__main__":
    main()
