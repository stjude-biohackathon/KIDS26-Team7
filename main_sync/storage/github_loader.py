"""
Track B: In-Memory GitHub App REST Loader & Mock Data Loader.
Streams clinical instruction templates and synthetic orders directly into memory with ZERO disk copies.
Adheres strictly to specs/02_TRACK_B_DATA_AND_STORAGE.md.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests
import jwt

from schemas.instruction_packet import (
    ClinicalOrders,
    MedicationOrder,
)

# In-memory token cache: (token_str, expiry_timestamp)
_TOKEN_CACHE: Dict[str, Tuple[str, float]] = {}


def load_mock_templates_and_orders() -> Tuple[Dict[str, Dict[str, str]], Dict[str, ClinicalOrders]]:
    """
    Returns standard in-memory clinical instruction templates and synthetic orders for Phase 1.
    Guarantees zero-disk writes.
    """
    modules: Dict[str, Dict[str, str]] = {
        "sickle_cell_pain": {
            "v1.2.0": (
                "CLINICAL PROTOCOL: SICKLE CELL ACUTE VASO-OCCLUSIVE CRISIS\n\n"
                "Pathophysiology: Intravascular sickling causes microvascular occlusion leading to ischemia.\n"
                "Hydration Strategy: Aggressive oral hydration at 1.5x maintenance with electrolyte solutions.\n"
                "Analgesic Protocol: Scheduled NSAIDs and oral opioids as prescribed. Titrate based on FLACC/Wong-Baker scale.\n"
                "Red Flag Triggers: Immediate presentation required for temperature >= 100.4°F, acute chest syndrome "
                "(tachypnea, chest pain, hypoxemia), sudden pallor, splenic enlargement, or priapism.\n"
                "Emergency Contact: St. Jude Triage 24/7 or nearest Pediatric Emergency Department."
            ),
            "v1.1.0": (
                "CLINICAL PROTOCOL: SICKLE CELL PAIN MANAGEMENT (LEGACY)\n\n"
                "Hydration and scheduled oral analgesia. Prompt evaluation for fever above 100.4°F."
            ),
        },
        "fever_neutropenia": {
            "v1.2.0": (
                "CLINICAL PROTOCOL: PEDIATRIC ONCOLOGY FEVER AND NEUTROPENIA (F&N)\n\n"
                "Absolute Neutrophil Count (ANC) < 500/mcL creates severe risk for overwhelming bacteremia.\n"
                "Definition of Fever: Single oral temp >= 101.0°F (38.3°C) or sustained >= 100.4°F (38.0°C) over 1 hour.\n"
                "Mandatory Action: Medical emergency. Do NOT administer antipyretics before blood cultures. "
                "Patient must arrive at clinic or emergency facility within 60 minutes for IV broad-spectrum antibiotics.\n"
                "Emergency Contact: 24/7 Triage: 901-595-3300. Call 911 if lethargic or unresponsive."
            ),
            "v1.1.0": (
                "CLINICAL PROTOCOL: FEVER AND NEUTROPENIA GUIDELINE (v1.1)\n\n"
                "Prompt evaluation for fever >= 100.4°F in neutropenic patients. Immediate IV antibiotic coverage required."
            ),
        },
        "chemo_nausea_hydration": {
            "v1.2.0": (
                "CLINICAL PROTOCOL: POST-CHEMOTHERAPY NAUSEA, VOMITING & HYDRATION\n\n"
                "Emetogenic Risk Management: Administer ondansetron 4 mg every 8 hours scheduled for 48 hours post-infusion.\n"
                "Oral Hydration Target: Minimum 1200 mL oral fluids per 24 hours. Small frequent sips every 15 minutes.\n"
                "Threshold for Intervention: Return if unable to keep fluids down for > 8 hours, absence of wet diapers/urination "
                "for > 12 hours, dry mucous membranes, or persistent emesis > 4 episodes in 12 hours.\n"
                "Contact: Daytime Hematology/Oncology Clinic: 901-595-3300. Emergency: 911."
            ),
            "v1.1.0": (
                "CLINICAL PROTOCOL: CHEMOTHERAPY ANTI-EMETIC PROTOCOL (v1.1)\n\n"
                "Administer scheduled anti-emetics. Ensure minimum hydration. Contact clinic for persistent emesis."
            ),
        },
    }

    orders: Dict[str, ClinicalOrders] = {
        "sickle_cell_pain": ClinicalOrders(
            order_id="ORD-SCD-01",
            order_version="v1.2.0",
            patient_id="SYN-PED-001",
            age="8 years old",
            diagnosis="Sickle Cell Disease with acute vaso-occlusive pain",
            medications=[
                MedicationOrder(
                    name="Ibuprofen oral suspension",
                    dose="200 mg",
                    route="oral",
                    frequency="every 6 hours as needed with food",
                    special_instructions="Take with meals to prevent stomach upset.",
                ),
                MedicationOrder(
                    name="Oxycodone oral solution",
                    dose="5 mg",
                    route="oral",
                    frequency="every 4 hours as needed for severe pain",
                    special_instructions="Only use if pain is not controlled by ibuprofen.",
                ),
            ],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
            emergency_phone="911",
        ),
        "fever_neutropenia": ClinicalOrders(
            order_id="ORD-FN-01",
            order_version="v1.2.0",
            patient_id="SYN-PED-002",
            age="5 years old",
            diagnosis="B-ALL (Acute Lymphoblastic Leukemia) with post-chemo neutropenia",
            medications=[
                MedicationOrder(
                    name="Cefepime IV (Home/Infusion)",
                    dose="1000 mg",
                    route="IV",
                    frequency="every 8 hours",
                    special_instructions="Administer over 30 minutes via central line.",
                ),
            ],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
            emergency_phone="911",
        ),
        "chemo_nausea_hydration": ClinicalOrders(
            order_id="ORD-CNH-01",
            order_version="v1.2.0",
            patient_id="SYN-PED-003",
            age="12 years old",
            diagnosis="Osteosarcoma post-cisplatin infusion",
            medications=[
                MedicationOrder(
                    name="Ondansetron tablets",
                    dose="4 mg",
                    route="oral",
                    frequency="every 8 hours scheduled for 48 hours",
                    special_instructions="Give 30 minutes before meals.",
                ),
            ],
            urgent_fever_threshold="100.4°F",
            emergency_fever_threshold="101.0°F",
            daytime_phone="901-595-3300",
            after_hours_phone="901-595-3300",
            emergency_phone="911",
        ),
    }

    return modules, orders


def _read_streamlit_secrets_section(section: str) -> Dict[str, str]:
    """Read a `[section]` table via Streamlit's own secrets resolver.

    `st.secrets` transparently checks the global `~/.streamlit/secrets.toml`
    (where governance requires this project's secrets file to live) as well
    as any project-local `.streamlit/secrets.toml`. This function never opens,
    reads, or logs the file itself — it only calls Streamlit's own API and
    returns the parsed section as a plain dict.
    """
    try:
        import streamlit as st

        if section in st.secrets:
            return dict(st.secrets[section])
    except Exception:
        # No secrets file configured, not running under Streamlit, or the
        # section is absent -- all treated the same as "not configured".
        pass
    return {}


def get_dataloader_config() -> Dict[str, str]:
    """
    Parses dataloader configuration from Streamlit secrets (global
    ~/.streamlit/secrets.toml or project .streamlit/secrets.toml) or
    environment variables. Never prints or logs secret contents.
    """
    config: Dict[str, str] = {}

    # Preferred path: Streamlit's own secrets resolver (checks the user's
    # home directory first, per this project's secrets-governance rule).
    config.update(_read_streamlit_secrets_section("dataloader"))

    # Fallback for non-Streamlit contexts (e.g. plain scripts/tests) that
    # still keep a project-local .streamlit/secrets.toml.
    if not config:
        secrets_file = os.path.join(".streamlit", "secrets.toml")
        if os.path.exists(secrets_file):
            try:
                import toml
                data = toml.load(secrets_file)
                if "dataloader" in data:
                    config.update(data["dataloader"])
            except Exception:
                pass

    # Environment variables override or supplement
    env_keys = [
        "GITHUB_APP_ID",
        "GITHUB_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_DATA_REPO",
        "MODULES_PATH",
        "ORDERS_PATH",
    ]
    for k in env_keys:
        val = os.environ.get(k)
        if val:
            config[k] = val

    # Set defaults for repo and paths if not explicitly specified
    config.setdefault("GITHUB_DATA_REPO", "stjude-biohackathon/team7-data")
    config.setdefault("MODULES_PATH", "data/modules/pediatric_discharge_instruction_templates.json")
    config.setdefault("ORDERS_PATH", "data/orders/synthetic_orders.json")

    return config


def is_github_app_configured() -> bool:
    """Returns True if the required GitHub App credentials are provided."""
    cfg = get_dataloader_config()
    return bool(
        cfg.get("GITHUB_APP_ID")
        and cfg.get("GITHUB_INSTALLATION_ID")
        and cfg.get("GITHUB_APP_PRIVATE_KEY_PATH")
    )


def mint_jwt(app_id: str, private_key_pem: str) -> str:
    """Mints an RS256 JWT for GitHub App authentication valid for 10 minutes."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 570,
        "iss": str(app_id),
    }
    encoded = jwt.encode(payload, private_key_pem, algorithm="RS256")
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


def get_installation_access_token(
    app_id: str,
    installation_id: str,
    private_key_path: str,
) -> str:
    """
    Obtains a short-lived installation access token from GitHub API.
    Caches token in-memory for 50 minutes (zero disk persistence).
    """
    cache_key = f"{app_id}:{installation_id}"
    now = time.time()
    if cache_key in _TOKEN_CACHE:
        token, exp = _TOKEN_CACHE[cache_key]
        if now < exp:
            return token

    if not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key file not found: {private_key_path}")

    with open(private_key_path, "r", encoding="utf-8") as f:
        private_key_pem = f.read()

    jwt_token = mint_jwt(app_id, private_key_pem)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    resp = requests.post(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    token = data["token"]
    # Cache for 50 minutes (3000 seconds)
    _TOKEN_CACHE[cache_key] = (token, now + 3000)
    return token


def fetch_file_content_in_memory(
    repo: str,
    file_path: str,
    token: str,
) -> str:
    """
    Fetches raw file content via GitHub REST Contents API and decodes in-memory.
    Never writes payload to disk.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    content_b64 = payload.get("content", "")
    decoded_bytes = base64.b64decode(content_b64)
    return decoded_bytes.decode("utf-8")


def fetch_remote_templates_and_orders() -> Tuple[Dict[str, Dict[str, str]], Dict[str, ClinicalOrders]]:
    """
    Fetches templates and orders on the fly.
    If GitHub App credentials are configured, streams remotely into memory.
    Otherwise, gracefully falls back to mock in-memory data fixtures.
    """
    if not is_github_app_configured():
        return load_mock_templates_and_orders()

    cfg = get_dataloader_config()
    try:
        token = get_installation_access_token(
            cfg["GITHUB_APP_ID"],
            cfg["GITHUB_INSTALLATION_ID"],
            cfg["GITHUB_APP_PRIVATE_KEY_PATH"],
        )
        repo = cfg["GITHUB_DATA_REPO"]
        modules_json = fetch_file_content_in_memory(repo, cfg["MODULES_PATH"], token)
        orders_json = fetch_file_content_in_memory(repo, cfg["ORDERS_PATH"], token)

        modules_raw = json.loads(modules_json)
        orders_raw = json.loads(orders_json)

        parsed_orders: Dict[str, ClinicalOrders] = {}
        for k, v in orders_raw.items():
            parsed_orders[k] = ClinicalOrders.model_validate(v)

        return modules_raw, parsed_orders
    except Exception:
        # Graceful fallback to in-memory fixtures if remote network fails
        return load_mock_templates_and_orders()
