"""
Track B: In-Memory GitHub App REST Loader & Mock Data Loader.
Streams clinical instruction templates and synthetic orders directly into memory with ZERO disk copies.
Adheres strictly to specs/02_TRACK_B_DATA_AND_STORAGE.md.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import jwt
from pydantic import ValidationError

from schemas.instruction_packet import (
    ClinicalOrders,
    MedicationOrder,
)

# In-memory token cache: (token_str, expiry_timestamp)
_TOKEN_CACHE: Dict[str, Tuple[str, float]] = {}

# Provenance of the most recent fetch_remote_templates_and_orders() call, so the
# UI can report what actually happened instead of inferring it from credential
# presence (specs/05 FIX-B3/FIX-C1). Never holds credential material.
_LAST_LOAD_STATUS: Dict[str, Any] = {"source": "unknown", "error": None, "warnings": []}

# The upstream `instructions[].type` vocabulary does not fully match the
# authoritative `handout_template_structure[].section` names declared in the
# same file. These three placements were supplied by the clinical owner; the
# other three type values match a declared section name exactly.
_TYPE_TO_DECLARED_SECTION: Dict[str, str] = {
    "pain_management": "pain_or_symptom_management",
    "warning_sign": "warning_signs_watch_for",
    "hydration_nutrition": "supportive_home_care",
}


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


def get_last_load_status() -> Dict[str, Any]:
    """Report what the most recent live load actually did (specs/05 FIX-B3).

    Returns a copy containing `source` ("github_app" | "mock" | "unknown"),
    an `error` string when the live path failed, and non-fatal `warnings`
    (e.g. upstream JSON defects that were tolerated). Never contains
    credential material.
    """
    return {
        "source": _LAST_LOAD_STATUS.get("source", "unknown"),
        "error": _LAST_LOAD_STATUS.get("error"),
        "warnings": list(_LAST_LOAD_STATUS.get("warnings", [])),
    }


def _sanitize_error(exc: Exception) -> str:
    """Describe a failure without echoing credentials, tokens, or key paths."""
    if isinstance(exc, FileNotFoundError):
        return "Configured GitHub App private key file was not found."
    if isinstance(exc, json.JSONDecodeError):
        return (
            "Upstream JSON could not be parsed "
            f"({exc.msg} at line {exc.lineno} column {exc.colno})."
        )
    if isinstance(exc, ValidationError):
        return "Upstream order record did not match the canonical ClinicalOrders schema."
    if isinstance(exc, requests.RequestException):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        return f"GitHub API request failed: {type(exc).__name__}{suffix}."
    if isinstance(exc, (KeyError, ValueError, TypeError)):
        return f"Upstream data was unusable: {type(exc).__name__}."
    return f"Unexpected error during live load: {type(exc).__name__}."


def parse_json_tolerantly(raw_text: str, warnings: List[str], label: str) -> Any:
    """Parse strict JSON, retrying once for a trailing-comma defect.

    The upstream modules file currently carries a trailing comma, which strict
    `json.loads` rejects. Rather than hiding that, the lenient retry records a
    data-quality warning so the defect can be fixed at source. The repaired
    text is never written to disk.
    """
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", raw_text)
        parsed = json.loads(repaired)
        warnings.append(
            f"{label}: upstream JSON contained trailing comma(s); parsed leniently "
            "in memory. The source file should be corrected."
        )
        return parsed


def adapt_modules(raw: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Compose `{category: {version: template_text}}` from the upstream schema.

    Orders and binds clinician-authored `instruction_text` values only: no
    clinical prose is generated, paraphrased, or rewritten here. Section order
    follows the file's authoritative `handout_template_structure` declaration.
    """
    instructions = raw.get("instructions") or []
    if not instructions:
        raise ValueError("Upstream modules payload contained no instructions.")

    declared_sections = [
        entry.get("section", "")
        for entry in (raw.get("handout_template_structure") or [])
        if entry.get("section")
    ]
    declared_lookup = set(declared_sections)

    grouped: Dict[str, Dict[str, List[str]]] = {}
    for index, item in enumerate(instructions):
        category = item.get("category")
        text = item.get("instruction_text")
        item_type = item.get("type") or "instructions"
        if not category or not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"Upstream modules instruction at index {index} is missing "
                "category or instruction_text."
            )
        section = (
            item_type if item_type in declared_lookup
            else _TYPE_TO_DECLARED_SECTION.get(item_type, item_type)
        )
        grouped.setdefault(category, {}).setdefault(section, []).append(text)

    if not grouped:
        raise ValueError("Upstream modules payload contained no usable instructions.")

    # History metadata alone is not archived content. Only expose the version
    # whose actual instructions were fetched; never relabel current wording.
    current_version = raw.get("version")
    if not current_version:
        raise ValueError("Upstream modules payload is missing version metadata.")
    versions = [current_version]

    modules: Dict[str, Dict[str, str]] = {}
    for category, sections in grouped.items():
        ordered = [s for s in declared_sections if s in sections]
        ordered += [s for s in sections if s not in declared_lookup]
        blocks = []
        for section in ordered:
            heading = section.replace("_", " ").upper()
            body = "\n".join(f"- {line}" for line in sections[section])
            blocks.append(f"=== {heading} ===\n{body}")
        modules[category] = {version: "\n\n".join(blocks) for version in versions}
    return modules


def adapt_orders(raw: Dict[str, Any]) -> Dict[str, ClinicalOrders]:
    """Map upstream `synthetic_orders[]` records onto canonical `ClinicalOrders`.

    One record per category is exposed, preferring the record whose `version`
    matches the file's current `version`.
    """
    records = raw.get("synthetic_orders") or []
    if not records:
        raise ValueError("Upstream orders payload contained no synthetic_orders.")
    current_version = raw.get("version") or ""

    optional_field_map = (
        ("age", "patient_age"),
        ("urgent_fever_threshold", "temperature_threshold_urgent"),
        ("emergency_fever_threshold", "temperature_threshold_emergency"),
        ("daytime_phone", "clinic_phone_daytime"),
        ("after_hours_phone", "clinic_phone_after_hours"),
        ("emergency_phone", "emergency_contact"),
    )

    adapted: Dict[str, ClinicalOrders] = {}
    chosen_version: Dict[str, str] = {}
    for record in records:
        category = record.get("category")
        if not category:
            continue
        record_version = record.get("version", "")
        already = category in adapted
        if already and not (
            record_version == current_version and chosen_version.get(category) != current_version
        ):
            continue

        medications = [
            MedicationOrder(
                name=med.get("name", ""),
                dose=med.get("dose", ""),
                route=med.get("route") or "",
                frequency=med.get("frequency", ""),
                special_instructions=med.get("special_instructions", ""),
            )
            for med in (record.get("medications") or [])
        ]
        fields: Dict[str, Any] = {
            "patient_id": record.get("patient_synthetic_id", ""),
            "diagnosis": record.get("diagnosis", ""),
            "medications": medications,
            "order_id": record.get("order_id", ""),
            "order_version": record_version,
            # Remote Team7 data is authoritative. Explicit blanks prevent
            # canonical demo defaults from becoming clinical source content.
            "urgent_fever_threshold": "",
            "emergency_fever_threshold": "",
            "daytime_phone": "",
            "after_hours_phone": "",
            "emergency_phone": "",
        }
        # Replace explicit blanks only with values that actually exist upstream.
        for target, source in optional_field_map:
            value = record.get(source)
            if value:
                fields[target] = value

        adapted[category] = ClinicalOrders(**fields)
        chosen_version[category] = record_version

    if not adapted:
        raise ValueError("Upstream orders payload contained no usable records.")
    return adapted


def merge_order_safety_sections(
    modules: Dict[str, Dict[str, str]], raw_orders: Dict[str, Any]
) -> Dict[str, Dict[str, str]]:
    """Append hydration and red-flag wording that has no canonical schema field.

    `hydration_order` and `red_flag_symptoms[]` are safety-critical vetted text
    that `ClinicalOrders` cannot carry, so they are bound into the composed
    template text instead of being dropped. Text is copied verbatim.
    """
    current_version = raw_orders.get("version") or ""
    by_category: Dict[str, Dict[str, Any]] = {}
    chosen_version: Dict[str, str] = {}
    for record in raw_orders.get("synthetic_orders") or []:
        category = record.get("category")
        if not category:
            continue
        record_version = record.get("version", "")
        if category in by_category and not (
            record_version == current_version and chosen_version.get(category) != current_version
        ):
            continue
        by_category[category] = record
        chosen_version[category] = record_version

    merged: Dict[str, Dict[str, str]] = {}
    for category, versioned in modules.items():
        record = by_category.get(category)
        extra_blocks: List[str] = []
        if record:
            hydration = record.get("hydration_order")
            if hydration:
                extra_blocks.append(f"=== HYDRATION PLAN ===\n- {hydration}")
            red_flags = record.get("red_flag_symptoms") or []
            if red_flags:
                body = "\n".join(f"- {flag}" for flag in red_flags)
                extra_blocks.append(f"=== RED FLAG SYMPTOMS ===\n{body}")
        suffix = ("\n\n" + "\n\n".join(extra_blocks)) if extra_blocks else ""
        merged[category] = {
            version: text + suffix for version, text in versioned.items()
        }
    return merged


def fetch_remote_templates_and_orders(
    strict: bool = False,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, ClinicalOrders]]:
    """
    Fetches templates and orders on the fly.
    If GitHub App credentials are configured, streams remotely into memory.
    Otherwise, falls back to mock in-memory data fixtures.

    The outcome is always recorded in `get_last_load_status()` so callers can
    report the real provenance rather than assuming live data was used. With
    `strict=True` a live failure is raised instead of silently degrading.
    """
    warnings: List[str] = []
    if not is_github_app_configured():
        _LAST_LOAD_STATUS.update({
            "source": "mock",
            "error": "GitHub App credentials are not configured.",
            "warnings": warnings,
        })
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

        modules_raw = parse_json_tolerantly(modules_json, warnings, "modules")
        orders_raw = parse_json_tolerantly(orders_json, warnings, "orders")

        modules = merge_order_safety_sections(adapt_modules(modules_raw), orders_raw)
        orders = adapt_orders(orders_raw)

        _LAST_LOAD_STATUS.update({
            "source": "github_app", "error": None, "warnings": warnings,
        })
        return modules, orders
    except Exception as exc:
        # Broad catch keeps the clinician workflow usable, but the reason is
        # always recorded (and re-raised under strict=True) so the failure is
        # surfaced rather than masked.
        _LAST_LOAD_STATUS.update({
            "source": "mock", "error": _sanitize_error(exc), "warnings": warnings,
        })
        if strict:
            raise
        return load_mock_templates_and_orders()
