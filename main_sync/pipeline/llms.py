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


class ModelConfigurationError(ValueError):
    """Required endpoint configuration is missing or invalid."""


@dataclass(frozen=True)
class ModelConfig:
    """Resolved, non-secret-printing connection details for one model alias."""

    alias: str
    base_url: str
    api_key: str
    deployment: str
    azure_endpoint: str = ""
    api_version: str = ""

    @property
    def is_azure(self) -> bool:
        """True when this alias must be reached through the Azure OpenAI API.

        Both an endpoint and an API version are required: Azure OpenAI's REST
        surface is versioned, so a populated `azure_endpoint` without a usable
        `api_version` cannot actually be dispatched through the Azure client.
        """
        return bool(self.azure_endpoint and self.api_version)


def _env_prefix(alias: str) -> str:
    """Uppercased, non-alphanumeric-safe prefix for an alias's env vars."""
    return "".join(ch if ch.isalnum() else "_" for ch in alias).upper()


def _read_st_secrets_section(alias: str) -> dict:
    """Read the `[alias]` section via Streamlit's own secrets resolver.

    `st.secrets` transparently checks the global `~/.streamlit/secrets.toml`
    (where governance requires this project's secrets file to live) as well
    as any project-local `.streamlit/secrets.toml`. This function never
    opens, reads, or logs the file itself — it only calls Streamlit's own API
    and returns the parsed section as a plain dict. Isolated into its own
    function so tests can patch it directly instead of relying on a
    real/absent Streamlit secrets file.
    """
    try:
        import streamlit as st

        if alias in st.secrets:
            return dict(st.secrets[alias])
    except Exception:
        # No secrets file configured, not running under Streamlit, or the
        # section is absent -- all treated the same as "not configured".
        pass
    return {}


def _load_secrets_section(alias: str) -> dict:
    """Read the `[alias]` section (e.g. `[gpt52]`) via Streamlit's secrets resolver.

    Each supported model has its own top-level section in secrets.toml,
    named exactly after its alias (e.g. `[gpt52]`, `[gpt4o]`, `[local1]`).
    Prefers `st.secrets` (see `_read_st_secrets_section`). Falls back to a
    project-local `.streamlit/secrets.toml` read (for non-Streamlit contexts
    such as scripts/tests) if Streamlit secrets are unavailable.
    """
    section = _read_st_secrets_section(alias)
    if section:
        return section

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
    """Resolve connection details for a model alias.

    Each secrets section may use either the generic key names
    (`base_url`/`api_key`/`model`) or the Azure OpenAI key names actually
    provisioned for this project (`AZURE_BASE_URL`/`AZURE_OPENAI_API_KEY`/
    `AZURE_OPENAI_API_VERSION`/`AZURE_OPENAI_ENDPOINT`/`MODEL_DEPLOYMENT`).
    Some provisioned `local*` sections use a truncated `AZURE_OPENAI_ENDPOIN`
    spelling; both spellings are checked. Resolution order per field:
    secrets section, then `{ALIAS}_BASE_URL` / `{ALIAS}_API_KEY` /
    `{ALIAS}_MODEL` environment variables. Local aliases fall back to a local
    OpenAI-compatible server; remote aliases raise if credentials are
    unavailable.
    """
    if alias not in AVAILABLE_MODELS:
        raise ModelConfigurationError("Unsupported model alias; select an AVAILABLE_MODELS entry.")

    secrets = _load_secrets_section(alias)
    prefix = _env_prefix(alias)

    azure_endpoint = (
        secrets.get("AZURE_OPENAI_ENDPOINT")
        or secrets.get("AZURE_OPENAI_ENDPOIN")
        or ""
    )
    api_version = secrets.get("AZURE_OPENAI_API_VERSION") or ""

    base_url = (
        secrets.get("base_url")
        or secrets.get("AZURE_BASE_URL")
        or os.environ.get(f"{prefix}_BASE_URL")
        or (_DEFAULT_LOCAL_BASE_URL if alias in _LOCAL_MODELS else None)
    )
    api_key = (
        secrets.get("api_key")
        or secrets.get("AZURE_OPENAI_API_KEY")
        or os.environ.get(f"{prefix}_API_KEY")
        or (_DEFAULT_LOCAL_API_KEY if alias in _LOCAL_MODELS else None)
    )
    deployment = (
        secrets.get("model")
        or secrets.get("MODEL_DEPLOYMENT")
        or os.environ.get(f"{prefix}_MODEL")
        or alias
    )

    if not base_url or not api_key:
        raise ModelConfigurationError(
            f"No endpoint/credentials configured for model alias '{alias}'. "
            "Set [alias] in .streamlit/secrets.toml or the "
            f"{prefix}_BASE_URL/{prefix}_API_KEY environment variables."
        )
    # Azure OpenAI requires api_version alongside its endpoint; without it the
    # Azure client cannot be constructed, so treat the alias as non-Azure and
    # let it fall through to the plain OpenAI-compatible client instead.
    if azure_endpoint and not api_version:
        azure_endpoint = ""
    return ModelConfig(
        alias=alias,
        base_url=base_url,
        api_key=api_key,
        deployment=deployment,
        azure_endpoint=azure_endpoint,
        api_version=api_version,
    )


def get_client(alias: str):
    """Build an OpenAI-compatible client for the given model alias.

    Imports `openai` lazily so importing this module (or selecting a model
    offline) never requires the dependency or touches the network. Remote
    Azure-provisioned aliases (endpoint + api_version both present) use
    `AzureOpenAI`; all other aliases (including local OpenAI-compatible
    servers) use the plain `OpenAI` client.
    """
    config = resolve_model_config(alias)
    if config.is_azure:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=config.azure_endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
    else:
        from openai import OpenAI

        client = OpenAI(base_url=config.base_url, api_key=config.api_key)
    return client, config.deployment


def describe_model_error(alias: str, exc: Exception) -> str:
    """Describe a model-call failure without echoing credentials or endpoints.

    The UI previously reported every live failure as "unconfigured model or
    endpoint error", which hid genuinely different causes (missing credentials,
    network/firewall denial, unreachable local server). Only the alias, the
    exception class, and an HTTP status code are surfaced — never the API key,
    endpoint URL, or request body (specs/05 FIX-C2).
    """
    name = type(exc).__name__
    if isinstance(exc, ModelConfigurationError):
        return f"{alias}: no endpoint or credentials configured for this model alias."
    from pipeline.protection import ProtectionError
    if isinstance(exc, ProtectionError):
        return f"{alias}: protected clinical values were not preserved; translation was rejected."
    if isinstance(exc, ValueError):
        return f"{alias}: input or model-output validation failed; no checked packet was produced."
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return (
            f"{alias}: access denied by the model endpoint (HTTP {status}) — "
            "the credential or this host's network is not permitted."
        )
    if status == 404:
        return f"{alias}: model deployment not found at the configured endpoint (HTTP 404)."
    if status == 429:
        return f"{alias}: model endpoint rate-limited the request (HTTP 429)."
    if name in ("APIConnectionError", "APITimeoutError"):
        return f"{alias}: could not reach the model endpoint ({name})."
    if status:
        return f"{alias}: model call failed ({name}, HTTP {status})."
    return f"{alias}: model call failed ({name})."
