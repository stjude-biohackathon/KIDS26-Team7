"""In-memory masking and exact restoration at every live model boundary."""
from collections import Counter
import re


class ProtectionError(ValueError):
    """A model response cannot be restored without changing protected values."""


class SentinelProtector:
    def __init__(self, values):
        self.values = sorted({value for value in values if value}, key=len, reverse=True)
        self.mapping = {}
        self.reverse = {}
        # Structured values win; all other numeric values are masked too.
        patterns = [re.escape(value) for value in self.values]
        units = r'(?:mcg|mg|mL|kg|g|%|tablets?|capsules?|drops?|hours?|minutes?|days?|weeks?|times)(?!\w)'
        patterns += [r'\+?\d[\d().\- ]{6,}\d',
                     r'[+−-]?\d+(?:[.,]\d+)*(?:\s*°?[FC](?!\w)|\s*' + units + r')?']
        self.pattern = re.compile('|'.join(patterns))
        self.tokens = re.compile(r'@@CLEAR_[A-Z]+@@')

    def mask(self, text):
        if '@@CLEAR_' in text:
            raise ProtectionError('Reserved sentinel text in input.')

        def substitute(match):
            value = match.group()
            if value not in self.reverse:
                number, letters = len(self.mapping), ''
                while True:
                    letters = chr(65 + number % 26) + letters
                    number = number // 26 - 1
                    if number < 0:
                        break
                token = f'@@CLEAR_{letters}@@'
                self.mapping[token] = value
                self.reverse[value] = token
            return self.reverse[value]

        return self.pattern.sub(substitute, text)

    def restore_translation(self, output, masked_input):
        if not isinstance(output, str) or not output.strip():
            raise ProtectionError('Translation is empty or unavailable.')
        expected = Counter(self.tokens.findall(masked_input))
        actual = Counter(self.tokens.findall(output))
        if actual != expected or any(token not in self.mapping for token in actual):
            raise ProtectionError('Translation changed protected sentinel values or counts.')
        remainder = self.tokens.sub('', output)
        if '@@' in remainder or any(char.isdigit() for char in remainder):
            raise ProtectionError('Translation introduced numbers or malformed sentinels.')
        return self.tokens.sub(lambda match: self.mapping[match.group()], output)

    def restore_finding(self, text):
        """Judge prose may mention a subset of sentinels, never unknown ones."""
        if any(token not in self.mapping for token in self.tokens.findall(text)):
            raise ProtectionError('Judge returned unknown sentinels.')
        restored = self.tokens.sub(lambda match: self.mapping[match.group()], text)
        if '@@CLEAR_' in restored:
            raise ProtectionError('Judge returned malformed sentinels.')
        return restored
