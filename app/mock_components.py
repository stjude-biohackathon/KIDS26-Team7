"""Track C's existing demo wording, connected to shared Track A/B components.

The fixture paragraphs below are carried over from Ramzi's Phase 1 work.
They are mock content, not clinically approved translations. Quality checks,
packet construction, data loading, storage, and PDF rendering use shared modules.
"""

from typing import Optional

from schemas.instruction_packet import (
    ClinicalOrders, EvaluationMetrics, InstructionPacket, MedicationOrder,
    SafetyJudgeResult, get_physician_annotation,
)
from pipeline.evaluator import evaluate_text, extract_verbatim_tokens
from pipeline.orchestrator import PipelineOrchestrator
from storage.github_loader import load_mock_templates_and_orders
from storage.gold_library import load_gold_records, save_to_gold_library
from exporters.pdf_generator import create_bilingual_pdf as generate_handout_pdf

MOCK_MODULES, MOCK_ORDERS = load_mock_templates_and_orders()


def evaluate_text_verbatim_and_fkgl(text, orders, drift_mode=None):
    """Compatibility name for Track A's real local checks."""
    return evaluate_text(text, orders)


def run_mock_pipeline(
    condition: str,
    module_version: str,
    orders: ClinicalOrders,
    llm1_model: str = "gpt52",
    llm2_model: str = "gpt4o",
    drift_mode: Optional[str] = None,
) -> InstructionPacket:
    """Generate a full InstructionPacket using deterministic plain-language templates."""
    modules, _ = load_mock_templates_and_orders()
    if condition not in modules or module_version not in modules[condition]:
        raise ValueError("Select an available condition and module version.")
    raw_template = modules[condition][module_version]

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
            f"• Call emergency if temperature reaches {orders.emergency_fever_threshold} or higher.\n"
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
            f"• Llame de emergencia si la temperatura llega a {orders.emergency_fever_threshold} o más.\n"
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
            f"• Call emergency if temperature reaches {orders.emergency_fever_threshold} or higher.\n"
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

    # These strings are already filled demo fixtures. Escape literal dollars so
    # Track A does not interpret user-entered dollar signs as new placeholders.
    packet = PipelineOrchestrator(llm1_model=llm1_model, llm2_model=llm2_model).generate(
        raw_template, orders, module_version=module_version, condition=condition,
        simplified_template_text=simplified_en.replace("$", "$$"),
        spanish_template_text=translated_es.replace("$", "$$"),
        back_translation_template_text=back_translated_en.replace("$", "$$"),
    )
    if drift_mode and drift_mode != "None":
        judge = packet.evaluation_metrics.safety_judge
        judge.overall_verdict = "FLAGGED_FOR_REVIEW"
        judge.factual_drift_detected = True
        judge.explanation += " Synthetic drift test selected; no live safety judge was called."
    return packet
