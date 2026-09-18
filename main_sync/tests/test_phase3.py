"""Phase 3 safety and workflow regressions; synthetic fixtures, no network/disk data."""
import unittest
from unittest.mock import patch
from schemas.instruction_packet import ClinicalOrders, InstructionPacket, MedicationOrder


def packet():
    return InstructionPacket(packet_id='SYN-PHASE3', condition='synthetic',
        clinical_orders=ClinicalOrders(patient_id='SYN-PED-001', diagnosis='Synthetic',
            medications=[MedicationOrder(name='Synthetic medicine',dose='280 mg')],
            daytime_phone='901-555-0100'),
        original_clinical_text='Give 280 mg. Call for 100.4°F or 101.0°F. Call 901-555-0100 or 911.\nRED FLAG: Seek help for sudden chest pain.',
        simplified_en='Give 280 mg. Call for 100.4°F or 101.0°F. Call 901-555-0100 or 911.\nRED FLAG: Seek help for sudden chest pain.',
        translated_es='Prueba 280 mg; 100.4°F; 101.0°F; 901-555-0100; 911.',
        back_translated_en='Test 280 mg; 100.4°F; 101.0°F; 901-555-0100; 911.')


class MemoryLibraryTests(unittest.TestCase):
    def test_snapshots_are_isolated_and_no_disk_is_used(self):
        from storage.gold_library import ReviewLibrary
        first, second = ReviewLibrary(), ReviewLibrary()
        p = packet(); p.status = 'APPROVED'
        with patch('builtins.open', side_effect=AssertionError('No disk writes')):
            first.save(p)
            p.simplified_en = 'Changed later'
            record = first.records()[0]
            self.assertNotEqual(record.simplified_en, p.simplified_en)
            record.simplified_en = 'Changed read copy'
            self.assertNotEqual(first.records()[0].simplified_en, record.simplified_en)
            self.assertEqual(second.records(), [])
            self.assertIsNone(p.reviewed_at)

    def test_duplicate_save_is_idempotent_but_conflicting_history_is_rejected(self):
        from storage.gold_library import ReviewLibrary
        library = ReviewLibrary(); p = packet(); p.status = 'APPROVED'
        library.save(p); library.save(p)
        self.assertEqual(len(library.records()),1)
        library.save(library.records()[0])
        p.simplified_en = 'Overwrite'
        with self.assertRaises(ValueError): library.save(p)

    def test_pending_or_unexplained_rejections_are_not_records(self):
        from storage.gold_library import ReviewLibrary
        p=packet(); library=ReviewLibrary()
        with self.assertRaises(ValueError): library.save(p)
        p.status='REJECTED_DRIFT'
        with self.assertRaises(ValueError): library.save(p)

class DriftTests(unittest.TestCase):
    def test_injections_are_actual_changes_detected_by_evaluation(self):
        from pipeline.drift import inject_drift, evaluate_injected_text
        for mode in ['Altered Medication Dose','Altered Fever Threshold','Contradictory Advice','Omitted Red Flag']:
            with self.subTest(mode=mode):
                original=packet(); before=original.model_dump()
                changed=inject_drift(original,mode)
                self.assertEqual(original.model_dump(),before)
                self.assertNotEqual(changed.packet_id,original.packet_id)
                self.assertNotEqual(changed.simplified_en,original.simplified_en)
                metrics=evaluate_injected_text(original.simplified_en,changed.simplified_en,original.clinical_orders)
                self.assertEqual(metrics.safety_judge.overall_verdict,'FLAGGED_FOR_REVIEW')
                self.assertTrue(changed.is_simulation)
                self.assertEqual(changed.status,'PENDING')
        self.assertIn('560 mg',inject_drift(packet(),'Altered Medication Dose').simplified_en)

    def test_injection_cannot_claim_success_without_matching_content(self):
        from pipeline.drift import inject_drift
        p=packet(); p.simplified_en='No values available.'
        with self.assertRaises(ValueError): inject_drift(p,'Altered Medication Dose')

class ProtectedModelTests(unittest.TestCase):
    def test_translation_masks_and_restores_values_verbatim(self):
        from pipeline.live_llm import translate_to_spanish
        from unittest.mock import MagicMock
        client=MagicMock()
        def response(**kwargs):
            text=kwargs['messages'][1]['content']
            for value in ['280 mg','100.4°F','901-555-0100']:
                self.assertNotIn(value,text)
            return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])
        client.chat.completions.create.side_effect=response
        text='Synthetic: 280 mg; 100.4°F; 901-555-0100.'
        self.assertEqual(translate_to_spanish(client,'synthetic',text),text)

    def test_lost_or_invented_protected_values_fail_closed(self):
        from pipeline.live_llm import translate_to_spanish
        from unittest.mock import MagicMock
        for output in ['No preserved values.', 'Give 999 mg.']:
            client=MagicMock()
            client.chat.completions.create.return_value.choices=[MagicMock(message=MagicMock(content=output))]
            with self.assertRaises(ValueError): translate_to_spanish(client,'synthetic','Give 280 mg.')

    def test_live_english_is_simplified_before_translation(self):
        from pipeline.orchestrator import PipelineOrchestrator
        from schemas.instruction_packet import SafetyJudgeResult
        orders=packet().clinical_orders
        with patch('pipeline.orchestrator.get_client',return_value=(object(),'test')), patch('pipeline.live_llm.simplify_to_plain_language',side_effect=lambda c,m,t,o,**kwargs:t.replace('Use','Give')), patch('pipeline.evaluator.textstat.flesch_kincaid_grade',return_value=5.8), patch('pipeline.live_llm.translate_to_spanish',side_effect=lambda c,m,t:t), patch('pipeline.live_llm.back_translate_to_english',side_effect=lambda c,m,t:t), patch('pipeline.live_llm.judge_safety',return_value=SafetyJudgeResult(overall_verdict='PASS')):
            result=PipelineOrchestrator().generate_live('Use ${medication_0_dose}.',orders,module_version='v1',condition='synthetic')
            self.assertIn('Give 280 mg.',result.simplified_en)

class RejectionTests(unittest.TestCase):
    def test_rejection_requires_reason_and_preserves_original(self):
        from app.review import reject_revision
        p=packet(); before=p.model_dump()
        with self.assertRaises(ValueError): reject_revision(p,p.simplified_en,'Unsafe dosage alteration','  ')
        rejected=reject_revision(p,p.simplified_en+' Changed.','Unsafe dosage alteration','Synthetic test finding')
        self.assertEqual(p.model_dump(),before)
        self.assertEqual(rejected.status,'REJECTED_DRIFT')
        self.assertNotEqual(rejected.packet_id,p.packet_id)
        self.assertEqual(rejected.parent_packet_id,p.packet_id)
        self.assertEqual(rejected.translated_es,'')
        self.assertEqual(rejected.rejection_reason,'Synthetic test finding')

    def test_finalized_packet_cannot_be_rejected_in_place(self):
        from app.review import reject_revision
        p=packet(); p.status='APPROVED'
        with self.assertRaises(ValueError): reject_revision(p,p.simplified_en,'Unsafe dosage alteration','Reason')


class PdfSafetyTests(unittest.TestCase):
    def test_metadata_and_rejection_reason_are_escaped(self):
        from exporters.pdf_generator import create_bilingual_pdf
        p=packet(); p.status='REJECTED_DRIFT'
        p.rejection_reason='Synthetic <font color="invalid-color">tag & value'
        p.clinical_orders.diagnosis='Synthetic <font color="invalid-color">tag & value'
        p.condition='Synthetic <font color="invalid-color">tag & value'
        pdf=create_bilingual_pdf(p)
        self.assertTrue(pdf.startswith(b'%PDF'))

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

@contextmanager
def phase3_app():
    """Real pipeline/storage/PDF with only external service boundaries replaced."""
    import streamlit as st
    from storage.github_loader import load_mock_templates_and_orders
    client=MagicMock()
    def reply(**kwargs):
        prompt=kwargs['messages'][0]['content']
        text=kwargs['messages'][1]['content']
        if 'safety auditor' in prompt:
            text='{"overall_verdict":"PASS","factual_drift_detected":false,"omitted_red_flags":[],"contradictory_advice":[],"clinical_risk_score":0,"explanation":"Synthetic transport test only"}'
        return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])
    client.chat.completions.create.side_effect=reply
    st.cache_data.clear()
    with patch('pipeline.evaluator.textstat.flesch_kincaid_grade',return_value=5.8), patch('streamlit.secrets',{}), patch('storage.github_loader.fetch_remote_templates_and_orders',side_effect=load_mock_templates_and_orders), patch('storage.github_loader.get_last_load_status',return_value={'source':'mock','error':None,'warnings':[]}), patch('pipeline.orchestrator.get_client',return_value=(client,'synthetic')), patch('requests.sessions.Session.request',side_effect=AssertionError('No network')):
        yield client
    st.cache_data.clear()


def click(at,label):
    return next(b for b in at.button if label in b.label).click().run()


class Phase3WorkflowTests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app'/'clinician_ui.py'),default_timeout=15).run()

    def test_all_conditions_approve_edit_and_reject_with_session_history(self):
        for condition in ['sickle_cell_pain','fever_neutropenia','chemo_nausea_hydration']:
            with self.subTest(condition=condition), phase3_app():
                at=self.app()
                next(s for s in at.selectbox if s.label=='Clinical Module:').select(condition).run()
                click(at,'Generate Instructions')
                self.assertEqual(len(at.exception),0)
                at.checkbox[0].check().run()
                click(at,'Approve & Publish')
                self.assertEqual(at.session_state['current_packet'].status,'APPROVED')
                original=at.session_state['review_library'].records()[0]
                self.assertTrue(at.session_state['pdf_bytes'].startswith(b'%PDF'))
                click(at,'Approve & Publish')
                self.assertEqual(len(at.session_state['review_library'].records()),1)
                at.text_area(key='txt_clinician_en').input(original.simplified_en+'\nSynthetic clinician-reviewed clarification.').run()
                click(at,'Save & Check Edits')
                self.assertEqual(at.session_state['current_packet'].status,'PENDING')
                self.assertIsNone(at.session_state['pdf_bytes'])
                at.checkbox[0].check().run()
                click(at,'Approve & Publish')
                self.assertEqual(at.session_state['current_packet'].status,'EDITED_AND_APPROVED')
                records=at.session_state['review_library'].records()
                self.assertEqual(len(records),2)
                self.assertEqual(records[0].model_dump(),original.model_dump())
                self.assertEqual(records[1].parent_packet_id,original.packet_id)
                click(at,'Generate Instructions')
                click(at,'Reject & Log Drift')
                click(at,'Confirm Rejection')
                self.assertEqual(len(at.session_state['review_library'].records()),2)
                next(t for t in at.text_area if 'Clinical Rationale' in t.label).input('Synthetic audit finding.').run()
                click(at,'Confirm Rejection')
                self.assertEqual(len(at.exception),0)
                self.assertEqual(at.session_state['current_packet'].status,'REJECTED_DRIFT')
                self.assertEqual(len(at.session_state['review_library'].records()),3)
                self.assertTrue(at.session_state['pdf_bytes'].startswith(b'%PDF'))

    def test_each_scenario_runs_offline_and_cannot_be_approved(self):
        from pipeline.drift import DRIFT_MODES
        for mode in DRIFT_MODES:
            with self.subTest(mode=mode), phase3_app() as client:
                at=self.app()
                next(s for s in at.selectbox if 'Simulate Safety Failure' in s.label).select(mode).run()
                click(at,'Generate Instructions')
                self.assertEqual(len(at.exception),0)
                self.assertTrue(at.session_state['current_packet'].is_simulation)
                self.assertEqual(at.session_state['current_packet'].evaluation_metrics.safety_judge.overall_verdict,'FLAGGED_FOR_REVIEW')
                at.checkbox[0].check().run()
                click(at,'Approve & Publish')
                self.assertEqual(at.session_state['current_packet'].status,'PENDING')
                self.assertEqual(at.session_state['review_library'].records(),[])
                client.chat.completions.create.assert_not_called()

    def test_separate_app_sessions_do_not_share_reviews(self):
        with phase3_app():
            at=self.app()
            click(at,'Generate Instructions'); at.checkbox[0].check().run(); click(at,'Approve & Publish')
            self.assertEqual(len(at.session_state['review_library'].records()),1)
            other=self.app()
            self.assertEqual(other.session_state['review_library'].records(),[])

class FinalSafetyGateTests(unittest.TestCase):
    def test_judge_pass_without_required_audit_fields_is_not_accepted(self):
        from pipeline.live_llm import judge_safety
        client=MagicMock()
        client.chat.completions.create.return_value.choices=[MagicMock(message=MagicMock(content='{"overall_verdict":"PASS"}'))]
        result=judge_safety(client,'synthetic','Source','Output',packet().clinical_orders)
        self.assertEqual(result.overall_verdict,'FLAGGED_FOR_REVIEW')

    def test_preserving_old_dose_does_not_allow_an_added_wrong_dose(self):
        from app.review import approval_blockers
        from schemas.instruction_packet import EvaluationMetrics, SafetyJudgeResult
        p=packet(); p.simplified_en += '\nAlso give 999 mg.'
        p.evaluation_metrics=EvaluationMetrics(fkgl_score=5.8,safety_judge=SafetyJudgeResult(overall_verdict='PASS'))
        self.assertTrue(approval_blockers(p,p.simplified_en,p.model_dump(mode='json'),True))

    def test_reported_omitted_warning_blocks_even_with_pass_verdict(self):
        from app.review import approval_blockers
        from schemas.instruction_packet import EvaluationMetrics, SafetyJudgeResult
        p=packet(); p.simplified_en=p.simplified_en.split('\n')[0]
        p.evaluation_metrics=EvaluationMetrics(fkgl_score=5.8,safety_judge=SafetyJudgeResult(overall_verdict='PASS',omitted_red_flags=['Missing warning']))
        self.assertTrue(approval_blockers(p,p.simplified_en,p.model_dump(mode='json'),True))

class WorkflowFailureTests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app'/'clinician_ui.py'),default_timeout=15).run()

    def test_live_generation_failure_does_not_substitute_a_mock_packet(self):
        with phase3_app() as client:
            client.chat.completions.create.side_effect=RuntimeError('Synthetic outage')
            at=self.app()
            click(at,'Generate Instructions')
            self.assertEqual(len(at.exception),0)
            self.assertIsNone(at.session_state['current_packet'])
            self.assertIsNone(at.session_state['pdf_bytes'])
            self.assertTrue(any('Generation failed' in e.value for e in at.error))

    def test_refresh_reloads_sources_and_cancel_does_not_save_rejection(self):
        from storage.github_loader import load_mock_templates_and_orders
        with phase3_app(), patch('storage.github_loader.fetch_remote_templates_and_orders',side_effect=load_mock_templates_and_orders) as fetch:
            at=self.app()
            self.assertEqual(fetch.call_count,1)
            click(at,'Refresh')
            self.assertEqual(fetch.call_count,2)
            click(at,'Generate Instructions')
            click(at,'Reject & Log Drift')
            click(at,'Cancel')
            self.assertIsNone(at.session_state['reject_dialog_packet_id'])
            self.assertEqual(at.session_state['review_library'].records(),[])

    def test_rejection_export_failure_preserves_pending_packet(self):
        with phase3_app(), patch('exporters.pdf_generator.create_bilingual_pdf',side_effect=RuntimeError('Synthetic export failure')):
            at=self.app(); click(at,'Generate Instructions'); click(at,'Reject & Log Drift')
            next(t for t in at.text_area if 'Clinical Rationale' in t.label).input('Synthetic finding').run()
            click(at,'Confirm Rejection')
            self.assertEqual(len(at.exception),0)
            self.assertEqual(at.session_state['current_packet'].status,'PENDING')
            self.assertEqual(at.session_state['review_library'].records(),[])

class FailureMessageTests(unittest.TestCase):
    def test_value_validation_failure_is_not_reported_as_bad_credentials(self):
        from pipeline.llms import describe_model_error
        message=describe_model_error('gpt4o', ValueError('Synthetic private source canary'))
        self.assertNotIn('credentials',message)
        self.assertNotIn('canary',message)
