"""
Mock components and fixtures for Track C (Clinician UI/UX).
Adheres strictly to canonical schemas defined in schemas/instruction_packet.py.
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import textstat

# Authoritative schemas
from schemas.instruction_packet import (
    ClinicalOrders,
    EvaluationMetrics,
    InstructionPacket,
    MedicationOrder,
    SafetyJudgeResult,
    get_physician_annotation,
)


# ---------------------------------------------------------------------------
# Verbatim Lock Regex Extractor (as specified in specs/01_TRACK_A_PIPELINE_AND_SAFETY.md)
# ---------------------------------------------------------------------------

RE_DOSES = re.compile(r"(\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?))", re.IGNORECASE)
RE_TEMPS = re.compile(r"(\d{2,3}(?:\.\d+)?\s*°?[FC])", re.IGNORECASE)
RE_PHONES = re.compile(r"(\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)")


from pipeline.evaluator import extract_verbatim_tokens, evaluate_text
from pipeline.drift import inject_drift


def evaluate_text_verbatim_and_fkgl(text, orders, drift_mode=None):
    """Compatibility wrapper: one canonical evaluator for demo and live paths."""
    return evaluate_text(text, orders)


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
        age="8 years old",
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
        urgent_fever_threshold="100.4°F",
        emergency_fever_threshold="101.0°F",
        daytime_phone="901-595-3300",
        after_hours_phone="901-595-3300",
        emergency_phone="911",
    ),
    "fever_neutropenia": ClinicalOrders(
        order_id="ORD-FN-01",
        order_version="v1.2.0",
        patient_id="SYN-PED-002",
        age="5 years old",
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
        urgent_fever_threshold="100.4°F",
        emergency_fever_threshold="101.0°F",
        daytime_phone="901-595-3300",
        after_hours_phone="901-595-3300",
        emergency_phone="911",
    ),
    "chemo_nausea_hydration": ClinicalOrders(
        order_id="ORD-CNH-01",
        order_version="v1.2.0",
        patient_id="SYN-PED-003",
        age="12 years old",
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
        urgent_fever_threshold="100.4°F",
        emergency_fever_threshold="101.0°F",
        daytime_phone="901-595-3300",
        after_hours_phone="901-595-3300",
        emergency_phone="911",
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
    requested_drift = drift_mode
    drift_mode = None
    raw_template = MOCK_MODULES.get(condition, {}).get(module_version, "")
    if not raw_template:
        raise ValueError("No bundled synthetic fixture matches the requested protocol version.")

    # Build simplified plain-language English
    if condition == "sickle_cell_pain":
        med1 = orders.medications[0].dose if orders.medications else "200 mg"
        med2 = orders.medications[1].dose if len(orders.medications) > 1 else "5 mg"
        if drift_mode == "Altered Medication Dose":
            med1 = "400 mg"  # Injected error: doubled dose

        urg_temp = orders.urgent_fever_threshold
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
            f"• Day or night clinic phone: {orders.daytime_phone}.\n"
            f"• If your child cannot wake up, call {orders.emergency_phone} right away."
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
            f"• Teléfono de la clínica de día o de noche: {orders.daytime_phone}.\n"
            f"• Si su hijo no se despierta, llame al {orders.emergency_phone} de inmediato."
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
            f"• Clinic day and night phone: {orders.daytime_phone}.\n"
            f"• If child does not wake up, call {orders.emergency_phone} right away."
        )

    elif condition == "fever_neutropenia":
        urg_temp = orders.urgent_fever_threshold
        emg_temp = orders.emergency_fever_threshold
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
            f"• Call 24/7 triage clinic immediately at {orders.after_hours_phone}.\n"
            f"• For severe breathing problems or extreme sleepiness, call {orders.emergency_phone}."
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
            f"• Llame de inmediato al teléfono de triaje las 24 horas al {orders.after_hours_phone}.\n"
            f"• Si tiene dificultad grave para respirar, llame al {orders.emergency_phone}."
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
            f"• Call 24-hour triage immediately at {orders.after_hours_phone}.\n"
            f"• For severe trouble breathing, call {orders.emergency_phone}."
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
            f"• Call if fever reaches {orders.urgent_fever_threshold}.\n\n"
            f"4. Contact phone numbers:\n"
            f"• Daytime clinic phone: {orders.daytime_phone}.\n"
            f"• In severe emergency, call {orders.emergency_phone}."
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
            f"• Llame si la fiebre llega a {orders.urgent_fever_threshold}.\n\n"
            f"4. Teléfonos de contacto:\n"
            f"• Teléfono de la clínica de día: {orders.daytime_phone}.\n"
            f"• En emergencias graves, llame al {orders.emergency_phone}."
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
            f"• Call if fever hits {orders.urgent_fever_threshold}.\n\n"
            f"4. Contact numbers:\n"
            f"• Daytime clinic: {orders.daytime_phone}.\n"
            f"• Severe emergency: call {orders.emergency_phone}."
        )

    # Evaluate metrics
    metrics = evaluate_text_verbatim_and_fkgl(simplified_en, orders, drift_mode=drift_mode)

    packet = InstructionPacket(
        packet_id=f"PKT-{uuid.uuid4().hex[:8].upper()}",
        condition=condition,
        module_version=module_version,
        order_version=orders.order_version,
        status="PENDING",
        original_clinical_text=raw_template,
        clinical_orders=orders,
        simplified_en=simplified_en,
        translated_es=translated_es,
        back_translated_en=back_translated_en,
        evaluation_metrics=metrics,
        physician_decision="Pending physician review",
    )
    return inject_drift(packet, requested_drift) if requested_drift and requested_drift != "None" else packet


# ---------------------------------------------------------------------------
# In-Memory Gold Library Mock Persistence
# ---------------------------------------------------------------------------

# Compatibility exports delegate to the canonical session store and exporter.
from storage.gold_library import save_to_gold_library, load_gold_records
from exporters.pdf_generator import create_bilingual_pdf as generate_handout_pdf
