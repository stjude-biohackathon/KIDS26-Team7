"""In-memory sentinel masking and exact restoration at model boundaries."""
from collections import Counter
import re
from uuid import uuid4

from pipeline.evaluator import _CONCENTRATION_RE, _DOSE_RE, _TEMPERATURE_RE, _PHONE_RE, _SHORT_PHONE_RE

# Include nonclinical numbers too: they may encode frequencies or hydration.
_VALUES = re.compile('|'.join('(?:' + p + ')' for p in (
    _CONCENTRATION_RE.pattern, _PHONE_RE.pattern, _SHORT_PHONE_RE.pattern,
    _TEMPERATURE_RE.pattern, _DOSE_RE.pattern, r'\d+(?:[.,]\d+)*',
)))
_SENTINEL = re.compile(r'\[\[CLEAR_[a-f0-9]+_\d+\]\]')


class ProtectionError(ValueError):
    """A model failed exact protected-value preservation."""


class ProtectedText:
    def __init__(self, text: str):
        if '[[CLEAR_' in text:
            raise ProtectionError('Input contains reserved protection markers.')
        self.values: dict[str, str] = {}
        reverse = {}
        namespace = uuid4().hex
        def mask(match):
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
        if set(tokens) - self.values.keys() or (require_all and tokens != self.counts):
            raise ProtectionError('Protected values were omitted, duplicated, or changed by the model.')
        remainder = _SENTINEL.sub('', response)
        if '[[CLEAR_' in remainder or (require_all and _VALUES.search(remainder)):
            raise ProtectionError('Model output contains altered markers or new numeric values.')
        return _SENTINEL.sub(lambda m: self.values[m.group()], response)
