"""Offline readability and verbatim checks for Track A's mock pipeline."""

import math
import re

import textstat

from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics, SafetyJudgeResult


def extract_verbatim_tokens(orders: ClinicalOrders) -> list[str]:
    """Keep structured values exactly as supplied, including units and formatting."""
    values = [med.dose for med in orders.medications] + [
        orders.urgent_fever_threshold, orders.emergency_fever_threshold,
        orders.daytime_phone, orders.after_hours_phone, orders.emergency_phone,
    ]
    # A shared daytime/after-hours number needs only one match. dict preserves
    # input order so the UI's missing-value list stays predictable.
    return list(dict.fromkeys(value for value in values if value))


def check_verbatim(text: str, orders: ClinicalOrders) -> tuple[list[str], list[str]]:
    """Return exact matches and missing values, without language-specific scoring."""
    tokens = extract_verbatim_tokens(orders)
    matches, mismatches = [], []
    for token in tokens:
        # Escape punctuation such as decimal points so it is matched literally.
        # Boundaries prevent 5 mg matching inside 15 mg, 0.5 mg, or 5 mg/kg.
        # Do not normalize case, spaces, degree signs, or phone formatting.
        pattern = r"(?<![\w.,/+\-−])" + re.escape(token) + r"(?!\w|\s*/|\.\d)"
        found = re.search(pattern, text) is not None
        (matches if found else mismatches).append(token)
    return matches, mismatches


def evaluate_text(text: str, orders: ClinicalOrders) -> EvaluationMetrics:
    """Measure English wording without rewriting it or claiming clinical approval."""
    if not text.strip():
        raise ValueError("Instruction text must not be empty.")
    try:
        fkgl = float(textstat.flesch_kincaid_grade(text))
    except Exception:
        # The schema has no 'unavailable score'. Stop instead of fabricating one,
        # and keep dependency errors (which may contain input text) out of logs.
        raise ValueError("Readability calculation failed; no evaluation was produced.") from None
    if not math.isfinite(fkgl):
        raise ValueError("Readability calculation returned an invalid score.")

    matches, mismatches = check_verbatim(text, orders)
    total = len(matches) + len(mismatches)

    # Report the two thresholds separately; a score of 4.5 is not in the target
    # range even though it is inside the spec's wider review bounds.
    readability = (
        "FKGL target met (5.0–6.9)." if 5.0 <= fkgl <= 6.9
        else "FKGL target not met (5.0–6.9)."
    )
    if fkgl < 4.0 or fkgl > 7.0:
        readability += " Readability outside review bounds (4.0–7.0)."

    return EvaluationMetrics(
        fkgl_score=fkgl,
        verbatim_matches=matches,
        verbatim_mismatches=mismatches,
        verbatim_match_percent=100.0 * len(matches) / total if total else 100.0,
        safety_judge=SafetyJudgeResult(
            overall_verdict="FLAGGED_FOR_REVIEW" if mismatches else "NEEDS_REVIEW",
            explanation=(
                "Mock checks only; clinical and authorized Spanish review remain required. "
                + ("Required verbatim values are missing or changed." if mismatches
                   else "All supplied protected values were found verbatim.")
                + " " + readability
            ),
        ),
    )
