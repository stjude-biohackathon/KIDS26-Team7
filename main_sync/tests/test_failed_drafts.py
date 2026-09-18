"""Failed protected output stays reviewable, never approvable or silently repaired."""
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from pipeline.orchestrator import PipelineOrchestrator
from schemas.instruction_packet import ClinicalOrders, MedicationOrder
from app.review import approval_blockers


def synthetic_orders():
    return ClinicalOrders(patient_id='SYN-FAILED', diagnosis='Synthetic',
        medications=[MedicationOrder(name='Example', dose='5 mg')],
        urgent_fever_threshold='', emergency_fever_threshold='', emergency_phone='')


@contextmanager
def provider(fail_stage):
    client = MagicMock()
    calls = []
    def reply(**kwargs):
        prompt = kwargs['messages'][0]['content']
        text = kwargs['messages'][1]['content']
        stage = ('English simplification' if prompt.startswith('Simplify') else
                 'Spanish translation' if 'Latin American' in prompt else
                 'English back-translation' if 'literally' in prompt else 'judge')
        calls.append(stage)
        if stage == fail_stage:
            text = 'Give 10 mg instead.'
        elif stage == 'judge':
            text = '{"overall_verdict":"PASS","factual_drift_detected":false,"omitted_red_flags":[],"contradictory_advice":[],"clinical_risk_score":0,"explanation":"Synthetic audit."}'
        return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])
    client.chat.completions.create.side_effect = reply
    with patch('pipeline.orchestrator.get_client', return_value=(client, 'test')), patch('pipeline.evaluator.textstat.flesch_kincaid_grade', return_value=5.8):
        yield calls


class FailedDraftTests(unittest.TestCase):
    def test_each_failed_stage_returns_a_flagged_draft_and_stops_later_calls(self):
        for stage in ('English simplification', 'Spanish translation', 'English back-translation'):
            with self.subTest(stage=stage), provider(stage) as calls:
                packet = PipelineOrchestrator().generate_live('Give 5 mg.', synthetic_orders(), condition='test', module_version='v1')
                metrics = packet.evaluation_metrics
                self.assertEqual(packet.status, 'PENDING')
                self.assertTrue(any(stage in f and '5 mg' in f for f in metrics.protection_failures))
                self.assertTrue(any('10 mg' in f for f in metrics.protection_failures))
                self.assertEqual(metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
                self.assertEqual(calls[-1], stage)
                self.assertNotIn('judge', calls)
                self.assertIn('10 mg', getattr(packet, {'English simplification':'simplified_en','Spanish translation':'translated_es','English back-translation':'back_translated_en'}[stage]))
                # A permissive judge/snapshot must not override deterministic failure.
                metrics.safety_judge.overall_verdict = 'PASS'
                self.assertTrue(approval_blockers(packet, packet.simplified_en, packet.model_dump(mode='json'), True))

    def test_successful_recheck_clears_findings_on_a_new_revision(self):
        with provider('English simplification'):
            failed = PipelineOrchestrator().generate_live('Give 5 mg.', synthetic_orders(), condition='test', module_version='v1', translate=False)
        before = failed.model_dump()
        with provider(None):
            still_bad = PipelineOrchestrator().recheck_edits_live(failed, failed.simplified_en, translate=False)
            fixed = PipelineOrchestrator().recheck_edits_live(failed, 'Give 5 mg.', translate=False)
        self.assertTrue(still_bad.evaluation_metrics.protection_failures)
        self.assertEqual(fixed.evaluation_metrics.protection_failures, [])
        self.assertEqual(approval_blockers(fixed, fixed.simplified_en, fixed.model_dump(mode='json'), False, spanish_requested=False), [])
        self.assertEqual(failed.model_dump(), before)
        self.assertEqual(fixed.parent_packet_id, failed.packet_id)

    def test_failed_recheck_keeps_spanish_draft(self):
        with provider(None):
            original = PipelineOrchestrator().generate_live('Give 5 mg.', synthetic_orders(), condition='test', module_version='v1')
        with provider('Spanish translation'):
            failed = PipelineOrchestrator().recheck_edits_live(original, 'Please give 5 mg.')
        self.assertEqual(failed.translated_es, 'Give 10 mg instead.')
        self.assertEqual(failed.back_translated_en, '')
        self.assertTrue(failed.evaluation_metrics.protection_failures)

    def test_marker_counts_and_unknown_markers_are_reported_without_guessing(self):
        from pipeline.protection import ProtectedText, ProtectionError
        protected = ProtectedText('Give 5 mg. Repeat 5 mg. Call 911.')
        dose, phone = protected.values
        for response, word in [(dose+' '+phone, 'Missing'), (protected.masked+' '+dose, 'Duplicated'), (protected.masked+' [[CLEAR_unknown_0]]', 'Unknown'), (protected.masked+' 10 mg', 'Unexpected')]:
            with self.subTest(word=word):
                with self.assertRaises(ProtectionError) as raised:
                    protected.restore(response)
                self.assertIn('5 mg', raised.exception.draft_text)
                self.assertTrue(any(word in f for f in raised.exception.findings))
                self.assertNotIn('5 mg', str(raised.exception))

    def test_ui_shows_failed_draft_tokens_and_blocks_publish(self):
        from tests.test_ui_components import offline_app
        from streamlit.testing.v1 import AppTest
        from pathlib import Path
        with provider('English simplification'):
            failed = PipelineOrchestrator().generate_live('Give 5 mg.', synthetic_orders(), condition='test', module_version='v1', translate=False)
        with offline_app(), patch('pipeline.orchestrator.PipelineOrchestrator.generate_live', return_value=failed), patch('storage.gold_library.save_gold_record') as save:
            app = AppTest.from_file(str(Path(__file__).parents[1]/'app'/'clinician_ui.py')).run()
            next(b for b in app.button if b.label == 'Generate Simplified Instructions').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_area(key='txt_clinician_en').value, failed.simplified_en)
            self.assertIsNone(app.session_state['checked_packet'])
            self.assertTrue(any('5 mg' in t.value for t in app.text))
            self.assertTrue(any('not for patient use' in e.value.lower() for e in app.error))
            self.assertEqual(next(m for m in app.metric if m.label=='Verbatim Score').value, 'FAILED')
            next(b for b in app.button if b.label == 'Approve & Publish').click().run()
            save.assert_not_called()
            self.assertIsNone(app.session_state['pdf_bytes'])

    def test_failed_values_cannot_be_exported_or_saved_as_approved(self):
        from exporters.pdf_generator import create_bilingual_pdf
        from storage.gold_library import ReviewLibrary
        with provider('English simplification'):
            failed = PipelineOrchestrator().generate_live('Give 5 mg.', synthetic_orders(), condition='test', module_version='v1', translate=False)
        failed.status = 'APPROVED'
        with self.assertRaises(ValueError):
            create_bilingual_pdf(failed)
        with self.assertRaises(ValueError):
            ReviewLibrary().save(failed)

    def test_source_only_repeated_value_cannot_be_waived_by_recheck(self):
        from pipeline.protection import numeric_findings
        self.assertTrue(numeric_findings('Rest for 2 hours. Repeat after 2 hours.', 'Rest for 2 hours.'))
        self.assertTrue(numeric_findings('Rest.', '[UNRESOLVED PROTECTED VALUE]'))
