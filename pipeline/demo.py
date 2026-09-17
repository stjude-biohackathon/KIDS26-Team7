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
    # Reuse the same blanks in each example so we can see whether their values
    # survive in all three outputs. No real patient records are loaded.
    values = (
        "$medication_0_dose; $urgent_fever_threshold; $emergency_fever_threshold; "
        "$daytime_phone; $after_hours_phone; $emergency_phone."
    )
    # This is the call Track C will make with Track B's data at the team sync.
    # The caller provides every example sentence, including both bilingual ones.
    packet = PipelineOrchestrator().generate(
        "Synthetic reference values: " + values,
        orders, module_version="v1.0.0", condition="sickle_cell_pain",
        simplified_template_text="This is a test. Example values: " + values,
        spanish_template_text="Ejemplo sintético. Valores: " + values,
        back_translation_template_text="Synthetic example. Values: " + values,
    )
    print("Sync 1 mock demonstration — supplied templates, no LLM calls or file writes.")
    # Print the four strings the UI will show in its four comparison panes.
    for label, text in (
        ("Original source (preserved)", packet.original_clinical_text),
        ("English (bound template)", packet.simplified_en),
        ("Spanish (supplied mock)", packet.translated_es),
        ("Back-translation (supplied mock)", packet.back_translated_en),
    ):
        print(f"\n{label}:\n{text}")
    metrics = packet.evaluation_metrics
    # Show the real local scores beside the mock verdict. PENDING means the
    # packet has been prepared for review, not approved for a family to use.
    print(f"\nStatus: {packet.status}; FKGL: {metrics.fkgl_score:.2f}; verbatim: {metrics.verbatim_match_percent:.0f}%")
    print(metrics.safety_judge.overall_verdict + ": " + metrics.safety_judge.explanation)


if __name__ == "__main__":
    # Run the demo when invoked as a command; importing this file does not run it.
    main()
