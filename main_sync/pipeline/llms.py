"""Model aliases and Phase 2 live credential/client resolution (Track A).

Importing this module never reads secrets or creates an external client;
credentials are only resolved when ``get_client`` is called. Nothing here
ever prints, logs, or raises with a secret value embedded in the message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

AVAILABLE_MODELS: tuple[str, ...] = (
    "gpt52",
    "gpt4o",
    "gpt56luna",
    "kimik3",
    "copus5",
    "local1",
    "local2",
)

# Local aliases need no external credentials; they target an OpenAI-compatible
# server (e.g. Ollama, vLLM) running on the caller's machine.
_LOCAL_MODELS = {"local1", "local2"}
_DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_LOCAL_API_KEY = "local-no-key-required"

_SECRETS_PATH = Path(".streamlit") / "secrets.toml"


@dataclass(frozen=True)
class ModelConfig:
    """Resolved, non-secret-printing connection details for one model alias."""

    alias: str
    base_url: str
    api_key: str
    deployment: str


def _env_prefix(alias: str) -> str:
    """Uppercased, non-alphanumeric-safe prefix for an alias's env vars."""
    return "".join(ch if ch.isalnum() else "_" for ch in alias).upper()


def _load_secrets_section(alias: str) -> dict:
    """Read the `[alias]` section (e.g. `[gpt52]`) via Streamlit's secrets resolver.

    Each supported model has its own top-level section in secrets.toml,
    named exactly after its alias (e.g. `[gpt52]`, `[gpt4o]`, `[local1]`).
    Prefers `st.secrets`, which transparently checks the global
    `~/.streamlit/secrets.toml` (where governance requires this project's
    secrets file to live) as well as any project-local
    `.streamlit/secrets.toml`. Never opens, reads, or logs the file itself
    outside of calling Streamlit's own API. Falls back to a project-local
    `.streamlit/secrets.toml` read (for non-Streamlit contexts such as
    scripts/tests) if Streamlit secrets are unavailable.
    """
    try:
        import streamlit as st

        if alias in st.secrets: 
            return dict(st.secrets[alias])
    except Exception:
        pass

    if not _SECRETS_PATH.exists():
        return {}
    try:
        import toml
    except ImportError:
        return {}
    try:
        data = toml.load(_SECRETS_PATH)
    except Exception:
        return {}
    if alias in data and isinstance(data[alias], dict):
        return data[alias]
    return {}


def resolve_model_config(alias: str) -> ModelConfig:
    """Resolve base_url/api_key/deployment for a model alias.

    Resolution order: `.streamlit/secrets.toml` `[alias]` section, then
    `{ALIAS}_BASE_URL` / `{ALIAS}_API_KEY` / `{ALIAS}_MODEL` environment
    variables. Local aliases fall back to a local OpenAI-compatible server;
    remote aliases raise if credentials are unavailable.
    """
    if alias not in AVAILABLE_MODELS:
        raise ValueError("Unsupported model alias; select an AVAILABLE_MODELS entry.")

    secrets = _load_secrets_section(alias)
    prefix = _env_prefix(alias)

    base_url = (
        secrets.get("base_url")
        or os.environ.get(f"{prefix}_BASE_URL")
        or (_DEFAULT_LOCAL_BASE_URL if alias in _LOCAL_MODELS else None)
    )
    api_key = (
        secrets.get("api_key")
        or os.environ.get(f"{prefix}_API_KEY")
        or (_DEFAULT_LOCAL_API_KEY if alias in _LOCAL_MODELS else None)
    )
    deployment = (
        secrets.get("model")
        or os.environ.get(f"{prefix}_MODEL")
        or alias
    )

    if not base_url or not api_key:
        raise ValueError(
            f"No endpoint/credentials configured for model alias '{alias}'. "
            "Set [alias] in .streamlit/secrets.toml or the "
            f"{prefix}_BASE_URL/{prefix}_API_KEY environment variables."
        )
    return ModelConfig(alias=alias, base_url=base_url, api_key=api_key, deployment=deployment)


def get_client(alias: str):
    """Build an OpenAI-compatible client for the given model alias.

    Imports `openai` lazily so importing this module (or selecting a model
    offline) never requires the dependency or touches the network.
    """
    from openai import OpenAI

    config = resolve_model_config(alias)
    return OpenAI(base_url=config.base_url, api_key=config.api_key), config.deployment
