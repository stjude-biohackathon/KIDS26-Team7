"""Live simplification, measured FKGL gating, and hidden offline mode."""
import unittest
from unittest.mock import MagicMock, patch
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.protection import ProtectionError
from schemas.instruction_packet import ClinicalOrders, SafetyJudgeResult, EvaluationMetrics, InstructionPacket


def orders():
    return ClinicalOrders(patient_id='SYN-TEST',diagnosis='Synthetic',urgent_fever_threshold='',emergency_fever_threshold='',emergency_phone='')


class SimplificationTests(unittest.TestCase):
    def test_simplification_masks_values_and_restores_them(self):
        from pipeline.live_llm import simplify_to_plain_language
        client=MagicMock()
        def reply(**kwargs):
            text=kwargs['messages'][1]['content']
            self.assertNotIn('5 mg',text)
            self.assertIn('5.0',kwargs['messages'][0]['content'])
            return MagicMock(choices=[MagicMock(message=MagicMock(content=text.replace('Administer','Give')))])
        client.chat.completions.create.side_effect=reply
        result=simplify_to_plain_language(client,'test','Administer 5 mg.',orders())
        self.assertEqual(result,'Give 5 mg.')

    def test_measured_fkgl_failure_retries_before_translation(self):
        with patch('pipeline.orchestrator.get_client',return_value=(object(),'test')), patch('pipeline.live_llm.simplify_to_plain_language',side_effect=['First candidate.','Passing candidate.']) as simplify, patch('pipeline.evaluator.textstat.flesch_kincaid_grade',side_effect=[9.2,5.8]), patch('pipeline.live_llm.translate_to_spanish',return_value='Prueba.') as translate, patch('pipeline.live_llm.back_translate_to_english',return_value='Passing candidate.'), patch('pipeline.live_llm.judge_safety',return_value=SafetyJudgeResult(overall_verdict='PASS')):
            result=PipelineOrchestrator().generate_live('Complex source.',orders(),module_version='v1',condition='test')
        self.assertEqual(simplify.call_count,2)
        self.assertEqual(result.simplified_en,'Passing candidate.')
        self.assertEqual(result.evaluation_metrics.fkgl_score,5.8)
        translate.assert_called_once_with(unittest.mock.ANY,'test','Passing candidate.')

    def test_missing_protected_value_retries_before_translation(self):
        missing = ProtectionError(
            'Protected values failed validation; draft requires review.',
            draft_text='Give the medicine.',
            findings=['Missing protected value: 5 mg (required at least once, found 0).'],
        )
        with patch('pipeline.orchestrator.get_client',return_value=(object(),'test')), patch(
            'pipeline.live_llm.simplify_to_plain_language',
            side_effect=[missing, 'Give 5 mg.'],
        ) as simplify, patch(
            'pipeline.evaluator.textstat.flesch_kincaid_grade', return_value=5.8,
        ), patch(
            'pipeline.live_llm.translate_to_spanish', return_value='Dé 5 mg.',
        ) as translate, patch(
            'pipeline.live_llm.back_translate_to_english', return_value='Give 5 mg.',
        ), patch(
            'pipeline.live_llm.judge_safety',
            return_value=SafetyJudgeResult(overall_verdict='PASS'),
        ):
            result = PipelineOrchestrator().generate_live(
                'Give 5 mg.', orders(), module_version='v1', condition='test'
            )

        self.assertEqual(simplify.call_count, 2)
        self.assertTrue(
            simplify.call_args_list[1].kwargs['previous_protection_failure']
        )
        self.assertEqual(result.simplified_en, 'Give 5 mg.')
        self.assertEqual(result.evaluation_metrics.protection_failures, [])
        translate.assert_called_once_with(unittest.mock.ANY, 'test', 'Give 5 mg.')

    def test_unmet_benchmark_returns_third_draft_with_failed_score(self):
        judge = SafetyJudgeResult(overall_verdict='PASS')
        with patch('pipeline.orchestrator.get_client',return_value=(object(),'test')), patch('pipeline.live_llm.simplify_to_plain_language',return_value='Too hard.') as simplify, patch('pipeline.evaluator.textstat.flesch_kincaid_grade',return_value=12.0), patch('pipeline.live_llm.translate_to_spanish', return_value='Muy difícil.') as translate, patch('pipeline.live_llm.back_translate_to_english', return_value='Too hard.'), patch('pipeline.live_llm.judge_safety', return_value=judge):
            packet = PipelineOrchestrator().generate_live(
                'Source.', orders(), module_version='v1', condition='test'
            )
        self.assertEqual(simplify.call_count,3)
        self.assertEqual(packet.simplified_en, 'Too hard.')
        self.assertEqual(packet.evaluation_metrics.fkgl_score, 12.0)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict,
                         'FLAGGED_FOR_REVIEW')
        translate.assert_called_once()

    def test_simplification_prompt_uses_information_preservation_rule(self):
        from pipeline.live_llm import _SIMPLIFY_SYSTEM_PROMPT
        self.assertIn(
            'Change the language, not the information. Preserve every instruction, fact, '
            'condition, exception, warning, and clinical value.',
            _SIMPLIFY_SYSTEM_PROMPT,
        )
        self.assertIn('one main idea per sentence', _SIMPLIFY_SYSTEM_PROMPT)
        self.assertIn('common, familiar words', _SIMPLIFY_SYSTEM_PROMPT)
        self.assertIn('Do not summarize', _SIMPLIFY_SYSTEM_PROMPT)

    def test_approval_blocks_out_of_range_readability(self):
        from app.review import approval_blockers
        for score in [4.9,7.0,float('nan')]:
            with self.subTest(score=score):
                p=InstructionPacket(packet_id='SYN-1',condition='test',clinical_orders=orders(),original_clinical_text='Source.',simplified_en='Text.',translated_es='Prueba.',back_translated_en='Text.',evaluation_metrics=EvaluationMetrics(fkgl_score=score,safety_judge=SafetyJudgeResult(overall_verdict='PASS')))
                self.assertTrue(approval_blockers(p,p.simplified_en,p.model_dump(mode='json'),True))

    def test_rephrased_warning_can_pass_at_benchmark_boundaries(self):
        from app.review import approval_blockers
        for score in (5.0, 6.9):
            packet = InstructionPacket(
                packet_id='SYN-WARNING', condition='test', clinical_orders=orders(),
                original_clinical_text='Call the clinic if pain persists.',
                simplified_en='If pain does not stop, call the clinic.',
                translated_es='Llame a la clínica si el dolor continúa.',
                back_translated_en='Call the clinic if pain continues.',
                evaluation_metrics=EvaluationMetrics(
                    fkgl_score=score, verbatim_match_percent=100,
                    safety_judge=SafetyJudgeResult(overall_verdict='PASS')),
            )
            self.assertEqual(approval_blockers(
                packet, packet.simplified_en, packet.model_dump(mode='json'), True), [])

    def test_ui_has_no_offline_mode_and_generation_calls_live_pipeline(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        from tests.test_ui_components import offline_app
        with offline_app(), patch(
            'pipeline.orchestrator.PipelineOrchestrator.generate_live',
            side_effect=RuntimeError('Synthetic live endpoint failure'),
        ) as live:
            app = AppTest.from_file(str(Path(__file__).parents[1] / 'app' / 'clinician_ui.py')).run()
            self.assertFalse(app.exception)
            for widget in list(app.radio) + list(app.selectbox):
                self.assertFalse(any('offline' in str(option).lower() for option in widget.options))
            next(button for button in app.button if 'Generate Simplified Instructions' in button.label).click().run()
            live.assert_called_once()
            self.assertTrue(any('Generation failed' in error.value for error in app.error))
