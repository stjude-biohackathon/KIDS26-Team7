"""Phase 0 model-selection tests; live credential resolution comes in Phase 2."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.orchestrator import PipelineOrchestrator


class ModelSelectionTests(unittest.TestCase):
    def test_each_documented_model_can_be_selected_offline_for_either_role(self):
        # Literal choices come from the Track A/C specs, not implementation.
        choices = (
            "gpt52", "gpt4o", "gpt56luna", "kimik3", "copus5", "local1", "local2"
        )
        with patch.dict(os.environ, {}, clear=True):
            for llm1_model in choices:
                for llm2_model in choices:
                    with self.subTest(llm1=llm1_model, llm2=llm2_model):
                        pipeline = PipelineOrchestrator(
                            llm1_model=llm1_model, llm2_model=llm2_model
                        )
                        self.assertEqual(
                            (pipeline.llm1_model, pipeline.llm2_model),
                            (llm1_model, llm2_model),
                        )

    def test_unknown_model_is_rejected_without_echoing_supplied_value(self):
        unknown = "UNTRUSTED_MODEL_INPUT_CANARY"
        for role in ("llm1_model", "llm2_model"):
            with self.subTest(role=role):
                with self.assertRaises(ValueError) as raised:
                    PipelineOrchestrator(**{role: unknown})

                self.assertIn(role, str(raised.exception))
                self.assertNotIn(unknown, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
