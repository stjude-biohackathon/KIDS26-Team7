"""
Track B: In-Memory GitHub App Loader Unit & Integration Tests.
Adheres strictly to specs/02_TRACK_B_DATA_AND_STORAGE.md.
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from storage.github_loader import (
    _TOKEN_CACHE,
    fetch_file_content_in_memory,
    fetch_remote_templates_and_orders,
    get_dataloader_config,
    get_installation_access_token,
    is_github_app_configured,
    load_mock_templates_and_orders,
    mint_jwt,
)


class TestGitHubLoader(unittest.TestCase):
    def setUp(self):
        _TOKEN_CACHE.clear()

    def test_configured_check(self):
        # Empty env should be unconfigured
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_github_app_configured())

        # Configured env
        env_mock = {
            "GITHUB_APP_ID": "123456",
            "GITHUB_INSTALLATION_ID": "654321",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/dummy_key.pem",
        }
        with patch.dict(os.environ, env_mock, clear=True):
            self.assertTrue(is_github_app_configured())

    def test_dataloader_section_parsing(self):
        # Test loading config with custom values
        env_mock = {
            "GITHUB_APP_ID": "app-999",
            "GITHUB_INSTALLATION_ID": "inst-888",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/tmp/key.pem",
            "GITHUB_DATA_REPO": "test-org/test-repo",
            "MODULES_PATH": "custom/modules.json",
            "ORDERS_PATH": "custom/orders.json",
        }
        with patch.dict(os.environ, env_mock, clear=True):
            cfg = get_dataloader_config()
            self.assertEqual(cfg["GITHUB_APP_ID"], "app-999")
            self.assertEqual(cfg["GITHUB_INSTALLATION_ID"], "inst-888")
            self.assertEqual(cfg["GITHUB_DATA_REPO"], "test-org/test-repo")
            self.assertEqual(cfg["MODULES_PATH"], "custom/modules.json")
            self.assertEqual(cfg["ORDERS_PATH"], "custom/orders.json")

    @patch("requests.get")
    def test_fetch_file_decodes_base64_in_memory(self, mock_get):
        raw_json_str = '{"sample_key": "sample_value", "number": 42}'
        b64_content = base64.b64encode(raw_json_str.encode("utf-8")).decode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "name": "templates.json",
            "path": "data/templates.json",
            "content": b64_content,
            "encoding": "base64",
        }
        mock_get.return_value = mock_resp

        result = fetch_file_content_in_memory(
            repo="org/repo",
            file_path="data/templates.json",
            token="test-token-xyz",
        )

        self.assertEqual(result, raw_json_str)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Authorization"], "token test-token-xyz")

    @patch("storage.github_loader.mint_jwt")
    @patch("requests.post")
    def test_token_caching(self, mock_post, mock_mint):
        mock_mint.return_value = "mocked-jwt"
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 201
        mock_post_resp.json.return_value = {"token": "ghs_test_token_12345"}
        mock_post.return_value = mock_post_resp

        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("DUMMY_KEY_DATA")
            key_path = f.name

        try:
            # First call fetches token via POST
            token1 = get_installation_access_token("app-1", "inst-1", key_path)
            self.assertEqual(token1, "ghs_test_token_12345")
            self.assertEqual(mock_post.call_count, 1)

            # Second call should use cached token without additional POST
            token2 = get_installation_access_token("app-1", "inst-1", key_path)
            self.assertEqual(token2, "ghs_test_token_12345")
            self.assertEqual(mock_post.call_count, 1)
        finally:
            if os.path.exists(key_path):
                os.remove(key_path)

    def test_mock_fallback_when_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            modules, orders = fetch_remote_templates_and_orders()
            self.assertIn("sickle_cell_pain", modules)
            self.assertIn("sickle_cell_pain", orders)


if __name__ == "__main__":
    unittest.main()
