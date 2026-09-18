"""Phase 1 offline contracts; synthetic examples do not certify clinical safety."""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.orchestrator import PipelineOrchestrator
from pipeline.evaluator import check_verbatim, evaluate_text, extract_verbatim_tokens
from schemas.instruction_packet import ClinicalOrders, MedicationOrder


def synthetic_orders(**changes):
    """Small in-memory fixtures; no patient records or fixture files are needed."""
    values = dict(
        patient_id="SYN-PED-001", diagnosis="Synthetic example", medications=[],
        urgent_fever_threshold="", emergency_fever_threshold="",
        daytime_phone="", after_hours_phone="", emergency_phone="",
        order_id="ORDER-TEST", order_version="v1.2.0",
    )
    values.update(changes)
    return ClinicalOrders(**values)


class MockPipelineTests(unittest.TestCase):
    def test_generation_binds_values_without_rewriting_or_mutating_the_source(self):
        source = "The amount in this example is $medication_0_dose."
        orders = synthetic_orders(medications=[MedicationOrder(name="Synthetic", dose="5 mg")])
        before = orders.model_dump()
        pipeline = PipelineOrchestrator()
        first = pipeline.generate(source, orders, module_version="v2.0.0", condition="demo")
        second = pipeline.generate(source, orders, module_version="v2.0.0", condition="demo")

        self.assertEqual(first.original_clinical_text, source)
        self.assertEqual(first.simplified_en, "The amount in this example is 5 mg.")
        self.assertEqual(first.simplified_en, second.simplified_en)
        self.assertNotEqual(first.packet_id, second.packet_id)
        self.assertEqual((first.module_version, first.order_version), ("v2.0.0", "v1.2.0"))
        self.assertEqual(first.condition, "demo")
        self.assertEqual(first.status, "PENDING")
        self.assertIsNone(first.physician_decision)
        self.assertEqual(first.evaluation_metrics.verbatim_matches, ["5 mg"])
        self.assertEqual(orders.model_dump(), before)
        # Mutating the loader's order object later must not change this packet.
        orders.medications[0].dose = "15 mg"
        self.assertEqual(first.clinical_orders.medications[0].dose, "5 mg")

    def test_four_panes_use_supplied_templates_and_exact_order_values(self):
        orders = synthetic_orders(
            medications=[MedicationOrder(name="Demo", dose="5 mg", frequency="demo frequency")],
            urgent_fever_threshold="100.4°F", emergency_phone="911",
        )
        source = "Synthetic reference; no paraphrasing is allowed."
        en = "Example: ${medication_0_name}; $medication_0_dose; $medication_0_frequency; $urgent_fever_threshold; $emergency_phone."
        es = "Ejemplo: $medication_0_dose; $urgent_fever_threshold; $emergency_phone."
        back = "Back-translation example: $medication_0_dose; $urgent_fever_threshold; $emergency_phone."
        packet = PipelineOrchestrator().generate(
            source, orders, module_version="v1.0.0", condition="demo",
            simplified_template_text=en, spanish_template_text=es,
            back_translation_template_text=back,
        )
        self.assertEqual(packet.original_clinical_text, source)
        self.assertEqual(packet.simplified_en, "Example: Demo; 5 mg; demo frequency; 100.4°F; 911.")
        self.assertEqual(packet.translated_es, "Ejemplo: 5 mg; 100.4°F; 911.")
        self.assertEqual(packet.back_translated_en, "Back-translation example: 5 mg; 100.4°F; 911.")
        self.assertEqual(packet.evaluation_metrics.verbatim_match_percent, 100.0)
        self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, "NEEDS_REVIEW")
        self.assertEqual(packet.status, "PENDING")

    def test_invalid_templates_fail_without_echoing_input(self):
        for template in ("$PRIVATE_CANARY", "${PRIVATE_CANARY", "", " \n "):
            with self.subTest(template=template):
                with self.assertRaises(ValueError) as raised:
                    PipelineOrchestrator().generate(
                        template, synthetic_orders(), module_version="v1", condition="demo"
                    )
                self.assertNotIn("PRIVATE_CANARY", str(raised.exception))

    def test_inserted_values_are_not_interpreted_as_more_template_code(self):
        orders = synthetic_orders(medications=[MedicationOrder(name="Demo $literal", dose="5 mg")])
        packet = PipelineOrchestrator().generate(
            "Example: $medication_0_name; $medication_0_dose. $$5 is a literal dollar example.",
            orders, module_version="v1", condition="demo",
        )
        self.assertEqual(packet.simplified_en, "Example: Demo $literal; 5 mg. $5 is a literal dollar example.")

    def test_source_and_version_metadata_cannot_be_missing(self):
        for field in ("source", "module_version", "order_version", "condition"):
            with self.subTest(field=field):
                values = dict(source="Synthetic reference.", module_version="v1", order_version="v1", condition="demo")
                values[field] = " "
                with self.assertRaises(ValueError):
                    PipelineOrchestrator().generate(
                        values["source"], synthetic_orders(order_version=values["order_version"]),
                        module_version=values["module_version"], condition=values["condition"],
                        simplified_template_text="The cat sat on the mat.",
                    )

    def test_missing_bilingual_fixtures_are_explicitly_unavailable(self):
        packet = PipelineOrchestrator().generate(
            "The cat sat on the mat.", synthetic_orders(), module_version="v1", condition="demo"
        )
        self.assertEqual(packet.translated_es, "")
        self.assertEqual(packet.back_translated_en, "")
        self.assertIn("Spanish mock unavailable", packet.evaluation_metrics.safety_judge.explanation)
        self.assertIn("Back-translation mock unavailable", packet.evaluation_metrics.safety_judge.explanation)

    def test_bilingual_value_mismatches_flag_the_packet(self):
        orders = synthetic_orders(medications=[MedicationOrder(name="Demo", dose="5 mg")])
        for pane in ("spanish_template_text", "back_translation_template_text"):
            with self.subTest(pane=pane):
                templates = dict(spanish_template_text="Ejemplo: 5 mg.", back_translation_template_text="Example: 5 mg.")
                templates[pane] = "Example: 15 mg."
                packet = PipelineOrchestrator().generate(
                    "Example: 5 mg.", orders, module_version="v1", condition="demo", **templates
                )
                # FKGL and verbatim telemetry describe the English pane only.
                self.assertEqual(packet.evaluation_metrics.verbatim_match_percent, 100.0)
                self.assertEqual(packet.evaluation_metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")
                self.assertIn("verbatim mismatch", packet.evaluation_metrics.safety_judge.explanation)
                self.assertEqual(packet.status, "PENDING")

    def test_edit_recheck_creates_a_pending_revision_and_preserves_the_old_packet(self):
        pipeline = PipelineOrchestrator()
        orders = synthetic_orders(medications=[MedicationOrder(name="Demo", dose="5 mg")])
        packet = pipeline.generate(
            "Example: $medication_0_dose.", orders, module_version="v1", condition="demo",
            spanish_template_text="Ejemplo: 5 mg.", back_translation_template_text="Example: 5 mg.",
        )
        packet.status = "APPROVED"
        packet.physician_decision = "Approve & publish"
        packet.clinician_notes = "Previous review only."
        packet.reviewed_at = "2026-01-01T00:00:00+00:00"
        packet.created_at = "2026-01-01T00:00:00+00:00"
        before = packet.model_dump()

        revision = pipeline.recheck_edits(packet, "This changed example says 15 mg.")

        self.assertEqual(packet.model_dump(), before)
        self.assertNotEqual(revision.packet_id, packet.packet_id)
        self.assertNotEqual(revision.created_at, packet.created_at)
        self.assertEqual(revision.original_clinical_text, packet.original_clinical_text)
        self.assertEqual(revision.clinical_orders, packet.clinical_orders)
        self.assertEqual(revision.module_version, packet.module_version)
        self.assertEqual(revision.order_version, packet.order_version)
        self.assertEqual(revision.simplified_en, "This changed example says 15 mg.")
        self.assertEqual(revision.status, "PENDING")
        self.assertTrue(revision.edited_by_physician)
        self.assertIsNone(revision.physician_decision)
        self.assertIsNone(revision.reviewed_at)
        self.assertIsNone(revision.clinician_notes)
        self.assertEqual(revision.translated_es, "")
        self.assertEqual(revision.back_translated_en, "")
        self.assertEqual(revision.evaluation_metrics.verbatim_mismatches, ["5 mg"])
        self.assertNotEqual(revision.evaluation_metrics.fkgl_score, packet.evaluation_metrics.fkgl_score)
        self.assertEqual(revision.evaluation_metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")
        revision.clinical_orders.medications[0].dose = "20 mg"
        self.assertEqual(packet.clinical_orders.medications[0].dose, "5 mg")

    def test_rechecking_a_rejected_packet_clears_the_previous_rejection(self):
        pipeline = PipelineOrchestrator()
        packet = pipeline.generate("The cat sat on the mat.", synthetic_orders(), module_version="v1", condition="demo")
        packet.status = "REJECTED_DRIFT"
        packet.physician_decision = "Reject & log drift"
        packet.rejection_reason = "Previous wording was rejected."
        packet.rejection_category = "Contradictory Advice"
        before = packet.model_dump()

        revision = pipeline.recheck_edits(packet, "The dog sat on the mat.")

        self.assertEqual(packet.model_dump(), before)
        self.assertEqual(revision.status, "PENDING")
        self.assertIsNone(revision.rejection_reason)
        self.assertIsNone(revision.rejection_category)
        self.assertIsNone(revision.physician_decision)

    def test_failed_edit_recheck_also_leaves_the_original_unchanged(self):
        pipeline = PipelineOrchestrator()
        packet = pipeline.generate("The cat sat on the mat.", synthetic_orders(), module_version="v1", condition="demo")
        before = packet.model_dump()
        with self.assertRaises(ValueError):
            pipeline.recheck_edits(packet, " \n ")
        self.assertEqual(packet.model_dump(), before)


class LivePipelineTests(unittest.TestCase):
    """Exercise the real pipeline against synthetic model transport responses."""
    def setUp(self):
        # Gate routing is tested at a fixed passing score; real FKGL arithmetic
        # and bounded retry behavior have independent regression coverage.
        scoring = patch('pipeline.evaluator.textstat.flesch_kincaid_grade', return_value=5.8)
        scoring.start()
        self.addCleanup(scoring.stop)

    def clients(self, judge_response=None, drop_translation=False):
        llm1, llm2 = MagicMock(), MagicMock()
        def forward(**kwargs):
            content = kwargs['messages'][1]['content']
            self.assertNotIn('5 mg', content)
            text = 'Dropped protected value.' if drop_translation else (
                content.replace('Administer', 'Give') if 'Simplify the supplied' in kwargs['messages'][0]['content'] else 'ES: ' + content
            )
            return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])
        def back_or_judge(**kwargs):
            content = kwargs['messages'][1]['content']
            self.assertNotIn('5 mg', content)
            if 'safety auditor' in kwargs['messages'][0]['content']:
                text = judge_response or '{"overall_verdict":"PASS","factual_drift_detected":false,"omitted_red_flags":[],"contradictory_advice":[],"clinical_risk_score":0,"explanation":"Synthetic audit"}'
            else:
                text = content.removeprefix('ES: ')
            return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])
        llm1.chat.completions.create.side_effect = forward
        llm2.chat.completions.create.side_effect = back_or_judge
        return llm1, llm2, patch('pipeline.orchestrator.get_client', side_effect=lambda alias: (llm1 if alias=='gpt52' else llm2,'synthetic'))

    def test_live_pipeline_simplifies_english_and_routes_both_models(self):
        orders=synthetic_orders(medications=[MedicationOrder(name='Demo',dose='5 mg')])
        first,second,context=self.clients()
        with context:
            result=PipelineOrchestrator().generate_live('Administer 5 mg orally daily.',orders,module_version='v1',condition='demo')
        self.assertEqual(result.simplified_en,'Give 5 mg orally daily.')
        self.assertEqual(result.translated_es,'ES: Give 5 mg orally daily.')
        self.assertEqual(result.back_translated_en,result.simplified_en)
        self.assertEqual(result.evaluation_metrics.safety_judge.overall_verdict,'PASS')
        self.assertEqual(first.chat.completions.create.call_count,2)
        self.assertEqual(second.chat.completions.create.call_count,2)
        self.assertEqual(result.status,'PENDING')

    def test_changed_dose_in_clinician_edit_cannot_be_waived_by_judge(self):
        orders=synthetic_orders(medications=[MedicationOrder(name='Demo',dose='5 mg')])
        pipeline=PipelineOrchestrator()
        packet=pipeline.generate('Give 5 mg.',orders,module_version='v1',condition='demo')
        _,_,context=self.clients()
        with context:
            revision=pipeline.recheck_edits_live(packet,'Give 15 mg.')
        self.assertEqual(revision.evaluation_metrics.safety_judge.overall_verdict,'FLAGGED_FOR_REVIEW')
        self.assertIn('5 mg',revision.evaluation_metrics.verbatim_mismatches)
        self.assertEqual(packet.simplified_en,'Give 5 mg.')

    def test_lost_translation_value_fails_before_a_packet_can_be_published(self):
        orders=synthetic_orders(medications=[MedicationOrder(name='Demo',dose='5 mg')])
        _,_,context=self.clients(drop_translation=True)
        with context, self.assertRaises(ValueError):
            PipelineOrchestrator().generate_live('Give 5 mg.',orders,module_version='v1',condition='demo')

    def test_judge_failure_flags_without_crashing_workflow(self):
        orders=synthetic_orders(medications=[MedicationOrder(name='Demo',dose='5 mg')])
        _,_,context=self.clients(judge_response='not valid json')
        with context:
            result=PipelineOrchestrator().generate_live('Give 5 mg.',orders,module_version='v1',condition='demo')
        self.assertEqual(result.evaluation_metrics.safety_judge.overall_verdict,'FLAGGED_FOR_REVIEW')

    def test_successful_recheck_is_a_new_revision(self):
        orders=synthetic_orders(medications=[MedicationOrder(name='Demo',dose='5 mg')])
        pipeline=PipelineOrchestrator()
        packet=pipeline.generate('Give 5 mg.',orders,module_version='v1',condition='demo')
        before=packet.model_dump()
        _,_,context=self.clients()
        with context:
            revision=pipeline.recheck_edits_live(packet,'Updated instructions: give 5 mg.')
        self.assertEqual(packet.model_dump(),before)
        self.assertEqual(revision.parent_packet_id,packet.packet_id)
        self.assertNotEqual(revision.packet_id,packet.packet_id)
        self.assertEqual(revision.translated_es,'ES: Updated instructions: give 5 mg.')
        self.assertEqual(revision.status,'PENDING')
        self.assertIsNone(revision.reviewed_at)

    def test_blank_edits_fail_before_model_calls(self):
        pipeline=PipelineOrchestrator()
        packet=pipeline.generate('Test.',synthetic_orders(),module_version='v1',condition='demo')
        with patch('pipeline.orchestrator.get_client') as client, self.assertRaises(ValueError):
            pipeline.recheck_edits_live(packet,' ')
        client.assert_not_called()


class EvaluationTests(unittest.TestCase):
    def test_readability_uses_the_fkgl_formula_without_rewriting_text(self):
        # Six one-syllable words in one sentence:
        # 0.39 * 6 + 11.8 * 1 - 15.59 = -1.45.
        metrics = evaluate_text("The cat sat on the mat.", synthetic_orders())

        self.assertAlmostEqual(metrics.fkgl_score, -1.45, places=2)
        self.assertEqual(metrics.safety_judge.overall_verdict, "NEEDS_REVIEW")
        self.assertIn("Mock", metrics.safety_judge.explanation)

    def test_exact_values_are_reported_once_and_missing_values_are_flagged(self):
        orders = synthetic_orders(
            medications=[MedicationOrder(name="Synthetic medicine", dose="5 mg")],
            urgent_fever_threshold="100.4°F", emergency_fever_threshold="101.0°F",
            daytime_phone="202-555-0100", after_hours_phone="202-555-0100",
            emergency_phone="911",
        )
        metrics = evaluate_text("Example: 5 mg; 100.4°F; 202-555-0100; 911.", orders)

        self.assertEqual(metrics.verbatim_matches, ["5 mg", "100.4°F", "202-555-0100", "911"])
        self.assertEqual(metrics.verbatim_mismatches, ["101.0°F"])
        self.assertEqual(metrics.verbatim_match_percent, 80.0)
        self.assertEqual(metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")

    def test_changed_numbers_units_and_phone_formats_do_not_pass_as_substrings(self):
        cases = [
            ("dose", "5 mg", "15 mg"), ("dose", "5 mg", "0.5 mg"),
            ("dose", "5 mg", "-5 mg"), ("dose", "5 mg", "−5 mg"),
            ("dose", "200 mg", "1,200 mg"), ("dose", "5 mg", "5 mg/kg"),
            ("dose", "5 mg", "1/5 mg"), ("dose", "5 mg", "5 mg / kg"),
            ("dose", "5 mL", "5 ml"), ("dose", "5 mg", "5  mg"),
            ("temp", "100.4°F", "100.4F"), ("temp", "100.4°F", "100x4°F"),
            ("temp", "100.4°F", "1100.4°F"),
            ("phone", "202-555-0100", "202.555.0100"),
            ("phone", "202-555-0100", "+1-202-555-0100"),
            ("phone", "911", "1911"), ("phone", "911", "9110"),
        ]
        for kind, expected, changed in cases:
            with self.subTest(expected=expected, changed=changed):
                changes = {
                    "dose": dict(medications=[MedicationOrder(name="Synthetic", dose=expected)]),
                    "temp": dict(urgent_fever_threshold=expected),
                    "phone": dict(emergency_phone=expected),
                }[kind]
                orders = synthetic_orders(**changes)
                good = evaluate_text(f"Example: ({expected}).", orders)
                self.assertEqual(good.verbatim_matches, [expected])
                bad = evaluate_text(f"Example: {changed}.", orders)
                self.assertEqual(bad.verbatim_mismatches, [expected])
                self.assertEqual(bad.verbatim_match_percent, 0.0)

    def test_unavailable_readability_never_returns_an_invented_score(self):
        # textstat is an external dependency. A failure must not look like grade 5.6.
        for result in (float("nan"), float("inf"), RuntimeError("PRIVATE_CANARY")):
            with self.subTest(result=type(result).__name__):
                settings = ({"side_effect": result} if isinstance(result, Exception)
                            else {"return_value": result})
                with patch("pipeline.evaluator.textstat.flesch_kincaid_grade", **settings):
                    with self.assertRaises(ValueError) as raised:
                        evaluate_text("An example sentence.", synthetic_orders())
                self.assertNotIn("PRIVATE_CANARY", str(raised.exception))

    def test_empty_text_cannot_be_evaluated_as_a_valid_instruction(self):
        for text in ("", " \n\t "):
            with self.subTest(text=text), self.assertRaises(ValueError):
                evaluate_text(text, synthetic_orders())

    def test_readability_target_and_outer_review_bounds_are_distinct(self):
        # The spec names both a target (5.0–6.9) and wider flag bounds (4.0–7.0).
        for score, target_met, review_flag in (
            (3.9, False, True), (4.0, False, False), (5.0, True, False),
            (6.9, True, False), (7.0, False, False), (7.1, False, True),
        ):
            with self.subTest(score=score):
                with patch("pipeline.evaluator.textstat.flesch_kincaid_grade", return_value=score):
                    metrics = evaluate_text("An example sentence.", synthetic_orders())
                explanation = metrics.safety_judge.explanation
                self.assertIn("FKGL target " + ("met" if target_met else "not met"), explanation)
                self.assertEqual("outside review bounds" in explanation, review_flag)


if __name__ == "__main__":
    unittest.main()


class CompositeSafetyFieldExtractionTests(unittest.TestCase):
    """specs/05: upstream order fields carry descriptive text around the
    safety-critical value. Lock the extracted values, not the prose."""

    def _orders(self, **overrides):
        fields = dict(
            order_id="ORD-SC-01",
            order_version="v1.2.0",
            patient_id="SYN-PED-101",
            age="9 years",
            diagnosis="Sickle cell pain episode",
            medications=[],
            urgent_fever_threshold="100.4°F (38.0°C)",
            emergency_fever_threshold="101.0°F (38.3°C)",
            daytime_phone="555-0144 (Pediatric Hematology Day Clinic, M-F 8am-5pm)",
            after_hours_phone="555-0199 (24-hour on-call line)",
            emergency_phone="Call 911 or go to Children's Hospital Emergency Department",
        )
        fields.update(overrides)
        return ClinicalOrders(**fields)

    def test_descriptive_text_around_a_threshold_is_not_locked(self):
        tokens = extract_verbatim_tokens(self._orders())
        self.assertNotIn("100.4°F (38.0°C)", tokens)
        self.assertIn("100.4°F", tokens)

    def test_both_units_of_a_dual_unit_threshold_are_locked(self):
        tokens = extract_verbatim_tokens(self._orders())
        self.assertIn("100.4°F", tokens)
        self.assertIn("38.0°C", tokens)
        self.assertIn("101.0°F", tokens)
        self.assertIn("38.3°C", tokens)

    def test_clinic_name_and_hours_are_not_locked_but_the_number_is(self):
        tokens = extract_verbatim_tokens(self._orders())
        self.assertIn("555-0144", tokens)
        self.assertNotIn(
            "555-0144 (Pediatric Hematology Day Clinic, M-F 8am-5pm)", tokens
        )
        self.assertFalse(
            any("Hematology" in t for t in tokens),
            f"Descriptive prose leaked into verbatim locks: {tokens}",
        )

    def test_emergency_number_is_locked_without_the_surrounding_sentence(self):
        tokens = extract_verbatim_tokens(self._orders())
        self.assertIn("911", tokens)
        self.assertFalse(
            any("Children's Hospital" in t for t in tokens),
            f"Descriptive prose leaked into verbatim locks: {tokens}",
        )

    def test_medication_dose_is_extracted_from_a_composite_dose_string(self):
        orders = self._orders(
            medications=[
                MedicationOrder(
                    name="Ibuprofen",
                    dose="200 mg (10 mg/kg, max 600 mg)",
                    route="by mouth",
                    frequency="every 6 hours",
                )
            ]
        )
        tokens = extract_verbatim_tokens(orders)
        self.assertIn("200 mg", tokens)
        self.assertNotIn("200 mg (10 mg/kg, max 600 mg)", tokens)

    def test_plain_values_without_descriptive_text_are_unchanged(self):
        orders = self._orders(
            urgent_fever_threshold="100.4°F",
            daytime_phone="901-595-3300",
            emergency_phone="911",
            after_hours_phone="",
        )
        tokens = extract_verbatim_tokens(orders)
        self.assertIn("100.4°F", tokens)
        self.assertIn("901-595-3300", tokens)
        self.assertIn("911", tokens)

    def test_field_with_no_extractable_safety_value_is_not_locked_as_prose(self):
        orders = self._orders(
            emergency_phone="Go to the nearest emergency department",
        )
        tokens = extract_verbatim_tokens(orders)
        self.assertFalse(
            any("emergency department" in t.lower() for t in tokens),
            f"Unanchored prose must not be verbatim-locked: {tokens}",
        )

    def test_repeated_values_across_fields_are_reported_once(self):
        orders = self._orders(
            daytime_phone="555-0144 (day clinic)",
            after_hours_phone="555-0144 (after hours)",
        )
        tokens = extract_verbatim_tokens(orders)
        self.assertEqual(tokens.count("555-0144"), 1)

    def test_product_concentration_is_locked_as_one_value_not_fragments(self):
        """Upstream doses read "280 mg (14 mL of 100 mg/5 mL suspension)".

        Splitting the concentration into "100 mg" and "5 mL" creates tokens that
        can never match: check_verbatim deliberately refuses a dose followed by
        "/", so "100 mg" inside "100 mg/5 mL" would be a permanent mismatch.
        """
        orders = self._orders(
            medications=[
                MedicationOrder(
                    name="Ibuprofen",
                    dose="280 mg (14 mL of 100 mg/5 mL suspension)",
                    route="by mouth",
                    frequency="every 6 hours",
                )
            ]
        )
        tokens = extract_verbatim_tokens(orders)
        self.assertIn("280 mg", tokens)
        self.assertIn("14 mL", tokens)
        self.assertIn("100 mg/5 mL", tokens)
        self.assertNotIn("100 mg", tokens)
        self.assertNotIn("5 mL", tokens)

        text = (
            "Give 280 mg (14 mL) of ibuprofen by mouth every 6 hours. "
            "Use the 100 mg/5 mL suspension."
        )
        matches, _ = check_verbatim(text, orders)
        for dose_token in ("280 mg", "14 mL", "100 mg/5 mL"):
            self.assertIn(dose_token, matches)

    def test_live_style_text_passes_when_it_carries_the_extracted_values(self):
        orders = self._orders()
        text = (
            "Call the clinic at 555-0144 during the day or 555-0199 at night. "
            "Call if the fever reaches 100.4°F (38.0°C). "
            "Go to the emergency room if the fever reaches 101.0°F (38.3°C). "
            "For an emergency, call 911."
        )
        matches, mismatches = check_verbatim(text, orders)
        self.assertEqual(mismatches, [])
        self.assertIn("100.4°F", matches)
