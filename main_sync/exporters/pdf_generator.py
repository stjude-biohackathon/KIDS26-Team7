"""
Track B: Bilingual PDF Generator.
ReportLab generator creating clean 2-column bilingual layout with physician verification status banner and audit footer.
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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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


def create_bilingual_pdf(packet: InstructionPacket) -> bytes:
    """
    Renders a high-quality 2-column bilingual pediatric discharge handout
    with physician verification banner, verbatim markers, and audit sign-off footer.
    """
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
    footer_style = ParagraphStyle(
        "FooterText",
        parent=styles["Italic"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#4A5568"),
    )

    elements = []

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
        banner_msg = f" {annotation.upper()} — Reviewed Bilingual Handout"
    elif status == "EDITED_AND_APPROVED":
        bg_col = colors.HexColor("#EBF8FF")
        border_col = colors.HexColor("#3182CE")
        txt_col = colors.HexColor("#2A4365")
        banner_msg = f" {annotation.upper()} — Reviewed Bilingual Handout"
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
        banner_msg = f"⏳ {annotation.upper()}"

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
        f"<b>Patient ID:</b> {escape(packet.clinical_orders.patient_id)} &nbsp;|&nbsp; "
        f"<b>Age:</b> {escape(packet.clinical_orders.age or 'N/A')} &nbsp;|&nbsp; "
        f"<b>Diagnosis:</b> {escape(packet.clinical_orders.diagnosis)}"
    )
    elements.append(Paragraph(patient_info, meta_style))
    elements.append(Spacer(1, 8))

    # 2-Column Side-by-Side Grid
    values = extract_verbatim_tokens(packet.clinical_orders)
    en_formatted = _format_for_reportlab(packet.simplified_en, values)
    es_formatted = _format_for_reportlab(packet.translated_es, values)

    col_en = Paragraph(en_formatted, cell_style)
    col_es = Paragraph(es_formatted, cell_style)

    # The frame adds 6pt padding on each side of doc.width. Split within
    # long cells so a single paragraph can span pages without truncation.
    content_table = Table(
        [[Paragraph("<b>ENGLISH</b>", cell_style),
          Paragraph("<b>ESPAÑOL (Instrucciones para la Familia)</b>", cell_style)],
         [col_en, col_es]],
        colWidths=[(doc.width - 12) / 2] * 2,
        repeatRows=1, splitByRow=1, splitInRow=1,
    )
    content_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBEFORE", (1, 0), (1, -1), 1, colors.HexColor("#CBD5E0")),
        ])
    )
    elements.append(content_table)
    elements.append(Spacer(1, 12))

    # Audit Sign-Off Footer
    timestamp = packet.reviewed_at or packet.created_at or datetime.now(timezone.utc).isoformat()
    clean_ts = timestamp[:19].replace("T", " ")
    footer_text = (
        f"Protocol: {escape(packet.condition)} | Module: {escape(packet.module_version)} | Order Set: {escape(packet.order_version)} | "
        f"Packet ID: {escape(packet.packet_id)}<br/>"
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
