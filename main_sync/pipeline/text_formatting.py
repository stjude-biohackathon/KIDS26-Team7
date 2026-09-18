"""Convert model Markdown into clean plain text for clinician editing."""

from html import unescape
import re


def to_editor_plain_text(text: str) -> str:
    """Remove presentation markup while preserving readable structure and words."""
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"^[ \t]*```[^\n]*\n?", "", value, flags=re.MULTILINE)
    value = re.sub(r"^[ \t]*```[ \t]*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^[ \t]*>[ \t]?", "", value, flags=re.MULTILINE)
    value = re.sub(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+", "• ", value, flags=re.MULTILINE)
    value = re.sub(r"^[ \t]*(?:-{3,}|_{3,}|\*{3,})[ \t]*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: m.group(1) or m.group(2), value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", value)
    value = re.sub(r"`([^`\n]+)`", r"\1", value)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</?[A-Za-z][^>\n]*>", "", value)
    value = unescape(value)
    lines = [line.rstrip() for line in value.splitlines()]
    value = "\n".join(lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
