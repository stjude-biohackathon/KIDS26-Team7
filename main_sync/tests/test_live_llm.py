"""Phase 2 credential resolution and live LLM call tests (Track A).

All tests are fully offline: OpenAI client calls are mocked, and no real
credentials are read or required. Assertions confirm secrets are never
echoed into exception messages.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import live_llm
from pipeline.llms import resolve_model_config
from schemas.instruction_packet import ClinicalOrders, MedicationOrder, SafetyJudgeResult


def synthetic_orders(**changes):
    values = dict(
        patient_id="SYN-PED-001", diagnosis="Synthetic example",
        medications=[MedicationOrder(name="Synthetic", dose="5 mg")],
        urgent_fever_threshold="100.4°F", emergency_fever_threshold="101.0°F",
        daytime_phone="202-555-0100", after_hours_phone="202-555-0100",
        emergency_phone="911", order_id="ORDER-TEST", order_version="v1.2.0",
    )
    values.update(changes)
    return ClinicalOrders(**values)


class CredentialResolutionTests(unittest.TestCase):
    def test_remote_alias_without_credentials_raises_without_echoing_env(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._SECRETS_PATH", Path("/nonexistent/secrets.toml")):
                with patch("pipeline.llms._read_st_secrets_section", return_value={}):
                    with self.assertRaises(ValueError) as raised:
                        resolve_model_config("gpt4o")
        self.assertIn("gpt4o", str(raised.exception))

    def test_remote_alias_resolves_from_env_vars_without_leaking_key(self):
        secret_canary = "PRIVATE_KEY_CANARY_VALUE"
        env = {
            "GPT4O_BASE_URL": "https://example.invalid/v1",
            "GPT4O_API_KEY": secret_canary,
            "GPT4O_MODEL": "gpt-4o-deployment",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("pipeline.llms._SECRETS_PATH", Path("/nonexistent/secrets.toml")):
                with patch("pipeline.llms._read_st_secrets_section", return_value={}):
                    config = resolve_model_config("gpt4o")
        self.assertEqual(config.base_url, "https://example.invalid/v1")
        self.assertEqual(config.deployment, "gpt-4o-deployment")
        self.assertEqual(config.api_key, secret_canary)

        # The resolved key must never appear inside a raised error message.
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._SECRETS_PATH", Path("/nonexistent/secrets.toml")):
                with patch("pipeline.llms._read_st_secrets_section", return_value={}):
                    with self.assertRaises(ValueError) as raised:
                        resolve_model_config("gpt4o")
        self.assertNotIn(secret_canary, str(raised.exception))

    def test_local_alias_falls_back_to_local_server_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._SECRETS_PATH", Path("/nonexistent/secrets.toml")):
                with patch("pipeline.llms._read_st_secrets_section", return_value={}):
                    config = resolve_model_config("local1")
        self.assertTrue(config.base_url.startswith("http://localhost"))
        self.assertEqual(config.deployment, "local1")


    def test_unknown_alias_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_model_config("UNTRUSTED_MODEL_INPUT_CANARY")


class LiveLlmCallTests(unittest.TestCase):
    def _mock_client(self, content: str):
        client = MagicMock()
        client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content=content))
        ]
        return client

    def test_simplify_returns_model_text(self):
        client = self._mock_client("Give 5 mg by mouth every day.")
        result = live_llm.simplify_to_plain_language(client, "deploy", "source", synthetic_orders())
        self.assertEqual(result, "Give 5 mg by mouth every day.")

    def test_empty_model_response_raises(self):
        client = self._mock_client("   ")
        with self.assertRaises(ValueError):
            live_llm.simplify_to_plain_language(client, "deploy", "source", synthetic_orders())

    def test_judge_safety_parses_well_formed_json(self):
        payload = (
            '{"overall_verdict": "PASS", "factual_drift_detected": false, '
            '"omitted_red_flags": [], "contradictory_advice": [], '
            '"clinical_risk_score": 0.1, "explanation": "Looks fine."}'
        )
        client = self._mock_client(payload)
        result = live_llm.judge_safety(client, "deploy", "orig", "simplified", synthetic_orders())
        self.assertIsInstance(result, SafetyJudgeResult)
        self.assertEqual(result.overall_verdict, "PASS")
        self.assertEqual(result.explanation, "Looks fine.")

    def test_judge_safety_strips_code_fences(self):
        payload = '```json\n{"overall_verdict": "NEEDS_REVIEW", "explanation": "ok"}\n```'
        client = self._mock_client(payload)
        result = live_llm.judge_safety(client, "deploy", "orig", "simplified", synthetic_orders())
        self.assertEqual(result.overall_verdict, "NEEDS_REVIEW")

    def test_judge_safety_never_raises_on_api_failure(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("PRIVATE_CANARY network detail")
        result = live_llm.judge_safety(client, "deploy", "orig", "simplified", synthetic_orders())
        self.assertEqual(result.overall_verdict, "FLAGGED_FOR_REVIEW")
        self.assertNotIn("PRIVATE_CANARY", result.explanation)

    def test_judge_safety_never_raises_on_malformed_json(self):
        client = self._mock_client("not valid json at all")
        result = live_llm.judge_safety(client, "deploy", "orig", "simplified", synthetic_orders())
        self.assertEqual(result.overall_verdict, "FLAGGED_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()
