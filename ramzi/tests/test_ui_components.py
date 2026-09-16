"""
Track C UI & Component Integration Tests.
Validates schemas, evaluation metrics, drift simulation, library persistence,
and PDF rendering for the Clinician Review Dashboard.
"""

from __future__ import annotations

import unittest
from app.mock_components import (
    ClinicalOrders,
    EvaluationMetrics,
    InstructionPacket,
    MedicationOrder,
    SafetyJudgeResult,
    evaluate_text_verbatim_and_fkgl,
    extract_verbatim_tokens,
    generate_handout_pdf,
    get_physician_annotation,
    load_gold_records,
    run_mock_pipeline,
    save_to_gold_library,
)


class TestTrackCComponents(unittest.TestCase):
    def setUp(self):
        self.orders = ClinicalOrders(
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
                ),
                MedicationOrder(
                    name="Oxycodone oral solution",
                    dose="5 mg",
                    route="oral",
                    frequency="every 4 hours as needed for severe pain",
                ),
            ],
            fever_threshold_urgent="100.4°F",
            fever_threshold_emergency="101.0°F",
            phone_clinic="901-595-3300",
            phone_triage_247="901-595-3300",
            phone_emergency="911",
        )

    def test_schema_instantiation(self):
        packet = InstructionPacket(
            condition="sickle_cell_pain",
            clinical_orders=self.orders,
            simplified_en="Sample text with 200 mg and 100.4°F.",
        )
        self.assertTrue(packet.packet_id.startswith("PKT-"))
        self.assertEqual(packet.status, "PENDING")
        self.assertEqual(packet.clinical_orders.patient_id, "SYN-PED-001")

    def test_physician_annotation_logic(self):
        p_pending = InstructionPacket(status="PENDING")
        p_approved = InstructionPacket(status="APPROVED")
        p_edited = InstructionPacket(status="EDITED_AND_APPROVED")
        p_rejected = InstructionPacket(status="REJECTED_DRIFT")

        self.assertEqual(get_physician_annotation(p_pending), "Pending physician review")
        self.assertEqual(get_physician_annotation(p_approved), "Approved by physician")
        self.assertEqual(get_physician_annotation(p_edited), "Edited and approved by physician")
        self.assertEqual(get_physician_annotation(p_rejected), "Rejected by physician")

    def test_verbatim_extraction_and_evaluation(self):
        tokens = extract_verbatim_tokens(self.orders)
        self.assertIn("200 mg", tokens)
        self.assertIn("5 mg", tokens)
        self.assertIn("100.4°F", tokens)
        self.assertIn("901-595-3300", tokens)

        # Test full match text
        full_text = (
            "Give Ibuprofen 200 mg every 6 hours and Oxycodone 5 mg if pain continues. "
            "Call clinic at 901-595-3300 if fever reaches 100.4°F or 101.0°F. Emergency: 911."
        )
        metrics = evaluate_text_verbatim_and_fkgl(full_text, self.orders)
        self.assertEqual(len(metrics.verbatim_mismatches), 0)
        self.assertEqual(metrics.verbatim_match_percent, 100.0)
        self.assertEqual(metrics.safety_judge.overall_verdict, "PASS")

        # Test missing dose mismatch
        missing_text = "Give medicine regularly. Call 901-595-3300 for fever 100.4°F. Emergency 911."
        mismatch_metrics = evaluate_text_verbatim_and_fkgl(missing_text, self.orders)
        self.assertIn("200 mg", mismatch_metrics.verbatim_mismatches)
        self.assertIn("5 mg", mismatch_metrics.verbatim_mismatches)
        self.assertEqual(mismatch_metrics.safety_judge.overall_verdict, "NEEDS_REVIEW")

    def test_drift_simulator_injections(self):
        # Test Altered Medication Dose
        p_drift_dose = run_mock_pipeline(
            condition="sickle_cell_pain",
            module_version="v1.2.0",
            orders=self.orders,
            drift_mode="Altered Medication Dose",
        )
        self.assertTrue(p_drift_dose.metrics.safety_judge.factual_drift_detected)
        self.assertEqual(p_drift_dose.metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")
        self.assertIn("200 mg", p_drift_dose.metrics.verbatim_mismatches)

        # Test Altered Fever Threshold
        p_drift_fever = run_mock_pipeline(
            condition="fever_neutropenia",
            module_version="v1.2.0",
            orders=self.orders,
            drift_mode="Altered Fever Threshold",
        )
        self.assertTrue(p_drift_fever.metrics.safety_judge.factual_drift_detected)
        self.assertEqual(p_drift_fever.metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")

    def test_mock_pipeline_generation(self):
        packet = run_mock_pipeline(
            condition="sickle_cell_pain",
            module_version="v1.2.0",
            orders=self.orders,
        )
        self.assertTrue(len(packet.simplified_en) > 50)
        self.assertTrue(len(packet.translated_es) > 50)
        self.assertTrue(len(packet.back_translated_en) > 50)
        self.assertEqual(packet.status, "PENDING")

    def test_gold_library_persistence(self):
        packet = run_mock_pipeline("sickle_cell_pain", "v1.2.0", self.orders)
        packet.status = "APPROVED"
        save_to_gold_library(packet)

        records = load_gold_records()
        self.assertTrue(len(records) > 0)
        saved = [r for r in records if r.packet_id == packet.packet_id]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].physician_decision, "Approved by physician")

    def test_bilingual_pdf_export(self):
        packet = run_mock_pipeline("sickle_cell_pain", "v1.2.0", self.orders)
        
        # Test Approved PDF
        packet.status = "APPROVED"
        pdf_approved = generate_handout_pdf(packet)
        self.assertTrue(isinstance(pdf_approved, bytes))
        self.assertTrue(len(pdf_approved) > 1000)
        self.assertTrue(pdf_approved.startswith(b"%PDF"))

        # Test Edited & Approved PDF
        packet.status = "EDITED_AND_APPROVED"
        packet.clinician_edited_en = "Custom modified instructions by clinician."
        pdf_edited = generate_handout_pdf(packet)
        self.assertTrue(pdf_edited.startswith(b"%PDF"))

        # Test Rejected PDF
        packet.status = "REJECTED_DRIFT"
        packet.rejection_reason = "Unsafe dosage alteration"
        pdf_rejected = generate_handout_pdf(packet)
        self.assertTrue(pdf_rejected.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
