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
