"""Exercise live UI wiring at the GitHub/SDK boundaries without paid requests."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class LiveUITests(unittest.TestCase):
    def test_live_mode_fetches_versions_routes_models_and_rechecks_edits(self):
        protocol = {'original_text': 'Synthetic reference. Example: $emergency_phone.',
                    'plain_language_template': 'Example: $emergency_phone.',
                    'vetted_by': 'Synthetic clinician', 'vetted_at': '2026-09-17', 'required_red_flags': []}
        modules = {'demo': {'v1': protocol, 'v2': protocol}}
        orders = {'demo': {version: {'patient_id': 'SYN-PED-001', 'diagnosis': 'Synthetic',
            'order_version': version, 'urgent_fever_threshold': '', 'emergency_fever_threshold': '',
            'medications': [], 'daytime_phone': '', 'after_hours_phone': '',
            'emergency_phone': phone} for version, phone in [('v1', '911'), ('v2', '112')]}}
        seen = []

        def get(url, **kwargs):
            response = MagicMock()
            data = modules if url.endswith('modules.json') else orders
            response.json.return_value = {'encoding': 'base64', 'content': base64.b64encode(json.dumps(data).encode()).decode()}
            return response

        def complete(**kwargs):
            seen.append(kwargs)
            text = kwargs['messages'][1]['content']
            if 'response_format' in kwargs:
                text = json.dumps({'overall_verdict': 'PASS', 'factual_drift_detected': False,
                    'omitted_red_flags': [], 'contradictory_advice': [], 'clinical_risk_score': 0.0,
                    'explanation': 'Synthetic provider test.'})
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=text, refusal=None))])

        # A temporary test signing key exercises actual JWT construction; it is
        # not a service credential and is removed when this test finishes.
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with tempfile.TemporaryDirectory() as temp:
            keypath = Path(temp) / 'synthetic.pem'
            keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            env = {'GITHUB_APP_ID': '1', 'GITHUB_INSTALLATION_ID': '2', 'GITHUB_APP_PRIVATE_KEY_PATH': str(keypath),
                   'GITHUB_DATA_REPO': 'test/catalog', 'MODULES_PATH': 'modules.json', 'ORDERS_PATH': 'orders.json'}
            for alias in ('GPT52', 'GPT4O', 'LOCAL1'):
                env.update({f'CLEAR_{alias}_API_KEY': 'fake-key', f'CLEAR_{alias}_MODEL': f'deployment-{alias}',
                            f'CLEAR_{alias}_BASE_URL': 'https://example.test/v1'})
            with patch.dict(os.environ, env, clear=True), patch('requests.get', side_effect=get) as http_get, patch('requests.post') as post, patch('openai.OpenAI') as sdk:
                post.return_value.json.return_value = {'token': 'fake-token'}
                sdk.return_value.chat.completions.create.side_effect = complete
                at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=20).run()
                at.radio(key='runtime_mode').set_value('Live integrations (Phase 2)').run()
                self.assertFalse(at.exception)
                self.assertTrue(any('GitHub App' in item.value for item in at.markdown))
                next(widget for widget in at.selectbox if widget.label == 'Order Set Ver:').select('v2').run()
                next(widget for widget in at.selectbox if widget.label.startswith('LLM 1')).select('local1').run()
                next(button for button in at.button if 'Generate Instructions' in button.label).click().run()
                self.assertFalse(at.exception)
                packet = at.session_state['current_packet']
                self.assertEqual(packet.source_mode, 'live')
                self.assertEqual(packet.order_version, 'v2')
                self.assertIn('112', packet.translated_es)
                self.assertEqual(seen[0]['model'], 'deployment-LOCAL1')
                self.assertEqual(seen[-1]['model'], 'deployment-GPT4O')
                self.assertTrue(all('112' not in call['messages'][1]['content'] for call in seen))
                at.text_area(key='txt_clinician_en').input(packet.simplified_en + ' Synthetic edit.').run()
                next(button for button in at.button if 'Save & Check' in button.label).click().run()
                revised = at.session_state['current_packet']
                self.assertNotEqual(revised.packet_id, packet.packet_id)
                self.assertTrue(revised.translated_es.endswith('Synthetic edit.'))
                next(button for button in at.button if 'Approve & Publish' in button.label).click().run()
                self.assertEqual(at.session_state['current_packet'].status, 'PENDING')
                at.checkbox(key=f'spanish_reviewed_{revised.packet_id}').check().run()
                at.text_input(key=f'spanish_reviewer_{revised.packet_id}').input('Synthetic reviewer').run()
                next(button for button in at.button if 'Approve & Publish' in button.label).click().run()
                self.assertEqual(at.session_state['current_packet'].status, 'EDITED_AND_APPROVED')
                prior_fetches = http_get.call_count
                next(button for button in at.button if button.label == 'Refresh data').click().run()
                self.assertGreater(http_get.call_count, prior_fetches)

    def test_live_mode_configuration_error_is_explicit_without_mock_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            at = AppTest.from_file(str(ROOT / 'app/clinician_ui.py'), default_timeout=15).run()
            at.radio(key='runtime_mode').set_value('Live integrations (Phase 2)').run()
            self.assertFalse(at.exception)
            self.assertTrue(at.error)
            self.assertIsNone(at.session_state['current_packet'])


if __name__ == '__main__':
    unittest.main()
