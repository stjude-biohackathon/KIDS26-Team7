"""Read local/home configuration without displaying secret values."""
from pathlib import Path
import tomllib


def load_settings():
    settings = {}
    for path in (Path.home() / '.streamlit/secrets.toml', Path(__file__).resolve().parents[1] / '.streamlit/secrets.toml'):
        if path.is_file():
            try:
                with path.open('rb') as stream:
                    incoming = tomllib.load(stream)
                for section, values in incoming.items():
                    if isinstance(values, dict):
                        settings.setdefault(section, {}).update(values)
            except Exception:
                raise ValueError('Unable to read application configuration.') from None
    return settings
