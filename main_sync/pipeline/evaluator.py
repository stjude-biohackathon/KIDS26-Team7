"""Offline readability and verbatim checks for Track A's mock pipeline."""

import math
import re

import textstat

from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics, SafetyJudgeResult


_DOSE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?)\b")
# A product strength such as "100 mg/5 mL" is one value, not two. Splitting it
# would also produce tokens check_verbatim can never match, because it refuses
# a dose followed by "/" (guarding against 5 mg vs 5 mg/kg).
_CONCENTRATION_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|g)\s*/\s*\d+(?:\.\d+)?\s*(?:mL|kg)\b"
)
_TEMPERATURE_RE = re.compile(r"\d{2,3}(?:\.\d+)?\s*°?[FC]\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# Upstream order fields such as "555-0144 (Day Clinic, M-F 8am-5pm)" use short
# internal numbers, and emergency guidance is written as prose around "911".
_SHORT_PHONE_RE = re.compile(r"\b\d{3}-\d{4}\b")
_EMERGENCY_NUMBER_RE = re.compile(r"\b911\b")

_EXTRACTORS = {
    "dose": (_CONCENTRATION_RE, _DOSE_RE),
    "temperature": (_TEMPERATURE_RE,),
    "phone": (_PHONE_RE, _SHORT_PHONE_RE, _EMERGENCY_NUMBER_RE),
}


def extract_safety_values(value: str, kind: str) -> list[str]:
    """Pull the safety-critical values out of a field that also carries prose.

    Upstream orders bundle descriptive text with the protected value, e.g.
    "100.4°F (38.0°C)" or "555-0144 (Pediatric Hematology Day Clinic)". Locking
    the whole string would force a model to reproduce clinic names and opening
    hours word for word, so only the clinical values are locked. Every value
    found is returned — a dropped unit conversion is real content loss, not
    formatting — while unanchored prose yields nothing to lock.
    """
    found: list[str] = []
    consumed: list[tuple[int, int]] = []
    # Patterns are ordered most specific first; a narrower pattern must not
    # re-extract a fragment of a value a broader one already claimed (e.g.
    # "555-0100" inside "202-555-0100").
    for pattern in _EXTRACTORS[kind]:
        for match in pattern.finditer(value):
            start, end = match.span()
            if any(start < c_end and end > c_start for c_start, c_end in consumed):
                continue
            consumed.append((start, end))
            token = match.group(0).strip()
            if token and token not in found:
                found.append(token)
    return found


def extract_verbatim_tokens(orders: ClinicalOrders) -> list[str]:
    """Keep structured values exactly as supplied, including units and formatting."""
    fields = (
        [(med.dose, "dose") for med in orders.medications]
        + [
            (orders.urgent_fever_threshold, "temperature"),
            (orders.emergency_fever_threshold, "temperature"),
            (orders.daytime_phone, "phone"),
            (orders.after_hours_phone, "phone"),
            (orders.emergency_phone, "phone"),
        ]
    )
    values: list[str] = []
    for value, kind in fields:
        if not value:
            continue
        values.extend(extract_safety_values(value, kind))
    # A shared daytime/after-hours number needs only one match. dict preserves
    # input order so the UI's missing-value list stays predictable.
    return list(dict.fromkeys(values))


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


def red_flag_lines(text: str) -> list[str]:
    """Conservative exact-line guard for source warnings in clinical English."""
    return [line for line in text.splitlines() if line.strip() and re.search(
        r'red.flag|call (?:immediately|if)|seek help|chest pain|emergency room', line, re.I)]


def content_findings(source: str, candidate: str, orders: ClinicalOrders) -> tuple[list[str], list[str]]:
    """Missing source warnings and new safety values may not be waived by an LLM."""
    missing = [line for line in red_flag_lines(source) if line not in candidate]
    reference = source + '\n' + ' '.join(extract_verbatim_tokens(orders))
    unexpected = []
    for kind in ('dose', 'temperature', 'phone'):
        allowed = set(extract_safety_values(reference, kind))
        unexpected.extend(value for value in extract_safety_values(candidate, kind) if value not in allowed)
    return missing, unexpected
