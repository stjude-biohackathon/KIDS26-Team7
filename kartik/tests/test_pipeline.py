"""Scaffold availability checks, not clinical safety acceptance tests."""

from pathlib import Path
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.orchestrator import PipelineOrchestrator
from pipeline.evaluator import evaluate_text


class PipelineScaffoldTests(unittest.TestCase):
    def test_generation_cannot_return_an_unchecked_packet_before_sync(self):
        source = "SYNTHETIC_INPUT_CANARY"
        # An opaque input deliberately avoids inventing Track B's schema.
        orders = object()

        with self.assertRaises(NotImplementedError) as raised:
            PipelineOrchestrator().generate(
                source, orders, module_version="v0-scaffold"
            )

        self.assertIn("Sync Point 0", str(raised.exception))
        self.assertNotIn(source, str(raised.exception))

    def test_edit_recheck_cannot_report_success_before_sync(self):
        edited_en = "SYNTHETIC_EDIT_CANARY"
        packet = object()

        with self.assertRaises(NotImplementedError) as raised:
            PipelineOrchestrator().recheck_edits(packet, edited_en)

        self.assertIn("Sync Point 0", str(raised.exception))
        self.assertNotIn(edited_en, str(raised.exception))

    def test_evaluation_cannot_return_uncomputed_safety_metrics_before_sync(self):
        text = "SYNTHETIC_EVALUATION_CANARY"
        orders = object()

        with self.assertRaises(NotImplementedError) as raised:
            evaluate_text(text, orders)

        self.assertIn("Sync Point 0", str(raised.exception))
        self.assertNotIn(text, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
