"""In-memory sentinel masking and exact restoration at model boundaries."""
from collections import Counter
import re
from uuid import uuid4

from pipeline.evaluator import (
    _CONCENTRATION_RE,
    _DOSE_RE,
    _EMERGENCY_NUMBER_RE,
    _PHONE_RE,
    _SHORT_PHONE_RE,
    _TEMPERATURE_RE,
)

# Protect clinical quantities instead of every number. This deliberately leaves
# incidental values such as age, list numbering, dates, and protocol versions
# available for simplification or omission when they are not instructions.
_TIMING_RE = re.compile(
    r"\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|times?)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_CLINICAL_MEASURE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:liters?|L|ounces?|oz|cups?|kg|lb|pounds?|cm|mm)\b",
    re.IGNORECASE,
)
_VALUES = re.compile('|'.join('(?:' + p + ')' for p in (
    _CONCENTRATION_RE.pattern, _PHONE_RE.pattern, _SHORT_PHONE_RE.pattern,
    _TEMPERATURE_RE.pattern, _DOSE_RE.pattern, _EMERGENCY_NUMBER_RE.pattern,
    _TIMING_RE.pattern, _PERCENT_RE.pattern, _CLINICAL_MEASURE_RE.pattern,
)), re.IGNORECASE)
_SENTINEL = re.compile(r'\[\[CLEAR_[a-f0-9]+_\d+\]\]')


def _is_age_context(text: str, match: re.Match) -> bool:
    """Exclude ages even when their unit resembles a clinical duration."""
    before = text[max(0, match.start() - 24):match.start()]
    after = text[match.end():match.end() + 12]
    return bool(
        re.search(r"\bage\s*:?\s*$", before, re.IGNORECASE)
        or re.match(r"\s*(?:old|of age)\b", after, re.IGNORECASE)
    )


def _protected_matches(text: str):
    return (match for match in _VALUES.finditer(text)
            if not _is_age_context(text, match))


class ProtectionError(ValueError):
    """A rejected response with optional in-memory, review-only draft details.

    The exception message never includes clinical text. Callers must not log
    the draft or findings; they are intended only for the clinician review.
    """
    def __init__(self, message: str, *, draft_text: str | None = None, findings=()):
        super().__init__(message)
        self.draft_text = draft_text
        self.findings = list(findings)


UNRESOLVED_VALUE = "[UNRESOLVED PROTECTED VALUE]"


def numeric_findings(source: str, candidate: str) -> list[str]:
    """Require every distinct source value at least once, with no new values."""
    expected = Counter(m.group() for m in _protected_matches(source))
    actual = Counter(m.group() for m in _protected_matches(candidate))
    findings = []
    for value in expected:
        if actual[value] == 0:
            findings.append(f"Missing protected value: {value} (required at least once, found 0).")
    for value in (v for v in actual if v not in expected):
        findings.append(f"Unexpected numeric value: {value}.")
    if UNRESOLVED_VALUE in candidate or '[[CLEAR_' in candidate.upper():
        findings.append("Unknown or altered protection marker remains unresolved.")
    return findings


class ProtectedText:
    def __init__(self, text: str):
        if '[[CLEAR_' in text:
            raise ProtectionError('Input contains reserved protection markers.')
        self.values: dict[str, str] = {}
        reverse = {}
        namespace = uuid4().hex
        def mask(match):
            if _is_age_context(text, match):
                return match.group()
            value = match.group()
            if value not in reverse:
                token = f'[[CLEAR_{namespace}_{len(reverse)}]]'
                reverse[value] = token
                self.values[token] = value
            return reverse[value]
        self.masked = _VALUES.sub(mask, text)
        self.counts = Counter(_SENTINEL.findall(self.masked))

    def restore(self, response: str, *, require_all: bool = True) -> str:
        tokens = Counter(_SENTINEL.findall(response))
        findings = []
        for token in self.values:
            if require_all and tokens[token] == 0:
                findings.append(f"Missing protected value: {self.values[token]} (required at least once, found 0).")
        if set(tokens) - self.values.keys():
            findings.append("Unknown protection marker returned by the model; its value cannot be recovered.")
        remainder = _SENTINEL.sub('', response)
        if '[[CLEAR_' in remainder.upper():
            findings.append("Unknown or altered protection marker returned by the model; its value cannot be recovered.")
        if require_all:
            numeric_remainder = re.sub(r'\[\[CLEAR_[^\]\r\n]*(?:\]\]?)?', '', remainder, flags=re.I)
            for value in dict.fromkeys(m.group() for m in _protected_matches(numeric_remainder)):
                findings.append(f"Unexpected numeric value: {value}.")
        if findings:
            # Restore only exact, known markers for display. Never invent a
            # missing value or guess what a corrupted marker was meant to be.
            draft = _SENTINEL.sub(lambda m: self.values.get(m.group(), UNRESOLVED_VALUE), response)
            draft = re.sub(r'\[\[CLEAR_[^\]\r\n]*(?:\]\]?)?', UNRESOLVED_VALUE, draft, flags=re.I)
            raise ProtectionError("Protected values failed validation; draft requires review.",
                                  draft_text=draft, findings=findings)
        return _SENTINEL.sub(lambda m: self.values[m.group()], response)
