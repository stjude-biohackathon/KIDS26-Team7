"""Phase 2 in-memory GitHub App loader tests (Track B).

All GitHub REST calls are mocked; no network access or real credentials are
used. Private keys are freshly generated, throwaway RSA test fixtures, never
persisted or reused. Confirms zero-disk streaming and in-memory token caching.
"""

import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import github_loader


def _generate_test_private_key_pem() -> bytes:
    """A fresh, throwaway RSA key used only to exercise JWT signing in tests."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


class ConfiguredCheckTests(unittest.TestCase):
    def test_is_github_app_configured_true_when_all_required_env_vars_present(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/does-not-need-to-exist.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(github_loader.is_github_app_configured())

    def test_is_github_app_configured_false_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("storage.github_loader._read_streamlit_secrets_section", return_value={}):
                    self.assertFalse(github_loader.is_github_app_configured())


class DataloaderSectionParsingTests(unittest.TestCase):
    def test_env_vars_populate_config_and_defaults_are_set(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("storage.github_loader._read_streamlit_secrets_section", return_value={}):
                    config = github_loader.get_dataloader_config()
        self.assertEqual(config["GITHUB_APP_ID"], "123")
        self.assertEqual(config["GITHUB_DATA_REPO"], "stjude-biohackathon/team7-data")
        self.assertIn("MODULES_PATH", config)
        self.assertIn("ORDERS_PATH", config)

    def test_toml_dataloader_section_is_parsed(self):
        toml_content = (
            "[dataloader]\n"
            'GITHUB_APP_ID = "789"\n'
            'GITHUB_INSTALLATION_ID = "999"\n'
            'GITHUB_APP_PRIVATE_KEY_PATH = "/tmp/from-toml.pem"\n'
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            secrets_dir = Path(tmp_dir) / ".streamlit"
            secrets_dir.mkdir()
            secrets_file = secrets_dir / "secrets.toml"
            secrets_file.write_text(toml_content)
            original_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    # Isolate from any real global secrets so this test verifies
                    # only the project-local-file fallback path.
                    with patch("storage.github_loader._read_streamlit_secrets_section", return_value={}):
                        config = github_loader.get_dataloader_config()
            finally:
                os.chdir(original_cwd)
        self.assertEqual(config["GITHUB_APP_ID"], "789")
        self.assertEqual(config["GITHUB_APP_PRIVATE_KEY_PATH"], "/tmp/from-toml.pem")


class FetchFileInMemoryTests(unittest.TestCase):
    def test_fetch_file_decodes_base64_in_memory_without_disk_writes(self):
        payload = {"content": base64.b64encode(b"template contents").decode("ascii")}
        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None
        with patch("storage.github_loader.requests.get", return_value=mock_response) as mock_get:
            result = github_loader.fetch_file_content_in_memory(
                "org/repo", "data/modules/file.json", "fake-token"
            )
        self.assertEqual(result, "template contents")
        called_headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(called_headers["Authorization"], "token fake-token")


class TokenCachingTests(unittest.TestCase):
    def setUp(self):
        github_loader._TOKEN_CACHE.clear()

    def test_installation_token_is_cached_and_reused(self):
        pem = _generate_test_private_key_pem()
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_file:
            key_file.write(pem)
            key_path = key_file.name
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"token": "minted-token-1"}
            mock_response.raise_for_status.return_value = None
            with patch("storage.github_loader.requests.post", return_value=mock_response) as mock_post:
                first = github_loader.get_installation_access_token("app-id", "install-id", key_path)
                second = github_loader.get_installation_access_token("app-id", "install-id", key_path)
            self.assertEqual(first, "minted-token-1")
            self.assertEqual(second, "minted-token-1")
            # Only one POST despite two calls: the second was served from the in-memory cache.
            self.assertEqual(mock_post.call_count, 1)
        finally:
            os.unlink(key_path)

    def test_installation_token_request_sends_bearer_jwt_header(self):
        pem = _generate_test_private_key_pem()
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_file:
            key_file.write(pem)
            key_path = key_file.name
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"token": "minted-token"}
            mock_response.raise_for_status.return_value = None
            with patch("storage.github_loader.requests.post", return_value=mock_response) as mock_post:
                with patch(
                    "storage.github_loader.mint_jwt", return_value="fake-jwt"
                ) as mock_mint_jwt:
                    github_loader.get_installation_access_token("app-id", "install-id", key_path)
            mock_mint_jwt.assert_called_once()
            called_headers = mock_post.call_args.kwargs["headers"]
            # Regression guard: the installation-token exchange must send the
            # real minted JWT as a Bearer credential, not a placeholder literal.
            self.assertEqual(called_headers["Authorization"], "Bearer fake-jwt")
        finally:
            os.unlink(key_path)

    def test_expired_token_triggers_a_fresh_mint(self):
        pem = _generate_test_private_key_pem()
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_file:
            key_file.write(pem)
            key_path = key_file.name
        try:
            github_loader._TOKEN_CACHE["app-id:install-id"] = ("stale-token", time.time() - 1)
            mock_response = MagicMock()
            mock_response.json.return_value = {"token": "fresh-token"}
            mock_response.raise_for_status.return_value = None
            with patch("storage.github_loader.requests.post", return_value=mock_response):
                token = github_loader.get_installation_access_token("app-id", "install-id", key_path)
            self.assertEqual(token, "fresh-token")
        finally:
            os.unlink(key_path)


class UpstreamSchemaAdapterTests(unittest.TestCase):
    """specs/05 FIX-B1/FIX-B2: real upstream payloads differ from the canonical shape."""

    def _modules_payload(self):
        return {
            "version": "v1.2.0",
            "version_history": [{"version": "v1.2.0"}, {"version": "v1.1.0"}],
            "handout_template_structure": [
                {"section": "supportive_home_care"},
                {"section": "pain_or_symptom_management"},
                {"section": "warning_signs_watch_for"},
                {"section": "when_to_seek_urgent_or_emergency_care"},
            ],
            "instructions": [
                {"id": "SC-014", "category": "sickle_cell_pain",
                 "type": "when_to_seek_urgent_or_emergency_care",
                 "instruction_text": "Go to the emergency room for fever of 101.0°F."},
                {"id": "SC-006", "category": "sickle_cell_pain",
                 "type": "pain_management",
                 "instruction_text": "Give pain medicine exactly as written."},
                {"id": "SC-001", "category": "sickle_cell_pain",
                 "type": "supportive_home_care",
                 "instruction_text": "Offer your child water often."},
                {"id": "SC-008", "category": "sickle_cell_pain",
                 "type": "warning_sign",
                 "instruction_text": "Watch for swelling of the hands or feet."},
                {"id": "CN-003", "category": "chemo_nausea_hydration",
                 "type": "hydration_nutrition",
                 "instruction_text": "Offer small sips of fluid every 15 minutes."},
            ],
        }

    def _orders_payload(self):
        return {
            "version": "v1.2.0",
            "version_history": [{"version": "v1.2.0"}, {"version": "v1.1.0"}],
            "synthetic_orders": [
                {
                    "order_id": "ORD-SC-01-v1.1", "version": "v1.1.0",
                    "category": "sickle_cell_pain", "diagnosis": "Archived record",
                    "patient_synthetic_id": "SYN-PED-999", "patient_age": "7 years",
                    "medications": [], "temperature_threshold_urgent": "100.0°F",
                },
                {
                    "order_id": "ORD-SC-01", "version": "v1.2.0",
                    "category": "sickle_cell_pain",
                    "diagnosis": "Sickle Cell Disease with acute pain episode",
                    "patient_synthetic_id": "SYN-PED-101", "patient_age": "9 years",
                    "weight_kg": 28.5,
                    "medications": [
                        {"name": "Ibuprofen (Advil/Motrin)", "dose": "280 mg",
                         "route": "Oral", "frequency": "every 6 hours as needed"},
                    ],
                    "hydration_order": "Encourage 1,800 to 2,000 mL of oral fluids daily.",
                    "temperature_threshold_urgent": "100.4°F (38.0°C)",
                    "temperature_threshold_emergency": "101.0°F (38.3°C)",
                    "red_flag_symptoms": ["Lethargy", "Sudden chest pain"],
                    "clinic_phone_daytime": "555-0144 (Day Clinic)",
                    "clinic_phone_after_hours": "555-0190 (On-Call)",
                    "emergency_contact": "Call 911 or go to the Emergency Department",
                },
            ],
        }

    def test_trailing_comma_json_is_parsed_and_warned(self):
        warnings = []
        payload = '{\n "a": 1,\n "b": {"c": 2,},\n}'
        parsed = github_loader.parse_json_tolerantly(payload, warnings, "modules")
        self.assertEqual(parsed, {"a": 1, "b": {"c": 2}})
        self.assertEqual(len(warnings), 1)
        self.assertIn("trailing comma", warnings[0])

    def test_strict_json_parses_without_emitting_a_warning(self):
        warnings = []
        parsed = github_loader.parse_json_tolerantly('{"a": 1}', warnings, "modules")
        self.assertEqual(parsed, {"a": 1})
        self.assertEqual(warnings, [])

    def test_adapt_modules_groups_by_category_in_declared_section_order(self):
        modules = github_loader.adapt_modules(self._modules_payload())
        self.assertEqual(
            set(modules.keys()), {"sickle_cell_pain", "chemo_nausea_hydration"}
        )
        # Both the current version and the historical label resolve to real text.
        self.assertEqual(set(modules["sickle_cell_pain"].keys()), {"v1.2.0", "v1.1.0"})
        text = modules["sickle_cell_pain"]["v1.2.0"]

        # Every vetted instruction_text is carried verbatim.
        for expected in (
            "Offer your child water often.",
            "Give pain medicine exactly as written.",
            "Watch for swelling of the hands or feet.",
            "Go to the emergency room for fever of 101.0°F.",
        ):
            self.assertIn(expected, text)

        # Ordering follows handout_template_structure, not input order.
        self.assertLess(
            text.index("Offer your child water often."),
            text.index("Give pain medicine exactly as written."),
        )
        self.assertLess(
            text.index("Give pain medicine exactly as written."),
            text.index("Watch for swelling of the hands or feet."),
        )
        self.assertLess(
            text.index("Watch for swelling of the hands or feet."),
            text.index("Go to the emergency room for fever of 101.0°F."),
        )

    def test_adapt_modules_maps_unmatched_types_to_declared_sections(self):
        modules = github_loader.adapt_modules(self._modules_payload())
        sickle = modules["sickle_cell_pain"]["v1.2.0"]
        self.assertIn("PAIN OR SYMPTOM MANAGEMENT", sickle)
        self.assertIn("WARNING SIGNS WATCH FOR", sickle)
        self.assertNotIn("PAIN MANAGEMENT ===", sickle)
        # hydration_nutrition has no declared section and is placed under
        # supportive_home_care per the clinical owner's mapping.
        chemo = modules["chemo_nausea_hydration"]["v1.2.0"]
        self.assertIn("SUPPORTIVE HOME CARE", chemo)
        self.assertIn("Offer small sips of fluid every 15 minutes.", chemo)

    def test_adapt_modules_rejects_empty_payload(self):
        with self.assertRaises(ValueError):
            github_loader.adapt_modules({"version": "v1.2.0", "instructions": []})

    def test_adapt_orders_maps_upstream_fields(self):
        orders = github_loader.adapt_orders(self._orders_payload())
        order = orders["sickle_cell_pain"]
        # The current-version record wins over the archived one.
        self.assertEqual(order.order_id, "ORD-SC-01")
        self.assertEqual(order.order_version, "v1.2.0")
        self.assertEqual(order.patient_id, "SYN-PED-101")
        self.assertEqual(order.age, "9 years")
        self.assertEqual(order.diagnosis, "Sickle Cell Disease with acute pain episode")
        self.assertEqual(order.urgent_fever_threshold, "100.4°F (38.0°C)")
        self.assertEqual(order.emergency_fever_threshold, "101.0°F (38.3°C)")
        self.assertEqual(order.daytime_phone, "555-0144 (Day Clinic)")
        self.assertEqual(order.after_hours_phone, "555-0190 (On-Call)")
        self.assertEqual(order.emergency_phone, "Call 911 or go to the Emergency Department")
        self.assertEqual(len(order.medications), 1)
        self.assertEqual(order.medications[0].name, "Ibuprofen (Advil/Motrin)")
        self.assertEqual(order.medications[0].dose, "280 mg")
        self.assertEqual(order.medications[0].frequency, "every 6 hours as needed")

    def test_merge_order_safety_sections_preserves_hydration_and_red_flags(self):
        modules = github_loader.adapt_modules(self._modules_payload())
        merged = github_loader.merge_order_safety_sections(modules, self._orders_payload())
        text = merged["sickle_cell_pain"]["v1.2.0"]
        self.assertIn("Encourage 1,800 to 2,000 mL of oral fluids daily.", text)
        self.assertIn("Lethargy", text)
        self.assertIn("Sudden chest pain", text)
        # Original instruction content is still present.
        self.assertIn("Offer your child water often.", text)


class LoadStatusReportingTests(unittest.TestCase):
    """specs/05 FIX-B3: failures must be recorded, never silently masked."""

    def test_unconfigured_load_reports_mock_source_with_reason(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("storage.github_loader._read_streamlit_secrets_section", return_value={}):
                    github_loader.fetch_remote_templates_and_orders()
        status = github_loader.get_last_load_status()
        self.assertEqual(status["source"], "mock")
        self.assertIn("not configured", status["error"])

    def test_failed_live_load_records_error_and_reports_mock_source(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
        secret_canary = "PRIVATE_TOKEN_CANARY"
        with patch.dict(os.environ, env, clear=True):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "storage.github_loader.get_installation_access_token",
                    side_effect=RuntimeError(secret_canary),
                ):
                    modules, _ = github_loader.fetch_remote_templates_and_orders()
        status = github_loader.get_last_load_status()
        self.assertEqual(status["source"], "mock")
        self.assertTrue(status["error"])
        # The recorded reason must never echo exception payloads.
        self.assertNotIn(secret_canary, status["error"])
        mock_modules, _ = github_loader.load_mock_templates_and_orders()
        self.assertEqual(modules, mock_modules)

    def test_strict_mode_reraises_instead_of_falling_back(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "storage.github_loader.get_installation_access_token",
                    side_effect=RuntimeError("network unavailable"),
                ):
                    with self.assertRaises(RuntimeError):
                        github_loader.fetch_remote_templates_and_orders(strict=True)
        self.assertEqual(github_loader.get_last_load_status()["source"], "mock")

    def test_successful_live_load_reports_github_app_source(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
        adapter_tests = UpstreamSchemaAdapterTests()
        modules_json = json.dumps(adapter_tests._modules_payload())
        orders_json = json.dumps(adapter_tests._orders_payload())
        with patch.dict(os.environ, env, clear=True):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "storage.github_loader.get_installation_access_token",
                    return_value="fake-token",
                ):
                    with patch(
                        "storage.github_loader.fetch_file_content_in_memory",
                        side_effect=[modules_json, orders_json],
                    ):
                        modules, orders = github_loader.fetch_remote_templates_and_orders()
        status = github_loader.get_last_load_status()
        self.assertEqual(status["source"], "github_app")
        self.assertIsNone(status["error"])
        self.assertIn("sickle_cell_pain", modules)
        self.assertEqual(orders["sickle_cell_pain"].patient_id, "SYN-PED-101")
        mock_modules, _ = github_loader.load_mock_templates_and_orders()
        self.assertNotEqual(modules, mock_modules)


class RemoteFetchFallbackTests(unittest.TestCase):
    def test_falls_back_to_mock_data_when_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                modules, orders = github_loader.fetch_remote_templates_and_orders()
        mock_modules, mock_orders = github_loader.load_mock_templates_and_orders()
        self.assertEqual(modules, mock_modules)
        self.assertEqual(set(orders.keys()), set(mock_orders.keys()))

    def test_falls_back_to_mock_data_on_remote_failure(self):
        env = {
            "GITHUB_APP_ID": "123",
            "GITHUB_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "storage.github_loader.get_installation_access_token",
                    side_effect=RuntimeError("network unavailable"),
                ):
                    modules, orders = github_loader.fetch_remote_templates_and_orders()
        mock_modules, _ = github_loader.load_mock_templates_and_orders()
        self.assertEqual(modules, mock_modules)


if __name__ == "__main__":
    unittest.main()
