import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from datetime import datetime, timezone


class TestInstructionPacketSchema(unittest.TestCase):
    def test_schema_imports(self):
        from schemas.instruction_packet import (
            MedicationOrder,
            ClinicalOrders,
            SafetyJudgeResult,
            EvaluationMetrics,
            InstructionPacket,
            get_physician_annotation,
        )

    def test_medication_order_valid(self):
        from schemas.instruction_packet import MedicationOrder

        med = MedicationOrder(
            name="Hydroxyurea",
            dose="500 mg",
            route="oral",
            frequency="once daily",
            special_instructions="Take with a full glass of water",
        )
        self.assertEqual(med.name, "Hydroxyurea")
        self.assertEqual(med.dose, "500 mg")
        self.assertEqual(med.route, "oral")
        self.assertEqual(med.frequency, "once daily")
        self.assertEqual(med.special_instructions, "Take with a full glass of water")

    def test_clinical_orders_valid(self):
        from schemas.instruction_packet import MedicationOrder, ClinicalOrders

        med = MedicationOrder(
            name="Ibuprofen",
            dose="200 mg",
            route="oral",
            frequency="every 6 hours as needed for pain",
        )
        orders = ClinicalOrders(
            patient_id="SYN-PED-001",
            age="8 years",
            diagnosis="Sickle Cell Disease with Vaso-occlusive Crisis",
            medications=[med],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-5555",
            emergency_phone="911",
            order_id="ORD-SCD-01",
            order_version="v1.2.0",
        )
        self.assertEqual(orders.patient_id, "SYN-PED-001")
        self.assertEqual(len(orders.medications), 1)
        self.assertEqual(orders.urgent_fever_threshold, "100.4°F")

    def test_safety_judge_result(self):
        from schemas.instruction_packet import SafetyJudgeResult

        judge = SafetyJudgeResult(
            overall_verdict="PASS",
            factual_drift_detected=False,
            omitted_red_flags=[],
            contradictory_advice=[],
            clinical_risk_score=0.0,
            explanation="Instructions align accurately with clinical orders.",
        )
        self.assertEqual(judge.overall_verdict, "PASS")
        self.assertFalse(judge.factual_drift_detected)

    def test_evaluation_metrics(self):
        from schemas.instruction_packet import EvaluationMetrics, SafetyJudgeResult

        metrics = EvaluationMetrics(
            fkgl_score=5.8,
            verbatim_matches=["500 mg", "100.4°F", "901-595-3300"],
            verbatim_mismatches=[],
            verbatim_match_percent=100.0,
            safety_judge=SafetyJudgeResult(
                overall_verdict="PASS",
                factual_drift_detected=False,
            ),
        )
        self.assertEqual(metrics.fkgl_score, 5.8)
        self.assertEqual(metrics.verbatim_match_percent, 100.0)

    def test_instruction_packet_and_annotation(self):
        from schemas.instruction_packet import (
            InstructionPacket,
            ClinicalOrders,
            MedicationOrder,
            get_physician_annotation,
        )

        orders = ClinicalOrders(
            patient_id="SYN-PED-001",
            age="8 years",
            diagnosis="Sickle Cell Anemia",
            medications=[
                MedicationOrder(
                    name="Morphine", dose="5 mg", route="oral", frequency="q4h prn"
                )
            ],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-5555",
            order_id="ORD-SCD-01",
            order_version="v1.2.0",
        )

        packet = InstructionPacket(
            packet_id="PKT-2026-001",
            condition="sickle_cell_pain",
            module_version="v1.2.0",
            order_version="v1.2.0",
            original_clinical_text="Administer morphine for breakthrough sickle cell pain crisis.",
            clinical_orders=orders,
            simplified_en="Give your child 5 mg of morphine by mouth every 4 hours if pain is severe.",
            translated_es="Dé a su hijo 5 mg de morfina por vía oral cada 4 horas si el dolor es intenso.",
            back_translated_en="Give your child 5 mg of morphine orally every 4 hours if pain is severe.",
            status="PENDING",
        )

        self.assertEqual(get_physician_annotation(packet), "Pending physician review")

        packet.status = "APPROVED"
        self.assertEqual(get_physician_annotation(packet), "Approved by physician")

        packet.status = "EDITED_AND_APPROVED"
        self.assertEqual(
            get_physician_annotation(packet), "Edited and approved by physician"
        )

        packet.status = "REJECTED_DRIFT"
        self.assertEqual(get_physician_annotation(packet), "Rejected by physician")


if __name__ == "__main__":
    unittest.main()
