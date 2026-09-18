"""
Track B: English and bilingual PDF generator.
ReportLab generator creating full-width language sections with physician
verification status banner and audit footer.
Adheres strictly to specs/02_TRACK_B_DATA_AND_STORAGE.md.
"""

from __future__ import annotations

import io
import re
from html import escape
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pipeline.evaluator import extract_verbatim_tokens

from schemas.instruction_packet import (
    InstructionPacket,
    get_physician_annotation,
)


def _apply_inline_markdown(html_text: str) -> str:
    """Render markdown emphasis markers as styled text instead of literal characters."""
    html_text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", html_text)
    html_text = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"<i>\1</i>", html_text)
    return html_text


def _format_for_reportlab(text: str, protected_values=()) -> str:
    """Escape supplied text, retaining line breaks and bolding protected values."""
    if not text:
        return ""
    values = sorted(set(protected_values), key=len, reverse=True)
    if not values:
        return _apply_inline_markdown(escape(text)).replace("\n", "<br/>")
    pattern = re.compile(r"(?<![\w.,/+\-])(?:" + "|".join(re.escape(v) for v in values) + r")(?!\w|\s*/|\.\d)")
    parts, offset = [], 0
    for match in pattern.finditer(text):
        parts.extend([_apply_inline_markdown(escape(text[offset:match.start()])), "<b>" + escape(match.group()) + "</b>"])
        offset = match.end()
    parts.append(_apply_inline_markdown(escape(text[offset:])))
    return "".join(parts).replace("\n", "<br/>")


def _ordered_language_sections(packet: InstructionPacket) -> list[tuple[str, str]]:
    """Return patient-facing sections in their required print order."""
    if packet.translated_es.strip():
        return [
            ("ESPAÑOL (Instrucciones para la Familia)", packet.translated_es),
            ("ENGLISH", packet.simplified_en),
        ]
    return [("ENGLISH", packet.simplified_en)]


# Section titles arrive in several shapes depending on how the text was
# produced: "=== HOME CARE ===" loader scaffolding, markdown headings or bold
# lines from the simplifier, or a bare short title such as "Signs to Watch For".
# All of them are rendered as coloured ribbons: presentation only, the wording
# itself is never changed.
_SECTION_HEADING_RE = re.compile(r"^\s*={2,}\s*(.+?)\s*={2,}\s*$")
_ATX_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_BOLD_LINE_RE = re.compile(r"^\s*(?:\*\*|__)(.+?)(?:\*\*|__)\s*:?\s*$")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*\u2022\u2013]\s+|\d+[.)]\s+)")
_TRAILING_PUNCT_RE = re.compile(r"[.!?,;]$")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")

_RIBBON_FILL = colors.Color(0, 0.72, 0.82, alpha=0.18)
_RIBBON_ACCENT = colors.Color(0, 0.52, 0.62, alpha=0.75)
_RIBBON_TEXT = colors.HexColor("#08424C")

_MAX_HEADING_CHARS = 90
_MAX_HEADING_WORDS = 12

# Words that stay lower case inside an English or Spanish title.
_TITLE_MINOR_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "if", "in", "of", "on",
    "or", "the", "to", "with", "your",
    "a\u00f1o", "al", "con", "de", "del", "en", "la", "las", "los", "para",
    "por", "si", "su", "un", "una", "y",
}


def _plain_heading(text: str) -> str:
    """Strip decorative markdown emphasis and trailing colons from a title."""
    cleaned = text.strip().strip("*_").strip()
    return cleaned.rstrip(":").strip()


def _is_upper_case_title(text: str) -> bool:
    """True when the title is written in capitals, ignoring parentheticals."""
    core = _PARENTHETICAL_RE.sub(" ", text)
    return any(char.isalpha() for char in core) and core.upper() == core


def _is_title_case(text: str) -> bool:
    """True when every significant word is capitalised, as titles usually are."""
    words = [w for w in _PARENTHETICAL_RE.sub(" ", text).split() if any(c.isalpha() for c in w)]
    if len(words) < 2:
        return False
    significant = 0
    for index, word in enumerate(words):
        lead = next((c for c in word if c.isalpha()), "")
        if index and word.lower().strip(":") in _TITLE_MINOR_WORDS:
            continue
        significant += 1
        if not lead.isupper():
            return False
    return significant >= 2


def _detect_heading(line: str, *, starts_block: bool, ends_block: bool) -> Optional[str]:
    """Return the title text when a line is a section heading, else None.

    Explicitly marked headings (``=== X ===``, ``## X``, ``**X**``) always win.
    Unmarked lines qualify only when they read like a standalone title, so the
    same wording is ribboned no matter which module or model produced it.
    """
    stripped = line.strip()
    if not stripped or _BULLET_PREFIX_RE.match(line):
        return None

    for pattern in (_SECTION_HEADING_RE, _ATX_HEADING_RE, _BOLD_LINE_RE):
        match = pattern.match(stripped)
        if match:
            title = _plain_heading(match.group(1))
            return title or None

    if _TRAILING_PUNCT_RE.search(stripped):
        return None
    candidate = _plain_heading(stripped)
    if not candidate or not any(char.isalpha() for char in candidate):
        return None
    if len(candidate) > _MAX_HEADING_CHARS or len(candidate.split()) > _MAX_HEADING_WORDS:
        return None

    if stripped.endswith(":") or _is_upper_case_title(candidate):
        return candidate
    # A capitalised title on its own line, separated from the surrounding body.
    if _is_title_case(candidate) and (starts_block or ends_block):
        return candidate
    return None


def _split_into_blocks(text: str) -> list[tuple[str, str]]:
    """Split body text into ('heading'|'body', text) chunks in source order."""
    blocks: list[tuple[str, str]] = []
    body: list[str] = []

    def flush() -> None:
        while body and not body[-1].strip():
            body.pop()
        if body:
            blocks.append(("body", "\n".join(body)))
        body.clear()

    lines = text.splitlines()
    for index, line in enumerate(lines):
        previous_blank = index == 0 or not lines[index - 1].strip()
        next_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
        heading = _detect_heading(line, starts_block=previous_blank, ends_block=next_blank)
        if heading:
            flush()
            blocks.append(("heading", heading))
        else:
            if not line.strip() and not body:
                continue
            body.append(line)
    flush()
    return blocks


def _ribbon(html_text: str, style: ParagraphStyle, width: float, *, accent: bool) -> Table:
    """Render one heading as a light cyan ribbon spanning the text column."""
    table = Table([[Paragraph(html_text, style)]], colWidths=[width], splitInRow=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, -1), _RIBBON_FILL),
        ("LINEBEFORE", (0, 0), (-1, -1), 3, _RIBBON_ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]
    if accent:
        commands.append(("LINEBELOW", (0, 0), (-1, -1), 1, _RIBBON_ACCENT))
    table.setStyle(TableStyle(commands))
    return table


def create_bilingual_pdf(packet: InstructionPacket) -> bytes:
    """
    Renders a full-width English or sequential Spanish-first bilingual pediatric
    discharge handout with physician verification and an audit sign-off footer.
    """
    if packet.status in {'APPROVED', 'EDITED_AND_APPROVED'} and packet.evaluation_metrics and packet.evaluation_metrics.protection_failures:
        raise ValueError('Protected-value failures must be resolved before publishing.')
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#1A365D"),
    )
    banner_style = ParagraphStyle(
        "BannerText",
        parent=styles["Normal"],
        fontSize=10,
        leading=13,
        fontName="Helvetica-Bold",
    )
    meta_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#2D3748"),
    )
    cell_style = ParagraphStyle(
        "ColCellText",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1A202C"),
    )
    language_ribbon_style = ParagraphStyle(
        "LanguageRibbon",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        fontName="Helvetica-Bold",
        textColor=_RIBBON_TEXT,
    )
    section_ribbon_style = ParagraphStyle(
        "SectionRibbon",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=12.5,
        fontName="Helvetica-Bold",
        textColor=_RIBBON_TEXT,
    )
    footer_style = ParagraphStyle(
        "FooterText",
        parent=styles["Italic"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#4A5568"),
    )

    elements = []
    bilingual = bool(packet.translated_es.strip())
    handout_label = "Bilingual Handout" if bilingual else "English Handout"

    # Hospital Title Header
    elements.append(
        Paragraph("<b>St. Jude / Pediatric Hospital Discharge Instructions</b>", title_style)
    )
    elements.append(Spacer(1, 6))

    # Physician Verification Banner
    annotation = get_physician_annotation(packet)
    status = packet.status.upper() if packet.status else "PENDING"

    if status == "APPROVED":
        bg_col = colors.HexColor("#F0FFF4")
        border_col = colors.HexColor("#38A169")
        txt_col = colors.HexColor("#22543D")
        banner_msg = f" {annotation.upper()} — Reviewed {handout_label}"
    elif status == "EDITED_AND_APPROVED":
        bg_col = colors.HexColor("#EBF8FF")
        border_col = colors.HexColor("#3182CE")
        txt_col = colors.HexColor("#2A4365")
        banner_msg = f" {annotation.upper()} — Reviewed {handout_label}"
    elif status == "REJECTED_DRIFT":
        bg_col = colors.HexColor("#FFF5F5")
        border_col = colors.HexColor("#E53E3E")
        txt_col = colors.HexColor("#742A2A")
        reason = packet.rejection_reason or "Clinical drift detected"
        banner_msg = f" {annotation.upper()} — NOTICE: {reason}"
    else:
        bg_col = colors.HexColor("#FFFAF0")
        border_col = colors.HexColor("#DD6B20")
        txt_col = colors.HexColor("#7B341E")
        banner_msg = f"{annotation.upper()}"

    banner_p = Paragraph(f"<font color='{txt_col.hexval()}'>{_format_for_reportlab(banner_msg)}</font>", banner_style)
    banner_table = Table([[banner_p]], colWidths=[doc.width - 12], splitInRow=1)
    banner_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_col),
            ("BOX", (0, 0), (-1, -1), 1.2, border_col),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    elements.append(banner_table)
    elements.append(Spacer(1, 8))

    # Patient Metadata Summary
    patient_info = (
        f"<b>Patient MRN:</b> {escape(packet.clinical_orders.patient_id)} &nbsp;|&nbsp; "
        f"<b>Age:</b> {escape(packet.clinical_orders.age or 'N/A')} &nbsp;|&nbsp; "
        f"<b>Module:</b> {escape(packet.clinical_orders.diagnosis)}"
    )
    elements.append(Paragraph(patient_info, meta_style))
    elements.append(Spacer(1, 8))

    # Full-width language sections. Spanish is first when requested, followed
    # by the simplified English source on the next page.
    values = extract_verbatim_tokens(packet.clinical_orders)
    sections = _ordered_language_sections(packet)
    for index, (heading, text) in enumerate(sections):
        if index:
            elements.append(PageBreak())
        elements.append(_ribbon(escape(heading), language_ribbon_style, doc.width, accent=True))
        elements.append(Spacer(1, 8))
        for kind, chunk in _split_into_blocks(text):
            if kind == "heading":
                elements.append(Spacer(1, 4))
                elements.append(
                    _ribbon(escape(chunk), section_ribbon_style, doc.width, accent=False)
                )
                elements.append(Spacer(1, 5))
            else:
                elements.append(Paragraph(_format_for_reportlab(chunk, values), cell_style))
    elements.append(Spacer(1, 12))

    # Audit Sign-Off Footer
    timestamp = packet.reviewed_at or packet.created_at or datetime.now(timezone.utc).isoformat()
    clean_ts = timestamp[:19].replace("T", " ")
    footer_text = (
        f"Protocol: {escape(packet.condition)} | Module: {escape(packet.module_version)} | Order Set: {escape(packet.order_version)} | "
        f"Record ID: {escape(packet.packet_id)}<br/>"
        f"Physician Verification: {annotation} | Recorded: {clean_ts} UTC | Signature: __________________________"
    )
    elements.append(Paragraph(footer_text, footer_style))

    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        label = "REJECTED AUDIT COPY - NOT FOR PATIENT USE" if packet.status == "REJECTED_DRIFT" else (
            "SYNTHETIC SIMULATION - NOT FOR PATIENT USE" if packet.is_simulation else (
                "DRAFT - NOT FOR PATIENT USE" if packet.status == "PENDING" else annotation
            )
        )
        canvas.drawString(36, 20, label)
        canvas.drawRightString(letter[0] - 36, 20, f"Page {document.page}")
        canvas.restoreState()
    doc.build(elements, onFirstPage=page_footer, onLaterPages=page_footer)
    buf.seek(0)
    return buf.getvalue()


# Compatibility aliases
generate_pdf_handout = create_bilingual_pdf
generate_handout_pdf = create_bilingual_pdf
