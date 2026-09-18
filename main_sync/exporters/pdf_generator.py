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


def _format_for_reportlab(text: str, protected_values=()) -> str:
    """Escape supplied text, retaining line breaks and bolding protected values."""
    if not text:
        return ""
    values = sorted(set(protected_values), key=len, reverse=True)
    if not values:
        return escape(text).replace("\n", "<br/>")
    pattern = re.compile(r"(?<![\w.,/+\-])(?:" + "|".join(re.escape(v) for v in values) + r")(?!\w|\s*/|\.\d)")
    parts, offset = [], 0
    for match in pattern.finditer(text):
        parts.extend([escape(text[offset:match.start()]), "<b>" + escape(match.group()) + "</b>"])
        offset = match.end()
    parts.append(escape(text[offset:]))
    return "".join(parts).replace("\n", "<br/>")


def _ordered_language_sections(packet: InstructionPacket) -> list[tuple[str, str]]:
    """Return patient-facing sections in their required print order."""
    if packet.translated_es.strip():
        return [
            ("ESPAÑOL (Instrucciones para la Familia)", packet.translated_es),
            ("ENGLISH", packet.simplified_en),
        ]
    return [("ENGLISH", packet.simplified_en)]


# Section titles arrive as "=== HOME CARE ===" scaffolding. They are rendered
# as coloured ribbons instead: presentation only, wording is never changed.
_SECTION_HEADING_RE = re.compile(r"^\s*={2,}\s*(.+?)\s*={2,}\s*$")

_RIBBON_FILL = colors.Color(0, 0.72, 0.82, alpha=0.18)
_RIBBON_ACCENT = colors.Color(0, 0.52, 0.62, alpha=0.75)
_RIBBON_TEXT = colors.HexColor("#08424C")


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

    for line in text.splitlines():
        match = _SECTION_HEADING_RE.match(line)
        if match:
            flush()
            blocks.append(("heading", match.group(1)))
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
