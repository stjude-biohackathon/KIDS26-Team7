"""Exercise the shared Phase 1 entrypoints with synthetic data and no live APIs."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.mock_components import run_mock_pipeline
from storage.github_loader import load_mock_templates_and_orders
from storage.gold_library import save_to_gold_library, load_gold_records
from pipeline.orchestrator import PipelineOrchestrator


class IntegratedPipelineTests(unittest.TestCase):
    def test_generation_uses_shared_checks_and_copies_loaded_orders(self):
        modules, orders = load_mock_templates_and_orders()
        before = orders['sickle_cell_pain'].model_dump()
        packet = run_mock_pipeline('sickle_cell_pain', 'v1.2.0', orders['sickle_cell_pain'])
        self.assertEqual(packet.original_clinical_text, modules['sickle_cell_pain']['v1.2.0'])
        self.assertEqual(packet.status, 'PENDING')
        # Ramzi's supplied fixture omits this threshold. The shared checker must
        # expose that omission rather than pretending the fixture passed.
        self.assertIn('101.0°F', packet.evaluation_metrics.verbatim_mismatches)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
        self.assertIn('Mock checks only', packet.evaluation_metrics.safety_judge.explanation)
        orders['sickle_cell_pain'].medications[0].dose = '15 mg'
        self.assertEqual(packet.clinical_orders.model_dump(), before)


class IntegratedStorageTests(unittest.TestCase):
    def test_review_records_are_independent_in_memory_snapshots(self):
        _, orders = load_mock_templates_and_orders()
        packet = run_mock_pipeline('sickle_cell_pain', 'v1.2.0', orders['sickle_cell_pain'])
        packet.status = 'APPROVED'
        before = packet.model_dump()
        library = []
        with patch('builtins.open', side_effect=AssertionError('No data files in Phase 1')):
            save_to_gold_library(packet, library=library)
            packet.simplified_en = 'A later edit.'
            records = load_gold_records(library=library)
            self.assertEqual(records[0].simplified_en, before['simplified_en'])
            self.assertEqual(records[0].physician_decision, 'Approved by physician')
            self.assertIsNotNone(records[0].reviewed_at)
            records[0].clinical_orders.medications[0].dose = '15 mg'
            self.assertEqual(load_gold_records(library=library)[0].clinical_orders.medications[0].dose, '200 mg')
            self.assertEqual(load_gold_records(library=[]), [])
        # Saving should not stamp a review onto the caller's original object.
        self.assertEqual(packet.reviewed_at, before['reviewed_at'])


class IntegratedUITests(unittest.TestCase):
    def test_all_condition_screens_use_their_own_orders_without_network_calls(self):
        from streamlit.testing.v1 import AppTest
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Phase 1 must stay offline')):
            at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
            for condition, dose in (('sickle_cell_pain', '200 mg'), ('fever_neutropenia', '1000 mg'), ('chemo_nausea_hydration', '4 mg')):
                with self.subTest(condition=condition):
                    next(widget for widget in at.selectbox if widget.label == 'Clinical Module:').select(condition).run()
                    next(button for button in at.button if 'Generate Instructions' in button.label).click().run()
                    self.assertFalse(at.exception)
                    packet = at.session_state['current_packet']
                    self.assertEqual(packet.condition, condition)
                    self.assertEqual(packet.clinical_orders.medications[0].dose, dose)
                    self.assertTrue(packet.original_clinical_text)
                    self.assertTrue(packet.simplified_en)
                    self.assertTrue(packet.translated_es)
                    self.assertTrue(packet.back_translated_en)
                    self.assertEqual(packet.status, 'PENDING')

    def test_complete_fixture_requires_spanish_review_then_saves_pdf_and_snapshot(self):
        from streamlit.testing.v1 import AppTest
        _, orders = load_mock_templates_and_orders()
        # Neutral synthetic labels exercise the positive review path without
        # inventing clinical advice to fill gaps in the supplied demo paragraphs.
        values = '200 mg; 5 mg; 100.4°F; 101.0°F; 901-595-3300; 911.'
        packet = PipelineOrchestrator().generate(
            'Synthetic test reference.', orders['sickle_cell_pain'],
            condition='sickle_cell_pain', module_version='v1.2.0',
            simplified_template_text='Example: ' + values,
            spanish_template_text='Ejemplo: ' + values,
            back_translation_template_text='Example: ' + values,
        )
        at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15)
        at.session_state['current_packet'] = packet
        at.session_state['txt_clinician_en'] = packet.simplified_en
        at.run()
        next(button for button in at.button if 'Approve & Publish' in button.label).click().run()
        self.assertEqual(at.session_state['current_packet'].status, 'PENDING')
        at.checkbox(key=f'spanish_reviewed_{packet.packet_id}').check().run()
        at.text_input(key=f'spanish_reviewer_{packet.packet_id}').input('Synthetic reviewer').run()
        next(button for button in at.button if 'Approve & Publish' in button.label).click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['current_packet'].status, 'APPROVED')
        self.assertTrue(at.session_state['pdf_bytes'].startswith(b'%PDF-'))
        records = load_gold_records(library=at.session_state['gold_library'])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, 'APPROVED')
        self.assertIn('Synthetic reviewer', records[0].clinician_notes)
        # A fresh browser session must not inherit the first session's records.
        other = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
        self.assertEqual(other.session_state['gold_library'], [])

    def test_rejection_records_reason_and_produces_track_b_pdf(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
        next(button for button in at.button if 'Generate Instructions' in button.label).click().run()
        next(button for button in at.button if 'Reject & Log Drift' in button.label).click().run()
        # A rerun while entering notes must not close the rejection dialog.
        next(widget for widget in at.text_area if widget.label.startswith('Clinical Rationale')).input('Synthetic review: missing threshold.').run()
        next(button for button in at.button if button.label == 'Confirm Rejection').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['current_packet'].status, 'REJECTED_DRIFT')
        self.assertTrue(at.session_state['pdf_bytes'].startswith(b'%PDF-'))
        records = load_gold_records(library=at.session_state['gold_library'])
        self.assertEqual(records[0].rejection_reason, 'Synthetic review: missing threshold.')

    def test_ui_cannot_publish_a_packet_with_known_missing_values(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
        next(button for button in at.button if 'Generate Instructions' in button.label).click().run()
        next(button for button in at.button if 'Approve & Publish' in button.label).click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['current_packet'].status, 'PENDING')
        self.assertEqual(at.session_state['gold_library'], [])
        self.assertIsNone(at.session_state['pdf_bytes'])
        self.assertTrue(at.error)

    def test_ui_uses_mock_loader_versions_and_preserves_edits_as_a_revision(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
        self.assertFalse(at.exception)
        self.assertTrue(any('Mock data' in item.value for item in at.markdown))
        next(button for button in at.button if 'Generate Instructions' in button.label).click().run()
        self.assertFalse(at.exception)
        original = at.session_state['current_packet']
        before = original.model_dump()
        self.assertEqual(original.order_version, 'v1.2.0')
        self.assertEqual(original.clinical_orders.order_id, 'ORD-SCD-01')
        at.text_area(key='txt_clinician_en').input(original.simplified_en + '\nSynthetic edit.').run()
        next(button for button in at.button if 'Save & Check Edits' in button.label).click().run()
        self.assertFalse(at.exception)
        revision = at.session_state['current_packet']
        self.assertNotEqual(revision.packet_id, original.packet_id)
        self.assertEqual(original.model_dump(), before)
        self.assertEqual(revision.status, 'PENDING')
        self.assertEqual(revision.translated_es, '')
        self.assertEqual(revision.back_translated_en, '')
        self.assertTrue(any('unavailable' in item.value.lower() for item in at.info))


if __name__ == '__main__':
    unittest.main()
