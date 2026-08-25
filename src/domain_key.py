"""The scale judge key with the ADR-028 domain corrections applied.

The frozen key files (``evals/scale_predictions_v3.csv``,
``evals/scale_ext_predictions.csv``) are records and are never edited. The
2026-08-23 audit (``evals/domain_error_audit.md``) found their
``judge_operational_domain`` column unstable at the margins -- including one
snippet keyed two different ways -- so ADR-028 ratified two rubric rules and an
owner-adjudicated corrections overlay
(``evals/scale_domain_key_corrections.csv``). This module is the only
sanctioned way to read the corrected key: future domain-axis experiments call
:func:`corrected_key` instead of consuming the raw column.

Published records and past verdicts are NOT re-scored through this module; the
overlay is opt-in for new work, and the drift guards below refuse rather than
silently mis-apply when either file moves under the other.
"""

from __future__ import annotations

import pandas as pd

from classify import DOMAINS

CORRECTIONS_PATH = "evals/scale_domain_key_corrections.csv"

DOMAIN_COLUMN = "judge_operational_domain"

_REQUIRED_COLUMNS = [
    "id",
    "judge_operational_domain_old",
    "judge_operational_domain_new",
    "rule",
    "reason",
]


def load_corrections(path: str = CORRECTIONS_PATH) -> pd.DataFrame:
    """Load and validate the corrections overlay.

    Args:
        path: The overlay CSV.

    Returns:
        The overlay frame, string-typed.

    Raises:
        ValueError: If a required column is missing, an id repeats (two
            corrections for one row cannot both be the ruling), a new label is
            outside the domain enum, or a correction is a no-op (old == new --
            a row that changes nothing does not belong in a corrections file).
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing required column(s): {missing}")
    ids = list(frame["id"])
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(
            f"{path} carries more than one correction for {duplicated} -- "
            "two rulings for one row cannot both be the ruling."
        )
    bad = sorted(set(frame["judge_operational_domain_new"]) - set(DOMAINS))
    if bad:
        raise ValueError(
            f"{path} corrects rows to label(s) outside the domain enum: {bad}"
        )
    noop = sorted(
        frame.loc[
            frame["judge_operational_domain_old"]
            == frame["judge_operational_domain_new"],
            "id",
        ]
    )
    if noop:
        raise ValueError(
            f"{path} carries no-op correction(s) for {noop} -- examined-but-"
            "unchanged rows belong in the .notes.md companion, not the overlay."
        )
    return frame


def corrected_key(
    key: pd.DataFrame, corrections: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Apply the ADR-028 corrections to a loaded key frame.

    Args:
        key: A key frame carrying ``id`` and ``judge_operational_domain``
            (e.g. the concatenated frozen key files).
        corrections: A pre-loaded overlay, or ``None`` to load
            :data:`CORRECTIONS_PATH`.

    Returns:
        A copy of ``key`` with the corrected domain labels. No other column
        is touched.

    Raises:
        ValueError: If a correction names an id the key does not contain, or
            if a correction's recorded old label does not match what the key
            actually holds -- either means the key or the overlay moved under
            the other, and applying the overlay anyway would relabel a row
            nobody adjudicated.
    """
    if corrections is None:
        corrections = load_corrections()
    result = key.copy()
    key_ids = set(result["id"].astype(str))
    unknown = sorted(set(corrections["id"]) - key_ids)
    if unknown:
        raise ValueError(
            f"correction(s) for id(s) the key does not contain: {unknown}. "
            "The overlay was adjudicated against a different key."
        )
    indexed = result.set_index(result["id"].astype(str))
    for _, row in corrections.iterrows():
        current = str(indexed.at[row["id"], DOMAIN_COLUMN])
        if current != row["judge_operational_domain_old"]:
            raise ValueError(
                f"correction for {row['id']} expects the key to hold "
                f"{row['judge_operational_domain_old']!r} but it holds "
                f"{current!r}. The key moved under the overlay; re-adjudicate "
                "before applying."
            )
    mapping = dict(zip(corrections["id"], corrections["judge_operational_domain_new"]))
    mask = result["id"].astype(str).isin(mapping)
    result.loc[mask, DOMAIN_COLUMN] = result.loc[mask, "id"].astype(str).map(mapping)
    return result
