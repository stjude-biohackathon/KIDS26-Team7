"""
Track C UI & Component Integration Tests.
Validates schemas, evaluation metrics, drift simulation, library persistence,
and PDF rendering for the Clinician Review Dashboard.
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from app.mock_components import (
    ClinicalOrders,
    EvaluationMetrics,
    InstructionPacket,
    MedicationOrder,
    SafetyJudgeResult,
    evaluate_text_verbatim_and_fkgl,
    extract_verbatim_tokens,
    generate_handout_pdf,
    get_physician_annotation,
    load_gold_records,
    run_mock_pipeline,
    save_to_gold_library,
)


@contextmanager
def offline_app(load_status=None, modules=None):
    """Run the Streamlit app without touching the network.

    Unit tests must stay hermetic: once live credentials resolve, the app would
    otherwise call the real GitHub App and the real models, making these
    structural assertions slow, flaky, and dependent on someone's secrets.
    """
    import streamlit as st

    from storage import github_loader

    mock_modules, mock_orders = github_loader.load_mock_templates_and_orders()
    status = load_status or {"source": "mock", "error": None, "warnings": []}

    def _unavailable(*_args, **_kwargs):
        raise RuntimeError("Live model call disabled in unit tests.")

    st.cache_data.clear()
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                github_loader,
                "fetch_remote_templates_and_orders",
                return_value=(mock_modules if modules is None else modules, mock_orders),
            )
        )
        stack.enter_context(
            patch.object(github_loader, "get_last_load_status", return_value=status)
        )
        stack.enter_context(
            patch(
                "pipeline.orchestrator.PipelineOrchestrator.generate_live",
                _unavailable,
            )
        )
        stack.enter_context(
            patch(
                "pipeline.orchestrator.PipelineOrchestrator.recheck_edits_live",
                _unavailable,
            )
        )
        yield
    st.cache_data.clear()


class TestTrackCComponents(unittest.TestCase):
    def setUp(self):
        self.orders = ClinicalOrders(
            order_id="ORD-SCD-01",
            order_version="v1.2.0",
            patient_id="SYN-PED-001",
            age="8 years old",
            diagnosis="Sickle Cell Disease with acute vaso-occlusive pain",
            medications=[
                MedicationOrder(
                    name="Ibuprofen oral suspension",
                    dose="200 mg",
                    route="oral",
                    frequency="every 6 hours as needed with food",
                ),
                MedicationOrder(
                    name="Oxycodone oral solution",
                    dose="5 mg",
                    route="oral",
                    frequency="every 4 hours as needed for severe pain",
                ),
            ],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
            emergency_phone="911",
        )

    def test_schema_instantiation(self):
        packet = InstructionPacket(
            packet_id="PKT-TEST001",
            condition="sickle_cell_pain",
            clinical_orders=self.orders,
            simplified_en="Sample text with 200 mg and 100.4°F.",
        )
        self.assertTrue(packet.packet_id.startswith("PKT-"))
        self.assertEqual(packet.status, "PENDING")
        self.assertEqual(packet.clinical_orders.patient_id, "SYN-PED-001")
        self.assertEqual(packet.clinical_orders.age, "8 years old")

    def test_physician_annotation_logic(self):
        p_pending = InstructionPacket(packet_id="P1", condition="c", clinical_orders=self.orders, status="PENDING")
        p_approved = InstructionPacket(packet_id="P2", condition="c", clinical_orders=self.orders, status="APPROVED")
        p_edited = InstructionPacket(packet_id="P3", condition="c", clinical_orders=self.orders, status="EDITED_AND_APPROVED")
        p_rejected = InstructionPacket(packet_id="P4", condition="c", clinical_orders=self.orders, status="REJECTED_DRIFT")

        self.assertEqual(get_physician_annotation(p_pending), "Pending physician review")
        self.assertEqual(get_physician_annotation(p_approved), "Approved by physician")
        self.assertEqual(get_physician_annotation(p_edited), "Edited and approved by physician")
        self.assertEqual(get_physician_annotation(p_rejected), "Rejected by physician")

    def test_verbatim_extraction_and_evaluation(self):
        tokens = extract_verbatim_tokens(self.orders)
        self.assertIn("200 mg", tokens)
        self.assertIn("5 mg", tokens)
        self.assertIn("100.4°F", tokens)
        self.assertIn("901-595-3300", tokens)

        # Test full match text
        full_text = (
            "Give Ibuprofen 200 mg every 6 hours and Oxycodone 5 mg if pain continues. "
            "Call clinic at 901-595-3300 if fever reaches 100.4°F or 101.0°F. Emergency: 911."
        )
        metrics = evaluate_text_verbatim_and_fkgl(full_text, self.orders)
        self.assertEqual(len(metrics.verbatim_mismatches), 0)
        self.assertEqual(metrics.verbatim_match_percent, 100.0)
        self.assertEqual(metrics.safety_judge.overall_verdict, "NEEDS_REVIEW")

        # Test missing dose mismatch
        missing_text = "Give medicine regularly. Call 901-595-3300 for fever 100.4°F. Emergency 911."
        mismatch_metrics = evaluate_text_verbatim_and_fkgl(missing_text, self.orders)
        self.assertIn("200 mg", mismatch_metrics.verbatim_mismatches)
        self.assertIn("5 mg", mismatch_metrics.verbatim_mismatches)
        self.assertEqual(mismatch_metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")

    def test_drift_simulator_injections(self):
        # Test Altered Medication Dose
        p_drift_dose = run_mock_pipeline(
            condition="sickle_cell_pain",
            module_version="v1.2.0",
            orders=self.orders,
            drift_mode="Altered Medication Dose",
        )
        self.assertTrue(p_drift_dose.evaluation_metrics.safety_judge.factual_drift_detected)
        self.assertEqual(p_drift_dose.evaluation_metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")
        self.assertIn("200 mg", p_drift_dose.evaluation_metrics.verbatim_mismatches)

        # Test Altered Fever Threshold
        p_drift_fever = run_mock_pipeline(
            condition="fever_neutropenia",
            module_version="v1.2.0",
            orders=self.orders,
            drift_mode="Altered Fever Threshold",
        )
        self.assertTrue(p_drift_fever.evaluation_metrics.safety_judge.factual_drift_detected)
        self.assertEqual(p_drift_fever.evaluation_metrics.safety_judge.overall_verdict, "FLAGGED_FOR_REVIEW")

    def test_mock_pipeline_generation(self):
        packet = run_mock_pipeline(
            condition="sickle_cell_pain",
            module_version="v1.2.0",
            orders=self.orders,
        )
        self.assertTrue(len(packet.simplified_en) > 50)
        self.assertTrue(len(packet.translated_es) > 50)
        self.assertTrue(len(packet.back_translated_en) > 50)
        self.assertEqual(packet.status, "PENDING")

    def test_gold_library_persistence(self):
        packet = run_mock_pipeline("sickle_cell_pain", "v1.2.0", self.orders)
        packet.status = "APPROVED"
        save_to_gold_library(packet)

        records = load_gold_records()
        self.assertTrue(len(records) > 0)
        saved = [r for r in records if r.packet_id == packet.packet_id]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].physician_decision, "Approved by physician")

    def test_bilingual_pdf_export(self):
        packet = run_mock_pipeline("sickle_cell_pain", "v1.2.0", self.orders)
        
        # Test Approved PDF
        packet.status = "APPROVED"
        pdf_approved = generate_handout_pdf(packet)
        self.assertTrue(isinstance(pdf_approved, bytes))
        self.assertTrue(len(pdf_approved) > 1000)
        self.assertTrue(pdf_approved.startswith(b"%PDF"))

        # Test Edited & Approved PDF
        packet.status = "EDITED_AND_APPROVED"
        packet.simplified_en = "Custom modified instructions by clinician."
        packet.edited_by_physician = True
        pdf_edited = generate_handout_pdf(packet)
        self.assertTrue(pdf_edited.startswith(b"%PDF"))

        # Test Rejected PDF
        packet.status = "REJECTED_DRIFT"
        packet.rejection_reason = "Unsafe dosage alteration"
        pdf_rejected = generate_handout_pdf(packet)
        self.assertTrue(pdf_rejected.startswith(b"%PDF"))

    def test_streamlit_app_headless_launch_and_generate(self):
        """Simulate Streamlit clinician review app execution and packet generation."""
        from streamlit.testing.v1 import AppTest

        with offline_app():
            at = AppTest.from_file("../app/clinician_ui.py")
            at.run()
            self.assertEqual(len(at.exception), 0, f"AppTest raised exceptions on launch: {at.exception}")

            # Click Generate Instructions
            gen_btn = None
            for b in at.button:
                if "Generate" in b.label:
                    gen_btn = b
                    break
            self.assertIsNotNone(gen_btn, "Generate Instructions button not found in sidebar")
            gen_btn.click().run()
            self.assertEqual(len(at.exception), 0, f"AppTest raised exceptions on generate: {at.exception}")

            # Verify 4-way comparative pane rendered
            markdown_texts = [m.value for m in at.markdown]
            self.assertTrue(any("1. Original Clinical Orders" in t for t in markdown_texts))
            self.assertTrue(any("2. Simplified English" in t for t in markdown_texts))
            self.assertTrue(any("3. Spanish Handout" in t for t in markdown_texts))
            self.assertTrue(any("4. Back-Translated English" in t for t in markdown_texts))

            # Verify action buttons exist
            button_labels = [b.label for b in at.button]
            self.assertTrue(any("Save & Check Edits" in l for l in button_labels))
            self.assertTrue(any("Approve & Publish" in l for l in button_labels))
            self.assertTrue(any("Reject & Log Drift" in l for l in button_labels))

            # Verify telemetry metrics for both FKGL and Verbatim score
            metric_labels = [m.label for m in at.metric]
            self.assertTrue(any("FKGL Readability" in l for l in metric_labels), f"FKGL metric not found in: {metric_labels}")
            self.assertTrue(any("Verbatim Score" in l for l in metric_labels), f"Verbatim metric not found in: {metric_labels}")

    def test_streamlit_app_inline_edit_and_approve(self):
        """Simulate Streamlit inline editing, re-checking, and approval gate."""
        from streamlit.testing.v1 import AppTest

        with offline_app():
            at = AppTest.from_file("../app/clinician_ui.py")
            at.run()
            for b in at.button:
                if "Generate" in b.label:
                    b.click().run()
                    break

            # Edit text in inline clinical editor
            txt_area = None
            for t in at.text_area:
                if t.key == "txt_clinician_en":
                    txt_area = t
                    break
            self.assertIsNotNone(txt_area, "Inline editor text area not found")
            txt_area.input("Updated clinician verified instructions: 200 mg and 100.4°F.").run()

            # Save & check edits
            for b in at.button:
                if "Save & Check Edits" in b.label:
                    b.click().run()
                    break
            self.assertEqual(len(at.exception), 0)

            # Verify telemetry metrics updated and present post-edit
            metric_labels_after_edit = [m.label for m in at.metric]
            self.assertTrue(any("Verbatim Score" in l for l in metric_labels_after_edit))
            self.assertTrue(any("FKGL Readability" in l for l in metric_labels_after_edit))

            # Approve & publish
            for b in at.button:
                if "Approve & Publish" in b.label:
                    b.click().run()
                    break
            self.assertEqual(len(at.exception), 0)


class TestLiveProvenanceReporting(unittest.TestCase):
    """specs/05 FIX-C1/FIX-C2: the UI must report real provenance, never assume it."""

    def setUp(self):
        # `_load_templates_and_orders` is @st.cache_data-wrapped, so results
        # (including load status) persist across AppTest runs in-process.
        import streamlit as st

        st.cache_data.clear()

    def _run_app(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("../app/clinician_ui.py")
        at.run()
        return at

    def _badge_markdown(self, at):
        return [
            m.value for m in at.markdown
            if "**Source:**" in m.value
        ]

    def test_badge_reports_live_source_when_load_succeeds(self):
        from unittest.mock import patch

        from storage import github_loader

        modules, orders = github_loader.load_mock_templates_and_orders()
        live_status = {"source": "github_app", "error": None, "warnings": []}
        with patch(
            "storage.github_loader.fetch_remote_templates_and_orders",
            return_value=(modules, orders),
        ):
            with patch(
                "storage.github_loader.get_last_load_status", return_value=live_status
            ):
                at = self._run_app()
        self.assertEqual(len(at.exception), 0, f"AppTest raised: {at.exception}")
        badges = self._badge_markdown(at)
        self.assertTrue(badges, "Data-source badge not rendered")
        self.assertIn("GitHub App (In-Memory, No Local Copy)", badges[0])

    def test_badge_reports_failed_live_load_instead_of_green_live_badge(self):
        from unittest.mock import patch

        from storage import github_loader

        modules, orders = github_loader.load_mock_templates_and_orders()
        failed_status = {
            "source": "mock",
            "error": "GitHub API request failed: ConnectionError.",
            "warnings": [],
        }
        with patch(
            "storage.github_loader.fetch_remote_templates_and_orders",
            return_value=(modules, orders),
        ):
            with patch(
                "storage.github_loader.get_last_load_status", return_value=failed_status
            ):
                with patch(
                    "storage.github_loader.is_github_app_configured", return_value=True
                ):
                    at = self._run_app()
        self.assertEqual(len(at.exception), 0, f"AppTest raised: {at.exception}")
        badges = self._badge_markdown(at)
        self.assertTrue(badges, "Data-source badge not rendered")
        # Credentials are present but the load failed: must NOT claim live.
        self.assertNotIn("GitHub App (In-Memory, No Local Copy)", badges[0])
        self.assertIn("live load failed", badges[0])
        captions = [c.value for c in at.caption]
        self.assertTrue(
            any("ConnectionError" in c for c in captions),
            f"Failure reason not surfaced in captions: {captions}",
        )

    def test_upstream_data_quality_warnings_are_surfaced(self):
        from unittest.mock import patch

        from storage import github_loader

        modules, orders = github_loader.load_mock_templates_and_orders()
        warned_status = {
            "source": "github_app",
            "error": None,
            "warnings": ["modules: upstream JSON contained trailing comma(s)"],
        }
        with patch(
            "storage.github_loader.fetch_remote_templates_and_orders",
            return_value=(modules, orders),
        ):
            with patch(
                "storage.github_loader.get_last_load_status", return_value=warned_status
            ):
                at = self._run_app()
        captions = [c.value for c in at.caption]
        self.assertTrue(
            any("trailing comma" in c for c in captions),
            f"Upstream warning not surfaced: {captions}",
        )

    def test_empty_live_template_raises_data_notice(self):
        from unittest.mock import patch

        from storage import github_loader

        _, orders = github_loader.load_mock_templates_and_orders()
        # Live load "succeeded" but yields no template for the selected module.
        empty_modules = {"sickle_cell_pain": {}}
        live_status = {"source": "github_app", "error": None, "warnings": []}
        with patch(
            "storage.github_loader.fetch_remote_templates_and_orders",
            return_value=(empty_modules, orders),
        ):
            with patch(
                "storage.github_loader.get_last_load_status", return_value=live_status
            ):
                with patch(
                    "pipeline.orchestrator.PipelineOrchestrator.generate_live",
                    side_effect=RuntimeError("Live model call disabled in unit tests."),
                ):
                    at = self._run_app()
                    for b in at.button:
                        if "Generate" in b.label:
                            b.click().run()
                            break
        self.assertEqual(len(at.exception), 0, f"AppTest raised: {at.exception}")
        self.assertTrue(
            at.session_state["live_data_notice"],
            "Empty live template must set the data-outage notice, not silently use mocks.",
        )
        warnings = [w.value for w in at.warning]
        self.assertTrue(
            any("Live clinical data unavailable" in w for w in warnings),
            f"Data-outage banner not shown: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()
