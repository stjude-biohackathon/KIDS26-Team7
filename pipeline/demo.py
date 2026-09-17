"""Run `python -m pipeline.demo` for an offline, in-memory Sync 1 example."""

from pipeline.orchestrator import PipelineOrchestrator
from schemas.instruction_packet import ClinicalOrders, MedicationOrder


def main() -> None:
    # Neutral labels demonstrate binding; these are not clinical instructions.
    orders = ClinicalOrders(
        patient_id="SYN-PED-001", diagnosis="Synthetic demonstration",
        medications=[MedicationOrder(name="DEMO_ONLY", dose="5 mg")],
        urgent_fever_threshold="100.4°F", emergency_fever_threshold="101.0°F",
        daytime_phone="202-555-0100", after_hours_phone="202-555-0101",
        emergency_phone="911", order_id="DEMO-001", order_version="v1.0.0",
    )
    values = (
        "$medication_0_dose; $urgent_fever_threshold; $emergency_fever_threshold; "
        "$daytime_phone; $after_hours_phone; $emergency_phone."
    )
    packet = PipelineOrchestrator().generate(
        "Synthetic reference values: " + values,
        orders, module_version="v1.0.0", condition="sickle_cell_pain",
        simplified_template_text="This is a test. Example values: " + values,
        spanish_template_text="Ejemplo sintético. Valores: " + values,
        back_translation_template_text="Synthetic example. Values: " + values,
    )
    print("Sync 1 mock demonstration — supplied templates, no LLM calls or file writes.")
    for label, text in (
        ("Original source (preserved)", packet.original_clinical_text),
        ("English (bound template)", packet.simplified_en),
        ("Spanish (supplied mock)", packet.translated_es),
        ("Back-translation (supplied mock)", packet.back_translated_en),
    ):
        print(f"\n{label}:\n{text}")
    metrics = packet.evaluation_metrics
    print(f"\nStatus: {packet.status}; FKGL: {metrics.fkgl_score:.2f}; verbatim: {metrics.verbatim_match_percent:.0f}%")
    print(metrics.safety_judge.overall_verdict + ": " + metrics.safety_judge.explanation)


if __name__ == "__main__":
    main()
