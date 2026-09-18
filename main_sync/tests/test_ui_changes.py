"""Acceptance coverage for uichanges.md and optional Spanish review."""
import unittest
from html import escape
from pathlib import Path
from unittest.mock import patch
from tests.test_phase3 import phase3_app, click
from tests import test_phase3
from tests.test_simplification import orders
from pipeline.orchestrator import PipelineOrchestrator
from schemas.instruction_packet import ClinicalOrders, InstructionPacket, SafetyJudgeResult


class OptionalTranslationTests(unittest.TestCase):
    def test_english_generation_and_recheck_never_call_translation(self):
        with patch('pipeline.orchestrator.get_client', return_value=(object(), 'test')), patch('pipeline.live_llm.simplify_to_plain_language', return_value='Plain English.'), patch('pipeline.evaluator.textstat.flesch_kincaid_grade', return_value=5.8), patch('pipeline.live_llm.translate_to_spanish') as forward, patch('pipeline.live_llm.back_translate_to_english') as back, patch('pipeline.live_llm.judge_safety', return_value=SafetyJudgeResult(overall_verdict='PASS')) as judge:
            service = PipelineOrchestrator()
            original = service.generate_live('Source.', orders(), condition='test', module_version='v1', translate=False)
            revised = service.recheck_edits_live(original, 'Edited English.', translate=False)
        forward.assert_not_called(); back.assert_not_called()
        self.assertEqual(judge.call_count, 2)
        self.assertEqual(revised.parent_packet_id, original.packet_id)
        self.assertEqual(revised.translated_es, '')
        self.assertEqual(revised.evaluation_metrics.safety_judge.overall_verdict, 'PASS')

    def test_english_pdf_has_no_spanish_column_or_bilingual_claim(self):
        from exporters import pdf_generator
        from reportlab.platypus import Paragraph
        texts = []
        def capture(text, *args, **kwargs):
            texts.append(text)
            return Paragraph(text, *args, **kwargs)
        p = InstructionPacket(packet_id='SYN-EN', condition='test', clinical_orders=orders(), simplified_en='English instructions. ' * 1000, status='APPROVED')
        with patch.object(pdf_generator, 'Paragraph', side_effect=capture):
            pdf = pdf_generator.create_bilingual_pdf(p)
        self.assertTrue(pdf.startswith(b'%PDF'))
        combined = ' '.join(texts)
        self.assertNotIn('Bilingual', combined)
        self.assertNotIn('ESPAÑOL', combined)
        self.assertNotIn('Packet ID', combined)
        self.assertIn('English Handout', combined)

    def test_bilingual_pdf_orders_spanish_before_simplified_english(self):
        from exporters.pdf_generator import _ordered_language_sections
        packet = InstructionPacket(
            packet_id='SYN-BILINGUAL', condition='test', clinical_orders=orders(),
            simplified_en='Simplified English.', translated_es='Español.',
            status='APPROVED',
        )
        sections = _ordered_language_sections(packet)
        self.assertEqual([heading for heading, _ in sections], [
            'ESPAÑOL (Instrucciones para la Familia)', 'ENGLISH',
        ])
        self.assertEqual([text for _, text in sections], [
            'Español.', 'Simplified English.',
        ])


class UiChangesTests(unittest.TestCase):
    def app(self):
        return test_phase3.Phase3WorkflowTests().app()

    def test_english_only_publish_has_no_false_spanish_attestation(self):
        with phase3_app():
            at = self.app()
            self.assertTrue(any(
                'front-page-heading' in item.value and
                'Pediatric Discharge Instruction Review' in item.value and
                'Patient Name:</strong> John Doe' in item.value and
                'Sex:</strong> M' in item.value
                for item in at.markdown
            ))
            self.assertFalse(at.checkbox(key='chk_want_spanish').value)
            self.assertTrue(any(
                'clinical-box-full' in m.value and 'clinical-orders-preview' in m.value
                for m in at.markdown
            ))
            click(at, 'Generate Simplified Instructions')
            self.assertFalse(at.exception)
            self.assertFalse(at.session_state['current_packet'].translated_es)
            self.assertEqual([m.value for m in at.metric][:2], ['5.8', '100%'])
            self.assertFalse(any('Spanish Handout (LLM' in m.value for m in at.markdown))
            self.assertEqual(len(at.slider), 0)
            click(at, 'Approve & Publish')
            self.assertEqual(at.session_state['current_packet'].status, 'APPROVED')
            self.assertNotIn('attested to authorized Spanish', at.session_state['current_packet'].clinician_notes or '')

    def test_requested_sidebar_labels_connection_status_and_hidden_chrome(self):
        with phase3_app():
            at = self.app()
            self.assertEqual(at.checkbox(key='chk_want_spanish').label, 'Generate Spanish')
            labels = [item.label for item in at.text_input]
            self.assertIn('MRN:', labels)
            self.assertIn('Diagnosis:', labels)
            self.assertNotIn('Synthetic Patient ID:', labels)
            self.assertNotIn('Module:', labels)
            subheaders = [item.value for item in at.subheader]
            self.assertIn('2. GitHub App', subheaders)
            self.assertIn('3. Protocol & Module Version', subheaders)
            self.assertIn('4. Clinical Orders Customization', subheaders)
            self.assertIn('5. Scenario C Drift Simulator', subheaders)
            self.assertTrue(any('github-status' in item.value for item in at.markdown))
            self.assertFalse(any('LLM1 simplifies English' in item.value for item in at.caption))

        source = (Path(__file__).parents[1] / 'app' / 'clinician_ui.py').read_text()
        self.assertIn('[data-testid="stAppDeployButton"]', source)
        self.assertIn('resize: horizontal', source)
        self.assertIn('label_visibility="collapsed"', source)

    def test_new_front_page_layout_and_add_medication_control(self):
        with phase3_app():
            at = self.app()
            preview = next(
                item.value for item in at.markdown
                if "<div class='clinical-orders-preview'>" in item.value
            )
            self.assertIn('clinical-section-title', preview)
            self.assertIn('<strong>MRN</strong>', preview)
            self.assertIn('<strong>Hydration Strategy:</strong>', preview)
            self.assertNotIn('CLINICAL PROTOCOL:', preview)
            self.assertNotIn('===', preview)
            self.assertFalse(any('Active Protocol:' in item.value for item in at.info))

            initial_names = [item for item in at.text_input if item.label.startswith('Name #')]
            click(at, 'Add medication')
            added_names = [item for item in at.text_input if item.label.startswith('Name #')]
            self.assertEqual(len(added_names), len(initial_names) + 1)
            self.assertEqual(added_names[-1].value, '')

        source = (Path(__file__).parents[1] / 'app' / 'clinician_ui.py').read_text()
        self.assertIn('st.container(key="generation_controls")', source)
        self.assertIn('.st-key-generation_controls', source)
        self.assertIn('with st.spinner(', source)
        self.assertIn('[data-testid="stStatusWidget"]', source)
        self.assertNotIn('[data-testid="stSpinner"]', source)
        self.assertLess(
            source.index('generation_status = st.empty()'),
            source.index('if packet is None:'),
        )
        self.assertIn('_run_generation(want_spanish, generation_status)', source)
        self.assertLess(
            source.index('_compose_original_preview_html(base_order'),
            source.index('if generate_clicked:'),
        )

    def test_team7_instruction_is_the_original_source_before_and_after_generation(self):
        from tests.test_ui_components import offline_app

        statement = (
            "Call your child's oncology/hematology team right away - any time of day or night - "
            "for a temperature of 100.4°F (38.0°C) or higher that lasts more than an hour, "
            "or a single reading of 101°F (38.3°C) or higher. Do not wait to see if it "
            "comes down on its own."
        )
        modules = {"fever_neutropenia": {"team7-current": statement}}
        source_orders = {
            "fever_neutropenia": ClinicalOrders(
                patient_id="SYN-TEAM7",
                diagnosis="Fever and Neutropenia",
                order_id="ORD-TEAM7",
                order_version="team7-current",
                urgent_fever_threshold="100.4°F (38.0°C)",
                emergency_fever_threshold="",
                emergency_phone="",
            )
        }

        with offline_app(modules=modules, orders=source_orders):
            at = self.app()
            preview = next(
                item.value for item in at.markdown
                if "<div class='clinical-orders-preview'>" in item.value
            )
            self.assertIn(escape(statement), preview)
            click(at, 'Generate Simplified Instructions')
            self.assertEqual(
                at.session_state['current_packet'].original_clinical_text,
                statement,
            )
            self.assertTrue(any(escape(statement) in item.value for item in at.markdown))

    def test_sidebar_edit_is_an_override_and_does_not_replace_team7_source(self):
        from tests.test_ui_components import offline_app

        modules = {
            "fever_neutropenia": {
                "v1.2.0": "Call the care team for the fever values in the order."
            }
        }
        source_orders = {
            "fever_neutropenia": ClinicalOrders(
                patient_id="SYN-OVERRIDE",
                diagnosis="Fever and Neutropenia",
                order_id="ORD-OVERRIDE",
                order_version="v1.2.0",
                urgent_fever_threshold="100.4°F (38.0°C)",
                emergency_fever_threshold="101°F (38.3°C)",
                emergency_phone="911",
            )
        }

        with offline_app(modules=modules, orders=source_orders):
            at = self.app()
            next(item for item in at.text_input if item.label == "Urgent Fever:").input(
                "100.5°F (38.1°C)"
            ).run()

            preview = next(
                item.value for item in at.markdown
                if "<div class='clinical-orders-preview'>" in item.value
            )
            self.assertIn("Physician overrides applied", preview)
            self.assertIn("100.4°F (38.0°C)", preview)
            self.assertNotIn("100.5°F (38.1°C)", preview)

            click(at, "Generate Simplified Instructions")
            packet = at.session_state["current_packet"]
            self.assertEqual(
                packet.source_clinical_orders.urgent_fever_threshold,
                "100.4°F (38.0°C)",
            )
            self.assertEqual(
                packet.clinical_orders.urgent_fever_threshold,
                "100.5°F (38.1°C)",
            )
            reviewed_preview = next(
                item.value for item in at.markdown
                if "<div class='clinical-orders-preview'>" in item.value
            )
            self.assertIn("Physician overrides applied", reviewed_preview)
            self.assertIn("100.4°F (38.0°C)", reviewed_preview)
            self.assertNotIn("100.5°F (38.1°C)", reviewed_preview)

    def test_non_github_source_is_blocked_even_without_error_detail(self):
        from tests.test_ui_components import offline_app

        with offline_app(load_status={
            "source": "mock", "error": None, "warnings": []
        }):
            at = self.app()

        self.assertFalse(any(
            button.label == "Generate Simplified Instructions" for button in at.button
        ))
        self.assertTrue(any("Team7" in item.value for item in at.error))

    def test_library_table_stays_concise(self):
        with phase3_app():
            at = self.app()
            click(at, 'Generate Simplified Instructions')
            click(at, 'Approve & Publish')
            self.assertTrue(at.dataframe)
            self.assertEqual(
                list(at.dataframe[0].value.columns),
                ['Module', 'Status', 'Physician Decision', 'Timestamp'],
            )

    def test_order_change_discards_stale_review(self):
        with phase3_app():
            at = self.app(); click(at, 'Generate Simplified Instructions')
            next(t for t in at.text_input if t.label == 'Patient Age:').input('10 years old').run()
            self.assertIsNone(at.session_state['current_packet'])
            self.assertIsNone(at.session_state['checked_packet'])
            self.assertTrue(any('10 years old' in m.value for m in at.markdown))

    def test_spanish_opt_in_renders_translation_review_and_publishes_on_approval(self):
        with phase3_app():
            at = self.app(); at.checkbox(key='chk_want_spanish').check().run()
            click(at, 'Generate Simplified Instructions')
            self.assertFalse(at.exception)
            self.assertTrue(any('Back-Translated English (LLM' in m.value for m in at.markdown))
            self.assertEqual(len(at.slider), 0)
            # Approving is itself the Spanish attestation; no separate checkbox.
            self.assertEqual(len(at.checkbox), 0)
            self.assertTrue(any('Approving attests' in c.value for c in at.caption))
            click(at, 'Approve & Publish')
            self.assertEqual(at.session_state['current_packet'].status, 'APPROVED')
            self.assertIn('Spanish', at.session_state['current_packet'].clinician_notes)

    def test_failed_readability_and_judge_still_show_simplified_draft(self):
        from schemas.instruction_packet import EvaluationMetrics, SafetyJudgeResult
        from unittest.mock import patch
        packet = test_phase3.packet()
        packet.simplified_en = 'A difficult synthetic draft remains visible.'
        packet.translated_es = packet.back_translated_en = ''
        packet.evaluation_metrics = EvaluationMetrics(
            fkgl_score=11.4,
            safety_judge=SafetyJudgeResult(
                overall_verdict='FLAGGED_FOR_REVIEW',
                explanation='A source instruction may be missing.',
                failure_category='INVALID_SCHEMA',
            ),
        )
        with phase3_app(), patch(
            'pipeline.orchestrator.PipelineOrchestrator.generate_live',
            return_value=packet,
        ):
            at = self.app()
            click(at, 'Generate Simplified Instructions')
            self.assertFalse(at.exception)
            self.assertEqual(
                at.text_area(key='txt_clinician_en').value,
                packet.simplified_en,
            )
            notices = [item.value for item in at.error]
            cautions = [item.value for item in at.warning]
            # Readability misses are yellow; safety failures stay red.
            self.assertTrue(any('readability' in item.lower() for item in cautions))
            self.assertFalse(any('readability' in item.lower() for item in notices))
            self.assertTrue(any('safety review' in item.lower() for item in notices))
            judge_metric = next(item for item in at.metric if item.label == 'Judge Review')
            self.assertEqual(judge_metric.delta, 'Invalid Schema')
            click(at, 'Approve & Publish')
            self.assertEqual(at.session_state['current_packet'].status, 'PENDING')
