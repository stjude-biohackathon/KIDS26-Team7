"""Offline readability and verbatim checks for Track A's mock pipeline."""

import math
import re

import textstat

from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics, SafetyJudgeResult

# This file makes a report card: how hard is the English to read, and are the
# required values still present? It does not rewrite text or approve medical advice.


def extract_verbatim_tokens(orders: ClinicalOrders) -> list[str]:
    """Keep structured values exactly as supplied, including units and formatting."""
    # Here, a "token" means a complete protected value such as "5 mg" or "911".
    # It is not an LLM token. Build the checklist from the original orders.
    values = [med.dose for med in orders.medications] + [
        orders.urgent_fever_threshold, orders.emergency_fever_threshold,
        orders.daytime_phone, orders.after_hours_phone, orders.emergency_phone,
    ]
    # Skip empty fields and count identical values once. For example, a shared
    # daytime/after-hours number needs only one match. dict keeps the original order.
    return list(dict.fromkeys(value for value in values if value))


def check_verbatim(text: str, orders: ClinicalOrders) -> tuple[list[str], list[str]]:
    """Return exact matches and missing values, without language-specific scoring."""
    tokens = extract_verbatim_tokens(orders)
    # Make two lists for the UI: values found exactly, and values needing attention.
    matches, mismatches = [], []
    for token in tokens:
        # Escape punctuation such as decimal points so it is matched literally.
        # Boundaries prevent 5 mg matching inside 15 mg, 0.5 mg, or 5 mg/kg.
        # Do not normalize case, spaces, degree signs, or phone formatting.
        pattern = r"(?<![\w.,/+\-−])" + re.escape(token) + r"(?!\w|\s*/|\.\d)"
        # re.search looks for the value anywhere in the text. Finding it proves
        # presence only; it cannot tell whether it belongs to the right medication
        # or whether conflicting advice appears in another sentence.
        found = re.search(pattern, text) is not None
        (matches if found else mismatches).append(token)
    return matches, mismatches


def evaluate_text(text: str, orders: ClinicalOrders) -> EvaluationMetrics:
    """Measure English wording without rewriting it or claiming clinical approval."""
    if not text.strip():
        raise ValueError("Instruction text must not be empty.")
    try:
        # FKGL estimates a US school reading grade using sentence length and
        # syllables per word. A score near 6 means roughly sixth-grade wording.
        # It measures writing complexity, not medical accuracy or understanding.
        fkgl = float(textstat.flesch_kincaid_grade(text))
    except Exception:
        # The schema has no 'unavailable score'. Stop instead of fabricating one,
        # and keep dependency errors (which may contain input text) out of logs.
        raise ValueError("Readability calculation failed; no evaluation was produced.") from None
    if not math.isfinite(fkgl):
        # NaN ("not a number") and infinity are not usable reading-level scores.
        raise ValueError("Readability calculation returned an invalid score.")

    # Run the separate value check after calculating the reading-level score.
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

    # Package the results in the shared schema so the UI knows where to find them.
    # For example, 4 matching values out of 5 gives an 80% match percentage.
    # With no required values the percentage is 100%; that is an empty checklist,
    # not proof that the instructions are safe.
    return EvaluationMetrics(
        fkgl_score=fkgl,
        verbatim_matches=matches,
        verbatim_mismatches=mismatches,
        verbatim_match_percent=100.0 * len(matches) / total if total else 100.0,
        # This is a simple mock verdict, not an LLM's clinical assessment.
        # Missing values raise a flag; even a clean check still needs human review.
        # Other judge fields keep schema defaults, not measured clinical findings.
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
