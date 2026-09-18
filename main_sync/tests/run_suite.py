"""Run synthetic regression tests without network access or user secrets."""
import builtins
import importlib.util
from contextlib import nullcontext
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # Allow only test-created temporary secrets fixtures, never a user's file.
    original_open = builtins.open
    temp_root = Path(tempfile.gettempdir()).resolve()
    def guarded_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)):
            path = Path(file).resolve()
            if path.name == 'secrets.toml' and not path.is_relative_to(temp_root):
                raise AssertionError('Tests may not open user secrets.')
            if path.suffix == '.jsonl':
                raise AssertionError('Clinical JSONL persistence is prohibited.')
        return original_open(file, *args, **kwargs)

    for name in ('streamlit.runtime.caching.cache_data_api', 'streamlit.runtime.scriptrunner_utils.script_run_context', 'streamlit.runtime.state.session_state_proxy'):
        logging.getLogger(name).setLevel(logging.ERROR)
    with patch('builtins.open', guarded_open), patch('streamlit.secrets', {}), patch(
        'requests.sessions.Session.request', side_effect=AssertionError('Network disabled in tests')
    ), (patch('httpx.Client.send', side_effect=AssertionError('Network disabled in tests'))
        if importlib.util.find_spec('httpx') else nullcontext()):
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), top_level_dir=str(ROOT))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
