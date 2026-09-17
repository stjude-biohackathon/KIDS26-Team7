"""Phase 0 model-selection tests; live credential resolution comes in Phase 2."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.orchestrator import PipelineOrchestrator
from pipeline.llms import get_client, resolve_model_config


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


class AzureCredentialResolutionTests(unittest.TestCase):
    """specs/05 FIX-A1: the provisioned secrets use Azure OpenAI key names."""

    def test_azure_key_names_resolve(self):
        secret_canary = "AZURE_KEY_CANARY_VALUE"
        section = {
            "AZURE_OPENAI_ENDPOINT": "https://example-resource.openai.azure.com/",
            "AZURE_BASE_URL": "https://example-resource.openai.azure.com/openai/",
            "AZURE_OPENAI_API_KEY": secret_canary,
            "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            "MODEL_DEPLOYMENT": "gpt-4o-deployment",
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._load_secrets_section", return_value=section):
                config = resolve_model_config("gpt4o")
        self.assertTrue(config.is_azure)
        self.assertEqual(config.azure_endpoint, "https://example-resource.openai.azure.com/")
        self.assertEqual(config.api_version, "2025-01-01-preview")
        self.assertEqual(config.deployment, "gpt-4o-deployment")
        self.assertEqual(config.api_key, secret_canary)

    def test_truncated_azure_endpoint_key_spelling_still_resolves(self):
        # Some provisioned local* sections use the truncated upstream
        # spelling `AZURE_OPENAI_ENDPOIN` instead of `AZURE_OPENAI_ENDPOINT`.
        section = {
            "AZURE_OPENAI_ENDPOIN": "https://example-resource.openai.azure.com/",
            "AZURE_BASE_URL": "https://example-resource.openai.azure.com/openai/",
            "AZURE_OPENAI_API_KEY": "canary",
            "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            "MODEL_DEPLOYMENT": "gpt-4o-deployment",
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._load_secrets_section", return_value=section):
                config = resolve_model_config("gpt4o")
        self.assertTrue(config.is_azure)
        self.assertEqual(config.azure_endpoint, "https://example-resource.openai.azure.com/")

    def test_local_alias_uses_plain_openai_client(self):
        # Provisioned local* sections have an empty api_version, so even
        # though AZURE_BASE_URL is set, the alias must not be treated as Azure.
        section = {
            "AZURE_BASE_URL": "http://localhost:11434/v1",
            "AZURE_OPENAI_API_KEY": "local-canary",
            "AZURE_OPENAI_API_VERSION": "",
            "MODEL_DEPLOYMENT": "qwen3.5:9b",
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._load_secrets_section", return_value=section):
                config = resolve_model_config("local1")
        self.assertFalse(config.is_azure)
        self.assertEqual(config.base_url, "http://localhost:11434/v1")
        self.assertEqual(config.deployment, "qwen3.5:9b")

    def test_get_client_selects_azure_client_for_azure_config(self):
        section = {
            "AZURE_OPENAI_ENDPOINT": "https://example-resource.openai.azure.com/",
            "AZURE_BASE_URL": "https://example-resource.openai.azure.com/openai/",
            "AZURE_OPENAI_API_KEY": "canary",
            "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            "MODEL_DEPLOYMENT": "gpt-4o-deployment",
        }
        fake_azure_client = MagicMock(name="AzureOpenAIInstance")
        fake_azure_ctor = MagicMock(return_value=fake_azure_client)
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._load_secrets_section", return_value=section):
                with patch("openai.AzureOpenAI", fake_azure_ctor, create=True):
                    client, deployment = get_client("gpt4o")
        fake_azure_ctor.assert_called_once_with(
            azure_endpoint="https://example-resource.openai.azure.com/",
            api_key="canary",
            api_version="2025-01-01-preview",
        )
        self.assertIs(client, fake_azure_client)
        self.assertEqual(deployment, "gpt-4o-deployment")

    def test_get_client_selects_plain_openai_client_for_local_alias(self):
        section = {
            "AZURE_BASE_URL": "http://localhost:11434/v1",
            "AZURE_OPENAI_API_KEY": "local-canary",
            "AZURE_OPENAI_API_VERSION": "",
            "MODEL_DEPLOYMENT": "qwen3.5:9b",
        }
        fake_openai_client = MagicMock(name="OpenAIInstance")
        fake_openai_ctor = MagicMock(return_value=fake_openai_client)
        with patch.dict(os.environ, {}, clear=True):
            with patch("pipeline.llms._load_secrets_section", return_value=section):
                with patch("openai.OpenAI", fake_openai_ctor, create=True):
                    client, deployment = get_client("local1")
        fake_openai_ctor.assert_called_once_with(
            base_url="http://localhost:11434/v1", api_key="local-canary"
        )
        self.assertIs(client, fake_openai_client)
        self.assertEqual(deployment, "qwen3.5:9b")


if __name__ == "__main__":
    unittest.main()



class ModelErrorDescriptionTests(unittest.TestCase):
    """specs/05 FIX-C2: failures must be described honestly, without secrets."""

    def test_unconfigured_alias_reported_as_configuration_problem(self):
        from pipeline.llms import describe_model_error

        msg = describe_model_error("kimik3", ValueError("No endpoint/credentials configured"))
        self.assertIn("kimik3", msg)
        self.assertIn("no endpoint or credentials configured", msg)

    def test_access_denied_distinguished_from_missing_configuration(self):
        from pipeline.llms import describe_model_error

        exc = Exception("Access denied due to Virtual Network/Firewall rules.")
        exc.status_code = 403
        msg = describe_model_error("gpt52", exc)
        self.assertIn("access denied", msg)
        self.assertIn("403", msg)
        self.assertNotIn("configured for this model alias", msg)

    def test_unreachable_endpoint_reported_as_connection_failure(self):
        from pipeline.llms import describe_model_error

        class APIConnectionError(Exception):
            pass

        msg = describe_model_error("local1", APIConnectionError("Connection error."))
        self.assertIn("could not reach", msg)

    def test_description_never_echoes_credentials_or_endpoint(self):
        from pipeline.llms import describe_model_error

        secret = "sk-supersecretkey1234"
        endpoint = "https://private-resource.openai.azure.com"
        exc = Exception(f"401 unauthorized for {endpoint} using {secret}")
        exc.status_code = 401
        msg = describe_model_error("gpt4o", exc)
        self.assertNotIn(secret, msg)
        self.assertNotIn(endpoint, msg)
