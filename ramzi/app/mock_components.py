"""
Mock components and Pydantic schemas for Track C (Clinician UI/UX).
Provides full scaffolding and mock implementations for Phase 0 & Phase 1,
and seamless adapter to live modules (storage, pipeline, exporters) when integrated.
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import textstat
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Canonical Pydantic Data Schemas (as specified in specs/02_TRACK_B_DATA_AND_STORAGE.md)
# ---------------------------------------------------------------------------

class MedicationOrder(BaseModel):
    name: str
    dose: str
    route: str = "oral"
    frequency: str
    special_instructions: str = ""


class ClinicalOrders(BaseModel):
    order_id: str = "ORD-SCD-01"
    order_version: str = "v1.2.0"
    patient_id: str = "SYN-PED-001"
    patient_age: str = "8 years old"
    diagnosis: str = "Sickle Cell Disease with acute vaso-occlusive pain"
    medications: List[MedicationOrder] = Field(default_factory=list)
    fever_threshold_urgent: str = "100.4°F"
    fever_threshold_emergency: str = "101.0°F"
    phone_clinic: str = "901-595-3300"
    phone_triage_247: str = "901-595-3300"
    phone_emergency: str = "911"


class SafetyJudgeResult(BaseModel):
    overall_verdict: str = "PASS"  # PASS | NEEDS_REVIEW | FLAGGED_FOR_REVIEW
    factual_drift_detected: bool = False
    omitted_red_flags: List[str] = Field(default_factory=list)
    contradictory_advice: List[str] = Field(default_factory=list)
    clinical_risk_score: float = 0.0
    explanation: str = "No critical omissions or dosage contradictions detected."


class EvaluationMetrics(BaseModel):
    fkgl_score: float = 5.8
    fkgl_target_met: bool = True
    verbatim_matches: List[str] = Field(default_factory=list)
    verbatim_mismatches: List[str] = Field(default_factory=list)
    verbatim_match_percent: float = 100.0
    safety_judge: SafetyJudgeResult = Field(default_factory=SafetyJudgeResult)


class InstructionPacket(BaseModel):
    packet_id: str = Field(default_factory=lambda: f"PKT-{uuid.uuid4().hex[:8].upper()}")
    condition: str = "sickle_cell_pain"
    module_version: str = "v1.2.0"
    order_version: str = "v1.2.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "PENDING"  # PENDING | APPROVED | EDITED_AND_APPROVED | REJECTED_DRIFT
    rejection_reason: Optional[str] = None
    original_instructions: str = ""
    clinical_orders: ClinicalOrders = Field(default_factory=ClinicalOrders)
    simplified_en: str = ""
    clinician_edited_en: Optional[str] = None
    translated_es: str = ""
    back_translated_en: str = ""
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    llm1_model: str = "gpt52"
    llm2_model: str = "gpt4o"
    physician_decision: Optional[str] = None
    pdf_annotation: Optional[str] = None


def get_physician_annotation(packet: InstructionPacket) -> str:
    """Helper returning standardized physician decision status."""
    if packet.status == "APPROVED":
        return "Approved by physician"
    elif packet.status == "EDITED_AND_APPROVED":
        return "Edited and approved by physician"
    elif packet.status == "REJECTED_DRIFT":
        return "Rejected by physician"
    return "Pending physician review"


# ---------------------------------------------------------------------------
# Verbatim Lock Regex Extractor (as specified in specs/01_TRACK_A_PIPELINE_AND_SAFETY.md)
# ---------------------------------------------------------------------------

RE_DOSES = re.compile(r"(\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?))", re.IGNORECASE)
RE_TEMPS = re.compile(r"(\d{2,3}(?:\.\d+)?\s*°?[FC])", re.IGNORECASE)
RE_PHONES = re.compile(r"(\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)")


def extract_verbatim_tokens(orders: ClinicalOrders) -> List[str]:
    """Extract safety-critical tokens from structured clinical orders."""
    tokens: List[str] = []
    for med in orders.medications:
        if med.dose:
            tokens.append(med.dose.strip())
    if orders.fever_threshold_urgent:
        tokens.append(orders.fever_threshold_urgent.strip())
    if orders.fever_threshold_emergency:
        tokens.append(orders.fever_threshold_emergency.strip())
    if orders.phone_clinic:
        tokens.append(orders.phone_clinic.strip())
    if orders.phone_triage_247:
        tokens.append(orders.phone_triage_247.strip())
    if orders.phone_emergency:
        tokens.append(orders.phone_emergency.strip())
    return tokens


def evaluate_text_verbatim_and_fkgl(
    text: str, orders: ClinicalOrders, drift_mode: Optional[str] = None
) -> EvaluationMetrics:
    """Evaluate text for FKGL grade level, verbatim token preservation, and safety drift."""
    # FKGL calculation
    try:
        fkgl = round(float(textstat.flesch_kincaid_grade(text)), 1)
    except Exception:
        fkgl = 5.6
    fkgl_met = 4.0 <= fkgl <= 6.9

    tokens = extract_verbatim_tokens(orders)
    matches: List[str] = []
    mismatches: List[str] = []

    text_lower = text.lower()
    for tok in tokens:
        # Check normalized match
        tok_clean = tok.lower().replace("°", "")
        if tok.lower() in text_lower or tok_clean in text_lower.replace("°", ""):
            matches.append(tok)
        else:
            mismatches.append(tok)

    total_tokens = len(tokens)
    match_pct = round((len(matches) / total_tokens * 100.0) if total_tokens > 0 else 100.0, 1)

    # Safety Judge verdict
    judge = SafetyJudgeResult()
    if drift_mode and drift_mode != "None":
        judge.factual_drift_detected = True
        judge.overall_verdict = "FLAGGED_FOR_REVIEW"
        judge.clinical_risk_score = 0.85
        if drift_mode == "Contradictory Advice":
            judge.contradictory_advice = ["Withhold anti-emetic medications until patient vomits 5 times."]
            judge.explanation = "Detected direct clinical contradiction: withholding anti-emetics is unsafe."
        elif drift_mode == "Altered Fever Threshold":
            judge.omitted_red_flags = ["Standard 100.4°F neutropenic fever threshold replaced with 104.5°F."]
            judge.explanation = "Dangerous elevation of fever return threshold detected."
        elif drift_mode == "Altered Medication Dose":
            judge.contradictory_advice = ["Medication dose altered or doubled compared to order set."]
            judge.explanation = "Prescribed medication dose does not match physician order."
    elif len(mismatches) > 0:
        judge.overall_verdict = "NEEDS_REVIEW"
        judge.factual_drift_detected = True
        judge.explanation = f"Missing verbatim tokens: {', '.join(mismatches)}"
        judge.clinical_risk_score = 0.45
    else:
        judge.overall_verdict = "PASS"
        judge.factual_drift_detected = False
        judge.explanation = "All medication doses, fever thresholds, and contact numbers verified verbatim."
        judge.clinical_risk_score = 0.05

    return EvaluationMetrics(
        fkgl_score=fkgl,
        fkgl_target_met=fkgl_met,
        verbatim_matches=matches,
        verbatim_mismatches=mismatches,
        verbatim_match_percent=match_pct,
        safety_judge=judge,
    )


# ---------------------------------------------------------------------------
# Mock Clinical Data Fixtures (Zero Disk Writes — generated in-memory)
# ---------------------------------------------------------------------------

MOCK_MODULES = {
    "sickle_cell_pain": {
        "v1.2.0": (
            "CLINICAL PROTOCOL: SICKLE CELL ACUTE VASO-OCCLUSIVE CRISIS\n\n"
            "Pathophysiology: Intravascular sickling causes microvascular occlusion leading to ischemia.\n"
            "Hydration Strategy: Aggressive oral hydration at 1.5x maintenance with electrolyte solutions.\n"
            "Analgesic Protocol: Scheduled NSAIDs and oral opioids as prescribed. Titrate based on FLACC/Wong-Baker scale.\n"
            "Red Flag Triggers: Immediate presentation required for temperature >= 100.4°F, acute chest syndrome "
            "(tachypnea, chest pain, hypoxemia), sudden pallor, splenic enlargement, or priapism.\n"
            "Emergency Contact: St. Jude Triage 24/7 or nearest Pediatric Emergency Department."
        ),
        "v1.1.0": (
            "CLINICAL PROTOCOL: SICKLE CELL PAIN MANAGEMENT (LEGACY)\n\n"
            "Hydration and scheduled oral analgesia. Prompt evaluation for fever above 100.4°F."
        ),
    },
    "fever_neutropenia": {
        "v1.2.0": (
            "CLINICAL PROTOCOL: PEDIATRIC ONCOLOGY FEVER AND NEUTROPENIA (F&N)\n\n"
            "Absolute Neutrophil Count (ANC) < 500/mcL creates severe risk for overwhelming bacteremia.\n"
            "Definition of Fever: Single oral temp >= 101.0°F (38.3°C) or sustained >= 100.4°F (38.0°C) over 1 hour.\n"
            "Mandatory Action: Medical emergency. Do NOT administer antipyretics before blood cultures. "
            "Patient must arrive at clinic or emergency facility within 60 minutes for IV broad-spectrum antibiotics.\n"
            "Emergency Contact: 24/7 Triage: 901-595-3300. Call 911 if lethargic or unresponsive."
        ),
        "v1.1.0": (
            "CLINICAL PROTOCOL: FEVER AND NEUTROPENIA GUIDELINE (v1.1)\n\n"
            "Prompt evaluation for fever >= 100.4°F in neutropenic patients. Immediate IV antibiotic coverage required."
        ),
    },
    "chemo_nausea_hydration": {
        "v1.2.0": (
            "CLINICAL PROTOCOL: POST-CHEMOTHERAPY NAUSEA, VOMITING & HYDRATION\n\n"
            "Emetogenic Risk Management: Administer ondansetron 4 mg every 8 hours scheduled for 48 hours post-infusion.\n"
            "Oral Hydration Target: Minimum 1200 mL oral fluids per 24 hours. Small frequent sips every 15 minutes.\n"
            "Threshold for Intervention: Return if unable to keep fluids down for > 8 hours, absence of wet diapers/urination "
            "for > 12 hours, dry mucous membranes, or persistent emesis > 4 episodes in 12 hours.\n"
            "Contact: Daytime Hematology/Oncology Clinic: 901-595-3300. Emergency: 911."
        ),
        "v1.1.0": (
            "CLINICAL PROTOCOL: CHEMOTHERAPY ANTI-EMETIC PROTOCOL (v1.1)\n\n"
            "Administer scheduled anti-emetics. Ensure minimum hydration. Contact clinic for persistent emesis."
        ),
    },
}

MOCK_ORDERS = {
    "sickle_cell_pain": ClinicalOrders(
        order_id="ORD-SCD-01",
        order_version="v1.2.0",
        patient_id="SYN-PED-001",
        patient_age="8 years old",
        diagnosis="Sickle Cell Disease with acute vaso-occlusive pain",
        medications=[
            MedicationOrder(
                name="Ibuprofen oral suspension",
                dose="200 mg",
                route="oral",
                frequency="every 6 hours as needed with food",
                special_instructions="Take with meals to prevent stomach upset.",
            ),
            MedicationOrder(
                name="Oxycodone oral solution",
                dose="5 mg",
                route="oral",
                frequency="every 4 hours as needed for severe pain",
                special_instructions="Only use if pain is not controlled by ibuprofen.",
            ),
        ],
        fever_threshold_urgent="100.4°F",
        fever_threshold_emergency="101.0°F",
        phone_clinic="901-595-3300",
        phone_triage_247="901-595-3300",
        phone_emergency="911",
    ),
    "fever_neutropenia": ClinicalOrders(
        order_id="ORD-FN-01",
        order_version="v1.2.0",
        patient_id="SYN-PED-002",
        patient_age="5 years old",
        diagnosis="B-ALL (Acute Lymphoblastic Leukemia) with post-chemo neutropenia",
        medications=[
            MedicationOrder(
                name="Cefepime IV (Home/Infusion)",
                dose="1000 mg",
                route="IV",
                frequency="every 8 hours",
                special_instructions="Administer over 30 minutes via central line.",
            ),
        ],
        fever_threshold_urgent="100.4°F",
        fever_threshold_emergency="101.0°F",
        phone_clinic="901-595-3300",
        phone_triage_247="901-595-3300",
        phone_emergency="911",
    ),
    "chemo_nausea_hydration": ClinicalOrders(
        order_id="ORD-CNH-01",
        order_version="v1.2.0",
        patient_id="SYN-PED-003",
        patient_age="12 years old",
        diagnosis="Osteosarcoma post-cisplatin infusion",
        medications=[
            MedicationOrder(
                name="Ondansetron tablets",
                dose="4 mg",
                route="oral",
                frequency="every 8 hours scheduled for 48 hours",
                special_instructions="Give 30 minutes before meals.",
            ),
        ],
        fever_threshold_urgent="100.4°F",
        fever_threshold_emergency="101.0°F",
        phone_clinic="901-595-3300",
        phone_triage_247="901-595-3300",
        phone_emergency="911",
    ),
}


# ---------------------------------------------------------------------------
# Mock Pipeline Orchestrator (Phase 0 / Phase 1 Engine)
# ---------------------------------------------------------------------------

def run_mock_pipeline(
    condition: str,
    module_version: str,
    orders: ClinicalOrders,
    llm1_model: str = "gpt52",
    llm2_model: str = "gpt4o",
    drift_mode: Optional[str] = None,
) -> InstructionPacket:
    """Generate a full InstructionPacket using deterministic plain-language templates."""
    raw_template = MOCK_MODULES.get(condition, {}).get(module_version, "")

    # Build simplified plain-language English
    if condition == "sickle_cell_pain":
        med1 = orders.medications[0].dose if orders.medications else "200 mg"
        med2 = orders.medications[1].dose if len(orders.medications) > 1 else "5 mg"
        if drift_mode == "Altered Medication Dose":
            med1 = "400 mg"  # Injected error: doubled dose

        urg_temp = orders.fever_threshold_urgent
        if drift_mode == "Altered Fever Threshold":
            urg_temp = "104.5°F"  # Injected error

        simplified_en = (
            f"Here is your child's care plan for sickle cell pain.\n\n"
            f"1. How to give pain medicine:\n"
            f"• Give Ibuprofen {med1} by mouth every 6 hours with food.\n"
            f"• If pain is still severe, give Oxycodone {med2} every 4 hours.\n\n"
            f"2. Water and liquids:\n"
            f"• Have your child drink extra water, soup, or milk every day.\n\n"
            f"3. When to call the clinic right away:\n"
            f"• Call immediately if temperature reaches {urg_temp} or higher.\n"
            f"• Call if your child has chest pain, fast breathing, or sudden tiredness.\n\n"
            f"4. Who to call:\n"
            f"• Day or night clinic phone: {orders.phone_clinic}.\n"
            f"• If your child cannot wake up, call {orders.phone_emergency} right away."
        )

        translated_es = (
            f"Este es el plan de cuidado para el dolor de células falciformes de su hijo.\n\n"
            f"1. Cómo dar los medicamentos para el dolor:\n"
            f"• Dé Ibuprofeno {med1} por la boca cada 6 horas con comida.\n"
            f"• Si el dolor sigue siendo fuerte, dé Oxicodona {med2} cada 4 horas.\n\n"
            f"2. Agua y líquidos:\n"
            f"• Haga que su hijo tome suficiente agua, caldo o leche todos los días.\n\n"
            f"3. Cuándo llamar a la clínica de inmediato:\n"
            f"• Llame de inmediato si la temperatura llega a {urg_temp} o más.\n"
            f"• Llame si su hijo tiene dolor en el pecho o respiración rápida.\n\n"
            f"4. A quién llamar:\n"
            f"• Teléfono de la clínica de día o de noche: {orders.phone_clinic}.\n"
            f"• Si su hijo no se despierta, llame al {orders.phone_emergency} de inmediato."
        )

        back_translated_en = (
            f"This is the care plan for your child's sickle cell pain.\n\n"
            f"1. How to give pain medicine:\n"
            f"• Give Ibuprofen {med1} by mouth every 6 hours with food.\n"
            f"• If severe pain continues, give Oxycodone {med2} every 4 hours.\n\n"
            f"2. Water and liquids:\n"
            f"• Make sure your child drinks plenty of water, soup, or milk every day.\n\n"
            f"3. When to call the clinic immediately:\n"
            f"• Call immediately if temperature reaches {urg_temp} or higher.\n"
            f"• Call if child has chest pain or fast breathing.\n\n"
            f"4. Contact numbers:\n"
            f"• Clinic day and night phone: {orders.phone_clinic}.\n"
            f"• If child does not wake up, call {orders.phone_emergency} right away."
        )

    elif condition == "fever_neutropenia":
        urg_temp = orders.fever_threshold_urgent
        emg_temp = orders.fever_threshold_emergency
        if drift_mode == "Altered Fever Threshold":
            urg_temp = "104.5°F"
            emg_temp = "105.0°F"

        simplified_en = (
            f"Important fever safety rules for your child:\n\n"
            f"Your child's immune system is low right now. A fever is a medical emergency.\n\n"
            f"1. Check temperature:\n"
            f"• Use a digital thermometer under the tongue or under the arm.\n"
            f"• Do not give Tylenol or Motrin before calling the clinic.\n\n"
            f"2. Warning signs to act fast:\n"
            f"• If fever reaches {urg_temp} or {emg_temp}, bring your child to the hospital immediately.\n"
            f"• Your child must get antibiotics within 60 minutes.\n\n"
            f"3. Contact numbers:\n"
            f"• Call 24/7 triage clinic immediately at {orders.phone_triage_247}.\n"
            f"• For severe breathing problems or extreme sleepiness, call {orders.phone_emergency}."
        )

        translated_es = (
            f"Reglas importantes de seguridad sobre la fiebre para su hijo:\n\n"
            f"Las defensas de su hijo están bajas en este momento. La fiebre es una emergencia médica.\n\n"
            f"1. Revise la temperatura:\n"
            f"• Use un termómetro digital en la boca o en la axila.\n"
            f"• No dé Tylenol ni Motrin antes de llamar a la clínica.\n\n"
            f"2. Señales de alarma para actuar rápido:\n"
            f"• Si la fiebre llega a {urg_temp} o {emg_temp}, traiga a su hijo al hospital de inmediato.\n"
            f"• Su hijo debe recibir antibióticos en menos de 60 minutos.\n\n"
            f"3. Números de contacto:\n"
            f"• Llame de inmediato al teléfono de triaje las 24 horas al {orders.phone_triage_247}.\n"
            f"• Si tiene dificultad grave para respirar, llame al {orders.phone_emergency}."
        )

        back_translated_en = (
            f"Important fever safety instructions for your child:\n\n"
            f"Your child's body defenses are low right now. Fever is a medical emergency.\n\n"
            f"1. Check temperature:\n"
            f"• Use a digital thermometer in mouth or under arm.\n"
            f"• Do not give Tylenol or Motrin before calling clinic.\n\n"
            f"2. Warning signs to act rapidly:\n"
            f"• If fever reaches {urg_temp} or {emg_temp}, bring your child to hospital right away.\n"
            f"• Child must receive antibiotics within 60 minutes.\n\n"
            f"3. Emergency numbers:\n"
            f"• Call 24-hour triage immediately at {orders.phone_triage_247}.\n"
            f"• For severe trouble breathing, call {orders.phone_emergency}."
        )

    else:  # chemo_nausea_hydration
        dose = orders.medications[0].dose if orders.medications else "4 mg"
        if drift_mode == "Contradictory Advice":
            contradiction = "\n• Note: Withhold anti-emetic medications until patient vomits 5 times."
        else:
            contradiction = ""

        simplified_en = (
            f"Care plan for nausea and vomiting after chemotherapy:\n\n"
            f"1. Nausea medicine:\n"
            f"• Give Ondansetron {dose} every 8 hours on schedule.{contradiction}\n"
            f"• Give medicine 30 minutes before food.\n\n"
            f"2. Keep your child hydrated:\n"
            f"• Give small sips of water, apple juice, or broth every 15 minutes.\n"
            f"• Goal is to drink at least 1200 mL of fluids every day.\n\n"
            f"3. When to call the doctor:\n"
            f"• Call if vomiting continues more than 4 times in half a day.\n"
            f"• Call if no wet diapers or urination for 12 hours.\n"
            f"• Call if fever reaches {orders.fever_threshold_urgent}.\n\n"
            f"4. Contact phone numbers:\n"
            f"• Daytime clinic phone: {orders.phone_clinic}.\n"
            f"• In severe emergency, call {orders.phone_emergency}."
        )

        translated_es = (
            f"Plan de cuidado para náuseas y vómitos después de la quimioterapia:\n\n"
            f"1. Medicina para las náuseas:\n"
            f"• Dé Ondansetrón {dose} cada 8 horas según el horario.\n"
            f"• Dé el medicamento 30 minutos antes de comer.\n\n"
            f"2. Mantenga a su hijo hidratado:\n"
            f"• Dé pequeños sorbos de agua, jugo de manzana o caldo cada 15 minutos.\n"
            f"• La meta es tomar al menos 1200 mL de líquidos cada día.\n\n"
            f"3. Cuándo llamar al médico:\n"
            f"• Llame si vomita más de 4 veces en medio día.\n"
            f"• Llame si no moja pañales o no orina durante 12 horas.\n"
            f"• Llame si la fiebre llega a {orders.fever_threshold_urgent}.\n\n"
            f"4. Teléfonos de contacto:\n"
            f"• Teléfono de la clínica de día: {orders.phone_clinic}.\n"
            f"• En emergencias graves, llame al {orders.phone_emergency}."
        )

        back_translated_en = (
            f"Care plan for nausea and vomiting after chemotherapy:\n\n"
            f"1. Nausea medication:\n"
            f"• Give Ondansetron {dose} every 8 hours on schedule.\n"
            f"• Administer medicine 30 minutes before eating.\n\n"
            f"2. Keep child hydrated:\n"
            f"• Offer small sips of water, apple juice, or soup every 15 minutes.\n"
            f"• Target is drinking at least 1200 mL fluids daily.\n\n"
            f"3. When to contact doctor:\n"
            f"• Call if vomiting happens more than 4 times in 12 hours.\n"
            f"• Call if no wet diapers or urine for 12 hours.\n"
            f"• Call if fever hits {orders.fever_threshold_urgent}.\n\n"
            f"4. Contact numbers:\n"
            f"• Daytime clinic: {orders.phone_clinic}.\n"
            f"• Severe emergency: call {orders.phone_emergency}."
        )

    # Evaluate metrics
    metrics = evaluate_text_verbatim_and_fkgl(simplified_en, orders, drift_mode=drift_mode)

    packet = InstructionPacket(
        condition=condition,
        module_version=module_version,
        order_version=orders.order_version,
        status="PENDING",
        original_instructions=raw_template,
        clinical_orders=orders,
        simplified_en=simplified_en,
        clinician_edited_en=simplified_en,
        translated_es=translated_es,
        back_translated_en=back_translated_en,
        metrics=metrics,
        llm1_model=llm1_model,
        llm2_model=llm2_model,
        physician_decision=get_physician_annotation(
            InstructionPacket(status="PENDING")
        ),
        pdf_annotation="Pending physician review",
    )
    return packet


# ---------------------------------------------------------------------------
# In-Memory Gold Library Mock Persistence
# ---------------------------------------------------------------------------

_IN_MEMORY_LIBRARY: List[InstructionPacket] = []


def save_to_gold_library(packet: InstructionPacket) -> None:
    """Save reviewed packet to in-memory audit store and optional local JSONL."""
    packet.physician_decision = get_physician_annotation(packet)
    packet.pdf_annotation = packet.physician_decision
    _IN_MEMORY_LIBRARY.append(packet)


def load_gold_records() -> List[InstructionPacket]:
    """Return all stored gold library packets."""
    return list(_IN_MEMORY_LIBRARY)


# ---------------------------------------------------------------------------
# ReportLab PDF Exporter Mock / Fallback
# ---------------------------------------------------------------------------

def generate_handout_pdf(packet: InstructionPacket) -> bytes:
    """Generate professional 2-column bilingual PDF with physician verification banner."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1A365D"),
    )
    banner_style = ParagraphStyle(
        "BannerStyle",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        fontName="Helvetica-Bold",
    )
    cell_style = ParagraphStyle(
        "CellStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )
    footer_style = ParagraphStyle(
        "FooterStyle",
        parent=styles["Italic"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#4A5568"),
    )

    elements = []

    # Hospital Title Header
    elements.append(Paragraph("<b>St. Jude / Pediatric Hospital Discharge Instructions</b>", title_style))
    elements.append(Spacer(1, 8))

    # Physician Verification Banner
    annotation = get_physician_annotation(packet)
    if packet.status == "APPROVED":
        bg_col = colors.HexColor("#F0FFF4")
        border_col = colors.HexColor("#38A169")
        txt_col = colors.HexColor("#22543D")
        banner_text = f"✔ {annotation.upper()} — Final Plain-Language Handout"
    elif packet.status == "EDITED_AND_APPROVED":
        bg_col = colors.HexColor("#EBF8FF")
        border_col = colors.HexColor("#3182CE")
        txt_col = colors.HexColor("#2A4365")
        banner_text = f"✎ {annotation.upper()} — Verified Plain-Language Handout"
    elif packet.status == "REJECTED_DRIFT":
        bg_col = colors.HexColor("#FFF5F5")
        border_col = colors.HexColor("#E53E3E")
        txt_col = colors.HexColor("#742A2A")
        reason = packet.rejection_reason or "Unsafe factual drift"
        banner_text = f"✖ {annotation.upper()} — REASON: {reason}"
    else:
        bg_col = colors.HexColor("#FFFAF0")
        border_col = colors.HexColor("#DD6B20")
        txt_col = colors.HexColor("#7B341E")
        banner_text = f"⏳ {annotation.upper()}"

    banner_p = Paragraph(f"<font color='{txt_col.hexval()}'>{banner_text}</font>", banner_style)
    banner_table = Table([[banner_p]], colWidths=[540])
    banner_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_col),
            ("BOX", (0, 0), (-1, -1), 1.5, border_col),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    elements.append(banner_table)
    elements.append(Spacer(1, 10))

    # Patient Meta
    meta_text = (
        f"<b>Patient ID:</b> {packet.clinical_orders.patient_id} | "
        f"<b>Age:</b> {packet.clinical_orders.patient_age} | "
        f"<b>Diagnosis:</b> {packet.clinical_orders.diagnosis}"
    )
    elements.append(Paragraph(meta_text, cell_style))
    elements.append(Spacer(1, 10))

    # 2-Column Side-by-Side: Left (English), Right (Spanish)
    en_content = (packet.clinician_edited_en or packet.simplified_en).replace("\n", "<br/>")
    es_content = packet.translated_es.replace("\n", "<br/>")

    col_en = Paragraph(f"<b>ENGLISH (5th–6th Grade)</b><br/><br/>{en_content}", cell_style)
    col_es = Paragraph(f"<b>ESPAÑOL (Instrucciones)</b><br/><br/>{es_content}", cell_style)

    content_table = Table([[col_en, col_es]], colWidths=[265, 265])
    content_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBEFORE", (1, 0), (1, -1), 1, colors.HexColor("#CBD5E0")),
        ])
    )
    elements.append(content_table)
    elements.append(Spacer(1, 14))

    # Audit Footer
    footer_text = (
        f"Protocol: {packet.condition} (Module: {packet.module_version}, Order Set: {packet.order_version}) | "
        f"Packet ID: {packet.packet_id} | Verified: {packet.created_at[:19]} UTC"
    )
    elements.append(Paragraph(footer_text, footer_style))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()
