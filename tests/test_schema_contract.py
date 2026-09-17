"""Cross-track checks against Nima's Sync 0 field contract."""
import unittest

from app import mock_components as ui
from schemas import instruction_packet as schema
from nima.schemas import instruction_packet as authority


class SchemaContractTests(unittest.TestCase):
    def test_shared_schema_matches_authority(self):
        for name in ('MedicationOrder', 'ClinicalOrders', 'SafetyJudgeResult',
                     'EvaluationMetrics', 'InstructionPacket'):
            with self.subTest(model=name):
                self.assertEqual(getattr(schema, name).model_json_schema(),
                                 getattr(authority, name).model_json_schema())
                self.assertIs(getattr(ui, name), getattr(schema, name))

    def test_canonical_orders_survive_ui_pipeline_and_serialization(self):
        orders = schema.ClinicalOrders(
            patient_id='SYN-CONTRACT', age='9 years', diagnosis='Synthetic fixture',
            urgent_fever_threshold='100.6°F', emergency_fever_threshold='102.2°F',
            daytime_phone='202-555-0101', after_hours_phone='202-555-0102',
            emergency_phone='911',
            medications=[schema.MedicationOrder(name='Fixture', dose='7 mg')],
        )
        tokens = ui.extract_verbatim_tokens(orders)
        for value in ('100.6°F', '102.2°F', '202-555-0101', '202-555-0102', '7 mg'):
            self.assertIn(value, tokens)
        packet = ui.run_mock_pipeline('sickle_cell_pain', 'v1.2.0', orders)
        self.assertIsInstance(packet, schema.InstructionPacket)
        restored = authority.InstructionPacket.model_validate_json(packet.model_dump_json())
        self.assertEqual(restored.clinical_orders.model_dump(), orders.model_dump())
        self.assertTrue(restored.original_clinical_text)
        self.assertIsNotNone(restored.evaluation_metrics)
        self.assertTrue(ui.generate_handout_pdf(packet).startswith(b'%PDF'))
