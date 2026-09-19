"""Phase 2 safety boundaries, using neutral synthetic text and fake providers."""
import json
import unittest

from pipeline.protection import SentinelProtector, ProtectionError
from pipeline.orchestrator import PipelineOrchestrator
from schemas.instruction_packet import ClinicalOrders, MedicationOrder, ProtocolTemplate


class FakeProvider:
    """External provider double; echoes protected neutral text, not clinical translation."""
    def __init__(self, failure=None, judge=None):
        self.calls = []
        self.failure = failure
        self.judge = judge

    def complete(self, system, content, *, json_output=False):
        self.calls.append((system, content))
        if self.failure:
            raise RuntimeError(self.failure)
        if json_output:
            return json.dumps(self.judge if self.judge is not None else {
                'overall_verdict': 'PASS', 'factual_drift_detected': False,
                'omitted_red_flags': [], 'contradictory_advice': [],
                'clinical_risk_score': 0.0, 'explanation': 'Synthetic test only.'})
        return content


def live_fixture():
    protocol = ProtocolTemplate(original_text='Example: $medication_0_dose. Red flag example.',
        plain_language_template='Example: $medication_0_dose. Red flag example.',
        vetted_by='Synthetic clinician', vetted_at='2026-09-17', required_red_flags=['Red flag example.'])
    orders = ClinicalOrders(patient_id='SYN-PED-001', diagnosis='Synthetic',
        medications=[MedicationOrder(name='Fixture', dose='5 mg')],
        urgent_fever_threshold='', emergency_fever_threshold='', emergency_phone='')
    return protocol, orders


class LivePipelineTests(unittest.TestCase):
    def test_altered_translation_blocks_judge_and_never_publishes_corrupt_text(self):
        class AlteredProvider(FakeProvider):
            def complete(self, system, content, **kwargs):
                return content + ' 10 mg'
        protocol, orders = live_fixture()
        judge = FakeProvider()
        packet = PipelineOrchestrator(llm1_client=AlteredProvider(), llm2_client=judge).generate_live(protocol, orders, module_version='v1', condition='demo')
        self.assertEqual(packet.translated_es, '')
        self.assertFalse(judge.calls)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')

    def test_judge_findings_override_inconsistent_pass_verdict(self):
        protocol, orders = live_fixture()
        result = {'overall_verdict': 'PASS', 'factual_drift_detected': False,
                  'omitted_red_flags': ['Synthetic omission'], 'contradictory_advice': [],
                  'clinical_risk_score': 0.0, 'explanation': 'Synthetic test.'}
        packet = PipelineOrchestrator(llm1_client=FakeProvider(), llm2_client=FakeProvider(judge=result)).generate_live(protocol, orders, module_version='v1', condition='demo')
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
        self.assertEqual(packet.status, 'PENDING')

    def test_judge_timeout_after_translation_retains_reviewable_outputs(self):
        class TimeoutJudge(FakeProvider):
            def complete(self, system, content, *, json_output=False):
                if json_output:
                    raise TimeoutError('SECRET_CANARY')
                return content
        protocol, orders = live_fixture()
        packet = PipelineOrchestrator(llm1_client=FakeProvider(), llm2_client=TimeoutJudge()).generate_live(protocol, orders, module_version='v1', condition='demo')
        self.assertTrue(packet.translated_es)
        self.assertTrue(packet.back_translated_en)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
        self.assertNotIn('SECRET_CANARY', packet.model_dump_json())

    def test_live_translation_judge_and_edit_revision_protect_values_and_history(self):
        first, second = FakeProvider(), FakeProvider()
        pipeline = PipelineOrchestrator(llm1_client=first, llm2_client=second)
        protocol, orders = live_fixture()
        packet = pipeline.generate_live(protocol, orders, module_version='v1', condition='demo')
        self.assertEqual(packet.simplified_en, 'Example: 5 mg. Red flag example.')
        self.assertEqual(packet.translated_es, packet.simplified_en)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'PASS')
        self.assertEqual(packet.status, 'PENDING')
        self.assertEqual(packet.source_mode, 'live')
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 2)
        for _, request in first.calls + second.calls:
            self.assertNotIn('5 mg', request)
            self.assertNotIn('Fixture', request)
            self.assertNotIn('SYN-PED-001', request)
        before = packet.model_dump()
        revision = pipeline.recheck_edits(packet, packet.simplified_en + ' Synthetic edit.')
        self.assertNotEqual(packet.packet_id, revision.packet_id)
        self.assertEqual(packet.model_dump(), before)
        self.assertTrue(revision.translated_es.endswith('Synthetic edit.'))
        self.assertEqual(revision.status, 'PENDING')
        self.assertIsNone(revision.clinician_notes)

    def test_missing_required_red_flag_blocks_calls_and_signoff(self):
        first, second = FakeProvider(), FakeProvider()
        protocol, orders = live_fixture()
        protocol.plain_language_template = 'Example: $medication_0_dose.'
        packet = PipelineOrchestrator(llm1_client=first, llm2_client=second).generate_live(protocol, orders, module_version='v1', condition='demo')
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
        self.assertEqual(packet.evaluation_metrics.safety_judge.omitted_red_flags, ['Red flag example.'])
        self.assertFalse(first.calls)

    def test_failed_or_malformed_judge_never_passes_and_does_not_crash(self):
        for provider in (FakeProvider(failure='SECRET_CANARY'), FakeProvider(judge={}),
                         FakeProvider(judge={'overall_verdict': 'PASS'})):
            with self.subTest(provider=provider):
                protocol, orders = live_fixture()
                packet = PipelineOrchestrator(llm1_client=FakeProvider(), llm2_client=provider).generate_live(protocol, orders, module_version='v1', condition='demo')
                self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, 'FLAGGED_FOR_REVIEW')
                self.assertNotIn('SECRET_CANARY', packet.model_dump_json())


class SentinelTests(unittest.TestCase):
    def test_units_and_numeric_schedules_are_masked_with_their_values(self):
        guard = SentinelProtector([])
        masked = guard.mask('Example: 12 hours; 2 tablets; 30 minutes; 8 mcg; 5 mL.')
        for unit in ('hours', 'tablets', 'minutes', 'mcg', 'mL'):
            self.assertNotIn(unit, masked)
        self.assertEqual(guard.restore_translation(masked, masked), 'Example: 12 hours; 2 tablets; 30 minutes; 8 mcg; 5 mL.')

    def test_masks_all_numbers_and_restores_exact_values_and_multiplicity(self):
        text = 'Example: 5 mg; 100.4°F; 202-555-0101; 5 mg; 12 hours; 0.5 mL.'
        guard = SentinelProtector(['5 mg', '100.4°F', '202-555-0101'])
        masked = guard.mask(text)
        self.assertFalse(any(c.isdigit() for c in masked))
        self.assertEqual(guard.restore_translation(masked, masked), text)
        for changed in (masked + ' 99 mg', masked.replace('@@CLEAR_A@@', '', 1), masked + ' @@CLEAR_UNKNOWN@@'):
            with self.subTest(changed=changed), self.assertRaises(ProtectionError):
                guard.restore_translation(changed, masked)

    def test_literal_sentinel_input_is_rejected(self):
        with self.assertRaises(ProtectionError):
            SentinelProtector([]).mask('Example @@CLEAR_A@@')


if __name__ == '__main__':
    unittest.main()
