import sys
import os

# Ensure project root is in sys.path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Ensure local venv site-packages is in sys.path if not activated
_venv_site = os.path.join(_project_root, "venv", "lib", "python3.14", "site-packages")
if os.path.exists(_venv_site) and _venv_site not in sys.path:
    sys.path.append(_venv_site)

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


class TestGoldLibraryStorage(unittest.TestCase):
    def setUp(self):
        from storage.gold_library import ReviewLibrary
        self.library = ReviewLibrary()

        from schemas.instruction_packet import ClinicalOrders, MedicationOrder, InstructionPacket
        self.orders = ClinicalOrders(
            patient_id="SYN-PED-002",
            diagnosis="Pediatric Fever & Neutropenia",
            medications=[MedicationOrder(name="Cefepime", dose="1000 mg", route="IV", frequency="q8h")],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
        )
        self.packet = InstructionPacket(
            packet_id="PKT-TEST-FN01",
            condition="fever_neutropenia",
            clinical_orders=self.orders,
            simplified_en="Seek emergency care immediately if fever reaches 100.4°F.",
            translated_es="Busque atención de emergencia de inmediato si la fiebre llega a 100.4°F.",
            back_translated_en="Seek emergency care immediately if fever reaches 100.4°F.",
            status="APPROVED",
        )

    def test_save_and_load_gold_library(self):
        from storage.gold_library import save_to_gold_library, load_gold_records

        save_to_gold_library(self.packet, library=self.library)

        records = load_gold_records(library=self.library)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].packet_id, "PKT-TEST-FN01")
        self.assertEqual(records[0].status, "APPROVED")
        self.assertEqual(records[0].physician_decision, "Approved by physician")

    def test_gold_library_append_immutability(self):
        from storage.gold_library import save_gold_record, load_gold_records

        save_gold_record(self.packet, library=self.library)

        # Second packet
        self.packet.packet_id = "PKT-TEST-FN02"
        self.packet.status = "REJECTED_DRIFT"
        self.packet.rejection_reason = "Altered fever threshold"
        self.packet.rejection_category = "Altered return/fever threshold"
        save_gold_record(self.packet, library=self.library)

        records = load_gold_records(library=self.library)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].packet_id, "PKT-TEST-FN01")
        self.assertEqual(records[0].status, "APPROVED")
        self.assertEqual(records[1].packet_id, "PKT-TEST-FN02")
        self.assertEqual(records[1].status, "REJECTED_DRIFT")
        self.assertEqual(records[1].rejection_reason, "Altered fever threshold")

    def test_rejection_without_optional_notes_can_be_saved(self):
        self.packet.status = "REJECTED_DRIFT"
        self.packet.rejection_reason = None
        self.packet.rejection_category = None
        self.library.save(self.packet)
        saved = self.library.records()[0]
        self.assertEqual(saved.status, "REJECTED_DRIFT")
        self.assertIsNone(saved.rejection_reason)


class TestPdfGenerator(unittest.TestCase):
    def setUp(self):
        from schemas.instruction_packet import ClinicalOrders, MedicationOrder, InstructionPacket
        self.orders = ClinicalOrders(
            patient_id="SYN-PED-003",
            diagnosis="Sickle Cell Pain Crisis",
            medications=[MedicationOrder(name="Ibuprofen", dose="200 mg", route="oral", frequency="q6h")],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
        )
        self.packet = InstructionPacket(
            packet_id="PKT-PDF-001",
            condition="sickle_cell_pain",
            clinical_orders=self.orders,
            simplified_en="Give your child 200 mg of Ibuprofen every 6 hours with food.",
            translated_es="Dé a su hijo 200 mg de Ibuprofeno cada 6 horas con comida.",
            back_translated_en="Give your child 200 mg of Ibuprofen every 6 hours with food.",
            status="APPROVED",
        )

    def test_pdf_generation_approved(self):
        from exporters.pdf_generator import create_bilingual_pdf, generate_pdf_handout

        pdf_bytes = create_bilingual_pdf(self.packet)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 0)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

        pdf_alias = generate_pdf_handout(self.packet)
        self.assertTrue(pdf_alias.startswith(b"%PDF-"))

    def test_pdf_generation_edited_and_approved(self):
        from exporters.pdf_generator import create_bilingual_pdf

        self.packet.status = "EDITED_AND_APPROVED"
        self.packet.edited_by_physician = True
        pdf_bytes = create_bilingual_pdf(self.packet)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_pdf_generation_rejected_drift(self):
        from exporters.pdf_generator import create_bilingual_pdf

        self.packet.status = "REJECTED_DRIFT"
        self.packet.rejection_reason = "Dosage modified from 200 mg to 400 mg"
        self.packet.rejection_category = "Unsafe dosage alteration"
        pdf_bytes = create_bilingual_pdf(self.packet)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))


class TestMockDataLoader(unittest.TestCase):
    def test_mock_loader_templates_and_orders(self):
        from storage.github_loader import load_mock_templates_and_orders

        modules, orders = load_mock_templates_and_orders()
        self.assertIn("sickle_cell_pain", modules)
        self.assertIn("fever_neutropenia", modules)
        self.assertIn("chemo_nausea_hydration", modules)

        self.assertIn("sickle_cell_pain", orders)
        self.assertIn("fever_neutropenia", orders)
        self.assertIn("chemo_nausea_hydration", orders)

        from schemas.instruction_packet import ClinicalOrders
        for cond, order_obj in orders.items():
            self.assertIsInstance(order_obj, ClinicalOrders)
            self.assertTrue(len(order_obj.medications) > 0)
            self.assertTrue(order_obj.urgent_fever_threshold)


if __name__ == "__main__":
    unittest.main()
