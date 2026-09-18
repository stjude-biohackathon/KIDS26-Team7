"""Regression coverage for review gating, loaded selectors, and long PDF exports."""
import re
import unittest
from schemas.instruction_packet import ClinicalOrders, InstructionPacket
from exporters.pdf_generator import create_bilingual_pdf


class LongPdfTests(unittest.TestCase):
    def test_long_bilingual_packet_splits_across_pages(self):
        packet = InstructionPacket(
            packet_id='SYN-LONG', condition='synthetic', status='APPROVED',
            clinical_orders=ClinicalOrders(patient_id='SYN-001', diagnosis='Synthetic fixture'),
            simplified_en='Synthetic English review text. ' * 1500,
            translated_es='Texto de prueba para revisión. ' * 1900,
        )
        pdf = create_bilingual_pdf(packet)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(re.findall(rb'/Type\s*/Page\b', pdf)), 2)

from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest
from tests.test_ui_components import offline_app as _offline_app
from contextlib import contextmanager

@contextmanager
def offline_app(*args, **kwargs):
    with patch('streamlit.secrets', {}), _offline_app(*args, **kwargs):
        yield

APP = str(Path(__file__).resolve().parents[1] / 'app' / 'clinician_ui.py')

class ReviewUiTests(unittest.TestCase):
    def test_unchecked_edit_cannot_publish_or_save(self):
        with offline_app(), patch('storage.gold_library.save_gold_record') as save, patch('storage.gold_library.load_gold_records', return_value=[]):
            at = AppTest.from_file(APP).run()
            next(b for b in at.button if 'Generate Simplified Instructions' in b.label).click().run()
            at.text_area(key='txt_clinician_en').input('Synthetic unchecked text.').run()
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(at.session_state['current_packet'].status, 'PENDING')
            self.assertIsNone(at.session_state['pdf_bytes'])
            save.assert_not_called()

class LoadedSelectorTests(unittest.TestCase):
    def test_selectors_use_loaded_condition_and_versions(self):
        from storage.github_loader import load_mock_templates_and_orders
        _, orders = load_mock_templates_and_orders()
        order = orders['sickle_cell_pain'].model_copy(deep=True)
        order.order_version = 'v9.3.1'
        order.order_id = 'SYN-ORDER-9'
        with offline_app(), patch('storage.github_loader.fetch_remote_templates_and_orders',
                                 return_value=({'new_protocol': {'v9.0.0': 'Synthetic source.'}}, {'new_protocol': order})):
            at = AppTest.from_file(APP).run()
            self.assertEqual(len(at.exception), 0)
            selections = {s.label: s for s in at.selectbox}
            self.assertEqual(selections['Clinical Module:'].value, 'new_protocol')
            self.assertEqual(selections['Module Ver:'].options, ['v9.0.0'])
            self.assertEqual(selections['Order Set Ver:'].value, 'v9.3.1')
            next(b for b in at.button if 'Generate Simplified Instructions' in b.label).click().run()
            self.assertEqual(len(at.exception), 0)
            packet = at.session_state['current_packet']
            self.assertEqual(packet.order_version, 'v9.3.1')
            self.assertIn('Synthetic source.', packet.original_clinical_text)
            self.assertEqual(packet.translated_es, '')

    def test_history_label_does_not_create_fake_archived_content(self):
        from storage.github_loader import adapt_modules
        modules = adapt_modules({'version': 'v9', 'version_history': [{'version': 'v8'}],
                                 'instructions': [{'category': 'synthetic', 'instruction_text': 'Current text.'}]})
        self.assertEqual(list(modules['synthetic']), ['v9'])

class CheckedApprovalTests(unittest.TestCase):
    def packet(self):
        from schemas.instruction_packet import EvaluationMetrics, SafetyJudgeResult, MedicationOrder
        return InstructionPacket(
            packet_id='SYN-CHECKED', condition='sickle_cell_pain',
            clinical_orders=ClinicalOrders(patient_id='SYN-001', diagnosis='Synthetic',
                medications=[MedicationOrder(name='Synthetic', dose='5 mg')],
                urgent_fever_threshold='', emergency_fever_threshold='', emergency_phone=''),
            simplified_en='Synthetic instructions: 5 mg.', translated_es='Prueba: 5 mg.',
            back_translated_en='Synthetic instructions: 5 mg.',
            evaluation_metrics=EvaluationMetrics(fkgl_score=5.8, safety_judge=SafetyJudgeResult(overall_verdict='PASS')),
        )

    def launch(self):
        at = AppTest.from_file(APP).run()
        at.checkbox(key='chk_want_spanish').check().run()
        next(b for b in at.button if 'Generate Simplified Instructions' in b.label).click().run()
        return at

    def test_successful_checks_and_human_review_allow_publish(self):
        packet = self.packet()
        with offline_app(), patch('pipeline.orchestrator.PipelineOrchestrator.generate_live',return_value=packet), patch('storage.gold_library.save_gold_record') as save, patch('storage.gold_library.load_gold_records',return_value=[]):
            at = self.launch()
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            self.assertEqual(len(at.exception),0)
            self.assertEqual(at.session_state['current_packet'].status,'APPROVED')
            self.assertTrue(at.session_state['pdf_bytes'].startswith(b'%PDF'))
            save.assert_called_once()

    def test_edit_after_passing_checks_requires_another_successful_recheck(self):
        packet = self.packet()
        revised = packet.model_copy(deep=True)
        revised.packet_id = 'SYN-REVISED'
        revised.simplified_en = 'Updated synthetic instructions: 5 mg.'
        revised.edited_by_physician = True
        with offline_app(), patch('pipeline.orchestrator.PipelineOrchestrator.generate_live',return_value=packet), patch('pipeline.orchestrator.PipelineOrchestrator.recheck_edits_live',return_value=revised), patch('storage.gold_library.save_gold_record') as save, patch('storage.gold_library.load_gold_records',return_value=[]):
            at = self.launch()
            at.text_area(key='txt_clinician_en').input(revised.simplified_en).run()
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            save.assert_not_called()
            next(b for b in at.button if 'Save & Check Edits' in b.label).click().run()
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            self.assertEqual(len(at.exception),0)
            self.assertEqual(at.session_state['current_packet'].status,'EDITED_AND_APPROVED')
            save.assert_called_once()

    def test_export_failure_does_not_save_approval(self):
        with offline_app(), patch('pipeline.orchestrator.PipelineOrchestrator.generate_live',return_value=self.packet()), patch('exporters.pdf_generator.create_bilingual_pdf',side_effect=RuntimeError('Synthetic export failure')), patch('storage.gold_library.save_gold_record') as save, patch('storage.gold_library.load_gold_records',return_value=[]):
            at = self.launch()
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            self.assertEqual(len(at.exception),0)
            self.assertEqual(at.session_state['current_packet'].status,'PENDING')
            self.assertIsNone(at.session_state['pdf_bytes'])
            save.assert_not_called()

    def test_bad_values_and_failed_judge_block_even_with_current_snapshot(self):
        from app.review import approval_blockers
        for change in ['dose', 'judge', 'translation', 'review']:
            with self.subTest(change=change):
                packet = self.packet()
                if change == 'dose': packet.simplified_en = 'Synthetic instructions: 15 mg.'
                if change == 'judge': packet.evaluation_metrics.safety_judge.overall_verdict = 'FLAGGED_FOR_REVIEW'
                if change == 'translation': packet.translated_es = ''
                reasons = approval_blockers(packet,packet.simplified_en,packet.model_dump(mode='json'),change!='review')
                self.assertTrue(reasons)

    def test_failed_recheck_invalidates_previous_approval_eligibility(self):
        with offline_app(), patch('pipeline.orchestrator.PipelineOrchestrator.generate_live',return_value=self.packet()), patch('storage.gold_library.save_gold_record') as save, patch('storage.gold_library.load_gold_records',return_value=[]):
            at = self.launch()
            next(b for b in at.button if 'Save & Check Edits' in b.label).click().run()
            self.assertIsNone(at.session_state['checked_packet'])
            self.assertEqual(at.session_state['current_packet'].translated_es,'')
            next(b for b in at.button if 'Approve & Publish' in b.label).click().run()
            self.assertEqual(len(at.exception),0)
            save.assert_not_called()
