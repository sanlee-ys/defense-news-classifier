"""L4: multi-agent classification -- triage -> classify -> critic, with a backward edge.

The ladder's last level, built to the Accepted spec (docs/specs/l4-multi-agent.md,
all three design forks resolved 2026-07-25):

- **Triage** pins verbatim evidence spans per axis (or ``none stated``) so the
  critic argues about quoted text, not preferences.
- **Classify** is the SHIPPED ``classify()`` call, byte-identical to production
  and BLIND to triage's output (fork 1) -- the pipeline measures the critic's
  marginal value, not a different classifier.
- **Critic** reviews snippet + evidence + label under a narrow charter: it may
  challenge only on **rubric-checkable evidence claims** (a place stated or not
  stated; a contract verb present or absent), covering ALL THREE axes (fork 3),
  and every challenge must cite the rubric rule and the evidence gap. An
  invalid challenge fails closed to accept, logged.
- **The backward edge:** a valid challenge triggers ONE re-classify (fork 2:
  bounce cap 1) whose prompt carries the reviewer's note. The critic reviews
  the re-classified label once more; a second challenge marks the row
  ``contested`` and the re-classified label stands -- never loop, never
  escalate to a bigger model (ADR-013's dead end).

The honest hypothesis this pipeline exists to test: the seven gold rows whose
``global`` region was pulled to a specific region by US-actor inference are
rubric-checkable misses -- exactly critic-shaped. Named-cluster accounting is
the report's headline; McNemar and the measured cost multiplier sit beside it.

All three agents run the workhorse model (SYS-002). Audit trail: every triage
note, label, challenge, bounce, and verdict is appended to a per-run JSONL
under ``evals/l4/`` (gitignored, replay-viewer format family). Predictions
append per row and re-runs resume by skipping scored ids.

Offline (free): ``--dry-run`` end-to-end with a canned backend; ``--report``
builds ``evals/l4_eval.txt`` from whatever prediction CSVs exist. Live (San
drives; ~120 extra calls on gold, ~630 on the scale do-no-harm pass):

    uv run --env-file .env python src/l4_pipeline.py --run gold
    uv run --env-file .env python src/l4_pipeline.py --run scale
    uv run python src/l4_pipeline.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from typing import Protocol, cast

import anthropic
import pandas as pd
from anthropic.types import ToolParam, ToolUseBlock

from baseline_ml import mcnemar_exact
from classify import CATEGORIES, DOMAINS, MODEL, REGIONS, SYSTEM_PROMPT, make_client
from eval import wilson_interval
from exemplar_eval import pending_rows
from optimize import (
    UNCLASSIFIED,
    _classify_retry,
    _salvage_labels,
    extract_region_block,
)

GOLD_PATH = "data/gold/gold.csv"
GOLD_BASELINE_PATH = "evals/gold_predictions_v3.csv"
SCALE_BASELINE_PATH = (
    "evals/exemplar_scale_baseline.csv"  # fresh v3-prompt run (ADR-019)
)
REPORT_PATH = "evals/l4_eval.txt"
AUDIT_DIR = "evals/l4"

RUN_PATHS = {
    "gold": "evals/l4_gold_predictions.csv",
    "scale": "evals/l4_scale_predictions.csv",
}

AXES3 = ("category", "operational_domain", "region")
NONE_STATED = "none stated"


# ---------------------------------------------------------------------------
# Agent prompts + tools.
# ---------------------------------------------------------------------------

TRIAGE_SYSTEM_PROMPT = """You are the triage agent in a defense-news \
classification pipeline. For the snippet you are given, quote the VERBATIM \
span of text that would support a call on each of three axes:

- category (procurement / operations / policy / technology / industry): the \
span naming what the story is primarily about (a contract verb, a deployment, \
a bill, an R&D milestone, an earnings statement).
- operational_domain (air / land / sea / cyber / space / multi): the span \
naming the platform, unit, or domain activity.
- region: the span naming a concrete place (a base, city, sea, strait, or \
country). If the snippet states NO place, you MUST report exactly "none \
stated" -- do not infer a location from the actor's nationality.

Rules: each evidence value is either a verbatim quote from the snippet or \
exactly "none stated". Never paraphrase. Also list any axes you consider \
genuinely contentious given the evidence."""

TRIAGE_TOOL: ToolParam = {
    "name": "report_evidence",
    "description": "Report the verbatim evidence span (or 'none stated') per axis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category_evidence": {"type": "string"},
            "domain_evidence": {"type": "string"},
            "region_evidence": {"type": "string"},
            "ambiguous_axes": {
                "type": "array",
                "items": {"type": "string", "enum": list(AXES3)},
            },
        },
        "required": [
            "category_evidence",
            "domain_evidence",
            "region_evidence",
            "ambiguous_axes",
        ],
    },
}

# The critic's charter embeds the live region rubric verbatim (the axis the
# hypothesis lives on), extracted from the shipped prompt so the two can never
# drift -- the same never-retype discipline as the contract artifact.
CRITIC_SYSTEM_PROMPT = f"""You are the critic in a defense-news classification \
pipeline. You receive a snippet, the triage agent's verbatim evidence spans, \
and a proposed label. Your charter is NARROW:

You may challenge ONLY on a rubric-checkable evidence claim -- a factual \
mismatch between the label and what the text states. Examples: the region \
label names a specific theater but the snippet states no place (triage region \
evidence is "none stated"); the category is procurement but no contract, \
award, or budget language exists in the snippet. You may NOT challenge \
because you would have judged a borderline case differently. If the label is \
defensible from the evidence, ACCEPT.

The region rubric (authoritative):

{extract_region_block(SYSTEM_PROMPT)}

Label vocabularies: category {sorted(CATEGORIES)}; operational_domain \
{sorted(DOMAINS)}; region {sorted(REGIONS)}.

A challenge MUST name the axis, quote the rubric rule being violated, and \
state the evidence gap. A challenge missing any of these is invalid and will \
be discarded."""

CRITIC_TOOL: ToolParam = {
    "name": "review_label",
    "description": "Accept the label, or challenge one axis on a rubric-checkable evidence claim.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["accept", "challenge"]},
            "axis": {"type": "string", "enum": list(AXES3)},
            "rubric_rule": {
                "type": "string",
                "description": "The rubric rule violated, quoted or closely paraphrased.",
            },
            "evidence_gap": {
                "type": "string",
                "description": "What the text states (or fails to state) that contradicts the label.",
            },
        },
        "required": ["verdict"],
    },
}


def challenge_violations(review: dict) -> list[str]:
    """Why a challenge is invalid (empty list = valid, or verdict is accept).

    The fail-closed gate (spec §2): a challenge without a named axis, a cited
    rubric rule, and a stated evidence gap is discarded and the label stands.
    Deterministic and free, mirroring the loops' pre-scoring guards.

    Args:
        review: The critic tool payload.

    Returns:
        Violation strings; empty when the review is actionable.
    """
    if review.get("verdict") != "challenge":
        return []
    problems = []
    if review.get("axis") not in AXES3:
        problems.append("challenge names no valid axis")
    for field_name in ("rubric_rule", "evidence_gap"):
        value = review.get(field_name)
        if not isinstance(value, str) or len(value.strip()) < 10:
            problems.append(f"challenge lacks a substantive {field_name}")
    return problems


def reviewer_note(review: dict) -> str:
    """The bounce prompt suffix built from a VALID challenge.

    Args:
        review: A validated challenge payload.

    Returns:
        Text appended to the shipped system prompt for the single re-classify.
    """
    return (
        "\n\nA reviewer has flagged this snippet's initial classification on the "
        f"'{review['axis']}' axis. Rubric rule at issue: {review['rubric_rule']} "
        f"Evidence gap: {review['evidence_gap']} "
        "Re-check that axis strictly against the text; change it only if the "
        "reviewer is right, and leave every other axis alone unless the same "
        "evidence forces a change."
    )


# ---------------------------------------------------------------------------
# Backends.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentReply:
    """One agent call's payload plus tokens spent."""

    payload: dict
    tokens: int


class L4Backend(Protocol):
    """The seam between the driver and anything that costs money."""

    def triage(self, text: str) -> AgentReply:
        """Evidence spans per axis."""
        ...

    def classify(self, text: str, note: str = "") -> AgentReply:
        """The shipped classifier; ``note`` is the reviewer suffix on a bounce."""
        ...

    def critic(self, text: str, evidence: dict, label: dict) -> AgentReply:
        """Accept or challenge."""
        ...


class AnthropicL4Backend:
    """Live backend -- all three agents on the workhorse model."""

    def __init__(self, client: anthropic.Anthropic, model: str = MODEL) -> None:
        """Build the live backend.

        Args:
            client: Authenticated Anthropic client.
            model: Model id for all three agents (SYS-002: no premium tier).
        """
        self.client = client
        self.model = model

    def _tool_call(self, system: str, tool: ToolParam, message: str) -> AgentReply:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": message}],
        )
        tokens = int(response.usage.input_tokens) + int(response.usage.output_tokens)
        block = next(b for b in response.content if isinstance(b, ToolUseBlock))
        return AgentReply(payload=cast(dict, block.input), tokens=tokens)

    def triage(self, text: str) -> AgentReply:
        """Evidence spans for one snippet."""
        return self._tool_call(TRIAGE_SYSTEM_PROMPT, TRIAGE_TOOL, text)

    def classify(self, text: str, note: str = "") -> AgentReply:
        """The shipped call (optionally with the reviewer note appended).

        Token accounting note: ``classify()`` does not surface usage (its
        return contract is pinned), so classify calls are counted as calls,
        not tokens -- the report's cost axis is calls-per-row, which is the
        number ADR-013 taught us to lead with anyway.
        """
        try:
            pred = _classify_retry(
                self.client, text, model=self.model, system_prompt=SYSTEM_PROMPT + note
            )
        except Exception as exc:
            from classify import InvalidLabelError

            if not isinstance(exc, InvalidLabelError):
                raise
            cat, dom, reg = _salvage_labels(exc)
            pred = {"category": cat, "operational_domain": dom, "region": reg}
        return AgentReply(payload=pred, tokens=0)

    def critic(self, text: str, evidence: dict, label: dict) -> AgentReply:
        """One review of snippet + evidence + label."""
        message = (
            f"Snippet:\n{text}\n\nTriage evidence:\n{json.dumps(evidence, indent=2)}"
            f"\n\nProposed label:\n{json.dumps(label, indent=2)}"
        )
        return self._tool_call(CRITIC_SYSTEM_PROMPT, CRITIC_TOOL, message)


class DryRunBackend:
    """Deterministic offline backend exercising every path, including contested.

    Classification heuristics here are deliberately crude -- the dry run
    exists to drive the pipeline's control flow (accept, challenge->fixed,
    challenge->contested, invalid-challenge->fail-closed), not to classify
    well. Behavior: snippets containing no place-like token get region
    'americas' (the exact US-actor failure the critic hunts), the critic
    challenges those, and the re-classify heeds the note -- except snippets
    containing 'stubborn', where the re-classify repeats itself and the row
    lands contested. Snippets containing 'vague' produce an INVALID challenge
    (no rubric rule), exercising the fail-closed gate.
    """

    _PLACES = (
        "pacific",
        "china",
        "sea",
        "europe",
        "ukraine",
        "gulf",
        "korea",
        "japan",
        "africa",
        "base",
        "washington",
        "california",
        "atlantic",
    )

    def _has_place(self, text: str) -> bool:
        lowered = text.lower()
        return any(p in lowered for p in self._PLACES)

    def triage(self, text: str) -> AgentReply:
        """Canned evidence: first 8 words as cat/dom spans; place token or none."""
        words = " ".join(text.split()[:8])
        region_ev = NONE_STATED
        if self._has_place(text):
            lowered = text.lower()
            region_ev = next(p for p in self._PLACES if p in lowered)
        return AgentReply(
            payload={
                "category_evidence": words,
                "domain_evidence": words,
                "region_evidence": region_ev,
                "ambiguous_axes": [],
            },
            tokens=0,
        )

    def classify(self, text: str, note: str = "") -> AgentReply:
        """Heuristic label; heeds the reviewer note unless the text is 'stubborn'."""
        region = "indo-pacific" if self._has_place(text) else "americas"
        if note and "stubborn" not in text.lower():
            region = "global"
        return AgentReply(
            payload={
                "category": "operations",
                "operational_domain": "sea" if "ship" in text.lower() else "multi",
                "region": region,
            },
            tokens=0,
        )

    def critic(self, text: str, evidence: dict, label: dict) -> AgentReply:
        """Challenge no-place rows labeled with a specific region; else accept."""
        if evidence["region_evidence"] == NONE_STATED and label["region"] != "global":
            if "vague" in text.lower():
                return AgentReply(payload={"verdict": "challenge"}, tokens=0)
            return AgentReply(
                payload={
                    "verdict": "challenge",
                    "axis": "region",
                    "rubric_rule": "Do not guess a region from world knowledge "
                    "when the text names no place.",
                    "evidence_gap": "Triage reports no stated place; the label "
                    "names a specific theater.",
                },
                tokens=0,
            )
        return AgentReply(payload={"verdict": "accept"}, tokens=0)


# ---------------------------------------------------------------------------
# The driver.
# ---------------------------------------------------------------------------


def process_row(backend: L4Backend, text: str) -> tuple[dict, list[dict], int]:
    """Run one snippet through triage -> classify -> critic (+ one bounce max).

    Args:
        backend: Live or dry-run backend.
        text: The snippet.

    Returns:
        ``(final_label_with_status, audit_events, calls_made)`` where status is
        ``accepted`` / ``fixed`` / ``contested`` / ``fail_closed``.
    """
    events: list[dict] = []
    triage = backend.triage(text)
    events.append({"event": "triage", "payload": triage.payload})
    first = backend.classify(text)
    events.append({"event": "classify", "payload": first.payload})
    review = backend.critic(text, triage.payload, first.payload)
    events.append({"event": "critic", "payload": review.payload})
    calls = 3

    if review.payload.get("verdict") != "challenge":
        return {**first.payload, "l4_status": "accepted"}, events, calls

    violations = challenge_violations(review.payload)
    if violations:
        # Fail closed: an unsupported challenge never moves a label.
        events.append({"event": "challenge_discarded", "violations": violations})
        return {**first.payload, "l4_status": "fail_closed"}, events, calls

    # The backward edge -- exactly one bounce.
    second = backend.classify(text, note=reviewer_note(review.payload))
    events.append({"event": "reclassify", "payload": second.payload})
    re_review = backend.critic(text, triage.payload, second.payload)
    events.append({"event": "critic_second", "payload": re_review.payload})
    calls += 2
    status = "fixed" if re_review.payload.get("verdict") == "accept" else "contested"
    return {**second.payload, "l4_status": status}, events, calls


def _rows_for(run: str) -> pd.DataFrame:
    if run == "gold":
        return pd.read_csv(GOLD_PATH)[["id", "text"]]
    from baseline_ml import load_train

    return load_train()[["id", "text"]]


def run_pipeline(run: str, backend: L4Backend, audit_path: str | None = None) -> str:
    """Score one dataset through the pipeline, resume-safe, with audit trail.

    Args:
        run: ``"gold"`` or ``"scale"``.
        backend: Live or dry-run backend.
        audit_path: Audit JSONL override (tests); default timestamped under
            ``evals/l4/``.

    Returns:
        The predictions CSV path.
    """
    rows = _rows_for(run)
    out_path = RUN_PATHS[run]
    todo = pending_rows(rows, out_path)
    print(f"l4 {run}: {len(todo)}/{len(rows)} rows to score (resume-safe)", flush=True)
    if todo.empty:
        return out_path
    if audit_path is None:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        audit_path = os.path.join(AUDIT_DIR, f"audit_{run}_{stamp}.jsonl")
    write_header = not os.path.exists(out_path)
    for n, (_, row) in enumerate(todo.iterrows(), start=1):
        label, events, calls = process_row(backend, row["text"])
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": row["id"], "events": events}) + "\n")
        pd.DataFrame(
            [
                {
                    "id": row["id"],
                    "pred_category": label["category"],
                    "pred_operational_domain": label["operational_domain"],
                    "pred_region": label["region"],
                    "l4_status": label["l4_status"],
                    "calls": calls,
                }
            ]
        ).to_csv(out_path, mode="a", header=write_header, index=False)
        write_header = False
        if n % 25 == 0 or n == len(todo):
            print(f"  scored {n}/{len(todo)}", flush=True)
    return out_path


# ---------------------------------------------------------------------------
# Report (offline).
# ---------------------------------------------------------------------------


def _accuracy_line(name: str, correct: int, n: int) -> str:
    lo, hi = wilson_interval(correct, n)
    return f"  {name:9s}: {correct / n:6.1%}  [{lo:.1%}, {hi:.1%}]  ({correct}/{n})"


def build_report() -> str:
    """Assemble ``evals/l4_eval.txt`` from whichever run CSVs exist.

    Returns:
        The report text (also written to disk).
    """
    lines = [
        "=" * 62,
        "L4 MULTI-AGENT PIPELINE -- triage -> classify -> critic (ADR-020)",
        "=" * 62,
        "",
        "Hypothesis under test: the 7 gold rows where region=global was",
        "pulled to a specific theater are rubric-checkable, critic-shaped",
        "misses. All agents run the workhorse; classify is the shipped call.",
        "",
    ]

    if os.path.exists(RUN_PATHS["gold"]):
        gold = pd.read_csv(GOLD_PATH).rename(columns={"domain": "operational_domain"})
        base = pd.read_csv(GOLD_BASELINE_PATH)
        l4 = pd.read_csv(RUN_PATHS["gold"])
        merged = gold.merge(
            base.rename(
                columns=lambda c: c.replace("pred_", "base_") if c != "id" else c
            )[["id", "base_category", "base_operational_domain", "base_region"]],
            on="id",
        ).merge(
            l4.rename(columns=lambda c: c.replace("pred_", "l4_") if c != "id" else c),
            on="id",
        )
        n = len(merged)
        lines.append(
            "== PRIMARY: gold (n=54) vs human labels, paired vs stored v3 run =="
        )
        for axis in AXES3:
            base_ok = merged[axis] == merged[f"base_{axis}"]
            l4_ok = merged[axis] == merged[f"l4_{axis}"]
            fixed = int((~base_ok & l4_ok).sum())
            broke = int((base_ok & ~l4_ok).sum())
            p = mcnemar_exact(broke, fixed)
            lines.append(f"-- {axis} " + "-" * (46 - len(axis)))
            lines.append(_accuracy_line("baseline", int(base_ok.sum()), n))
            lines.append(_accuracy_line("L4", int(l4_ok.sum()), n))
            lines.append(
                f"  paired: L4 fixed {fixed}, broke {broke}; McNemar exact p={p:.4f}"
            )
            lines.append("")

        # Named-cluster accounting: the rows whose HUMAN region label is
        # global but the stored baseline predicted a specific region.
        cluster = merged[
            (merged["region"] == "global") & (merged["base_region"] != "global")
        ]
        fixed_ids = cluster[cluster["l4_region"] == "global"]["id"].tolist()
        missed_ids = cluster[cluster["l4_region"] != "global"]["id"].tolist()
        lines.append("-- NAMED-CLUSTER ACCOUNTING (the headline; small-n, stated) --")
        lines.append(
            f"  cluster size {len(cluster)} (gold=global, baseline pulled to a region)"
        )
        lines.append(f"  fixed by L4  : {len(fixed_ids)}  {fixed_ids}")
        lines.append(f"  still missed : {len(missed_ids)}  {missed_ids}")
        lines.append("")
        lines += _flow_stats("gold", l4)
    else:
        lines.append("== PRIMARY: gold run not yet made ==\n")

    if os.path.exists(RUN_PATHS["scale"]):
        from baseline_ml import load_train

        truth = load_train()[["id", "category", "operational_domain"]]
        base = pd.read_csv(SCALE_BASELINE_PATH)
        l4 = pd.read_csv(RUN_PATHS["scale"])
        merged = truth.merge(
            base.rename(
                columns=lambda c: c.replace("pred_", "base_") if c != "id" else c
            )[["id", "base_category", "base_operational_domain"]],
            on="id",
        ).merge(
            l4.rename(columns=lambda c: c.replace("pred_", "l4_") if c != "id" else c),
            on="id",
        )
        n = len(merged)
        lines.append("== SECONDARY: scale (n=300) do-no-harm vs judge labels ==")
        lines.append("   (region has no scale answer key yet -- not scored;")
        lines.append("    baseline = ADR-019's fresh same-prompt arm, zero re-spend)")
        for axis in ("category", "operational_domain"):
            base_ok = merged[axis] == merged[f"base_{axis}"]
            l4_ok = merged[axis] == merged[f"l4_{axis}"]
            fixed = int((~base_ok & l4_ok).sum())
            broke = int((base_ok & ~l4_ok).sum())
            p = mcnemar_exact(broke, fixed)
            lines.append(f"-- {axis} " + "-" * (46 - len(axis)))
            lines.append(_accuracy_line("baseline", int(base_ok.sum()), n))
            lines.append(_accuracy_line("L4", int(l4_ok.sum()), n))
            lines.append(
                f"  paired: L4 fixed {fixed}, broke {broke}; McNemar exact p={p:.4f}"
            )
            lines.append("")
        lines += _flow_stats("scale", l4)
    else:
        lines.append("== SECONDARY: scale run not yet made ==\n")

    lines.append("=" * 62)
    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)
    return report


def _flow_stats(name: str, l4: pd.DataFrame) -> list[str]:
    counts = l4["l4_status"].value_counts().to_dict()
    challenged = sum(
        counts.get(status, 0) for status in ("fixed", "contested")
    ) + counts.get("fail_closed", 0)
    mean_calls = l4["calls"].mean()
    unclassified = l4[
        (l4[[c for c in l4.columns if c.startswith("pred_")]] == UNCLASSIFIED).any(
            axis=1
        )
    ]["id"].tolist()
    lines = [
        f"-- {name} pipeline flow / cost " + "-" * 30,
        f"  statuses     : {counts}",
        f"  challenge rate: {challenged}/{len(l4)} ({challenged / len(l4):.1%})",
        f"  calls per row : {mean_calls:.2f} (baseline 1.00)",
    ]
    if unclassified:
        lines.append(f"  sentinelled rows (counted as misses): {unclassified}")
    lines.append("")
    return lines


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=sorted(RUN_PATHS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.run:
        backend: L4Backend = (
            DryRunBackend() if args.dry_run else AnthropicL4Backend(make_client())
        )
        run_pipeline(args.run, backend)
    if args.report:
        print(build_report())
    if not args.run and not args.report:
        parser.error("nothing to do: pass --run <dataset> and/or --report")


if __name__ == "__main__":
    main()
