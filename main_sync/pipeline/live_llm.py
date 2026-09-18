"""Live LLM1/LLM2 calls for Phase 2 (Track A).

Each function makes exactly one chat-completion request and returns plain
text or a parsed `SafetyJudgeResult`. Nothing here ever prints, logs, or
raises with request/response content that could contain a credential; the
`llms.get_client` helper is the only place credentials are read.
"""

from __future__ import annotations

import json
import math
from pipeline.protection import ProtectedText

from schemas.instruction_packet import ClinicalOrders, SafetyJudgeResult

_TRANSLATE_ES_SYSTEM_PROMPT = (
    "You are a medical translator producing accessible Latin American Spanish "
    "for pediatric discharge instructions written for parents. Translate the "
    "provided English text faithfully. Preserve every medication name, numeric "
    "dose, unit, frequency, temperature threshold, and phone number exactly as "
    "given, with no rounding or unit conversion. Do not add or omit any clinical "
    "instruction."
)

_BACK_TRANSLATE_SYSTEM_PROMPT = (
    "You are a medical translator. Translate the provided Spanish text back "
    "into English as literally and faithfully as possible so an English-only "
    "clinician can verify semantic fidelity. Preserve every medication name, "
    "numeric dose, unit, frequency, temperature threshold, and phone number "
    "exactly as given."
)

_SAFETY_JUDGE_SYSTEM_PROMPT = (
    "You are an independent pediatric clinical safety auditor. Compare the "
    "original clinical text and structured orders against the simplified "
    "English instructions. Identify any factual drift, omitted red-flag "
    "warnings, or contradictory advice. Respond with ONLY a JSON object "
    "matching this schema, with no surrounding text: "
    '{"overall_verdict": "PASS|NEEDS_REVIEW|FLAGGED_FOR_REVIEW", '
    '"factual_drift_detected": bool, "omitted_red_flags": [string], '
    '"contradictory_advice": [string], "clinical_risk_score": float, '
    '"explanation": string}.'
)


def _chat(client, deployment: str, system_prompt: str, user_content: str) -> str:
    system_prompt += (
        " Preserve every [[CLEAR_...]] marker exactly, including its occurrence count. "
        "Markers represent protected clinical values; do not infer, translate, or invent numeric values."
    )
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("Model returned an empty response.")
    return content.strip()


def format_orders(orders: ClinicalOrders) -> str:
    """Render only the structured fields an LLM needs to preserve verbatim."""
    lines = [f"Diagnosis: {orders.diagnosis}", f"Age: {orders.age or 'unspecified'}"]
    for med in orders.medications:
        lines.append(
            f"Medication: {med.name} | Dose: {med.dose} | Route: {med.route} | "
            f"Frequency: {med.frequency} | Notes: {med.special_instructions or ''}"
        )
    lines.append(f"Urgent fever threshold: {orders.urgent_fever_threshold}")
    lines.append(f"Emergency fever threshold: {orders.emergency_fever_threshold}")
    lines.append(f"Daytime phone: {orders.daytime_phone}")
    lines.append(f"After-hours phone: {orders.after_hours_phone}")
    lines.append(f"Emergency phone: {orders.emergency_phone}")
    return "\n".join(lines)


def simplify_to_plain_language(client, deployment: str, composite_template_text: str, orders: ClinicalOrders) -> str:
    """LLM1: rewrite the clinical text at a 5th-6th grade level."""
    raise ValueError("AI rewriting of clinical English is disabled; use supplied versioned wording.")


def translate_to_spanish(client, deployment: str, simplified_en: str) -> str:
    """LLM1: forward-translate the simplified English pane into Spanish."""
    protected = ProtectedText(simplified_en)
    return protected.restore(_chat(client, deployment, _TRANSLATE_ES_SYSTEM_PROMPT, protected.masked))


def back_translate_to_english(client, deployment: str, translated_es: str) -> str:
    """LLM2: back-translate the Spanish pane into English to expose drift."""
    protected = ProtectedText(translated_es)
    return protected.restore(_chat(client, deployment, _BACK_TRANSLATE_SYSTEM_PROMPT, protected.masked))


def judge_safety(
    client, deployment: str, original_text: str, simplified_en: str, orders: ClinicalOrders
) -> SafetyJudgeResult:
    """LLM2: audit the simplified text for drift, omissions, and contradictions.

    Resilience rule (specs/01 Section 2.3): any request/parse failure is
    caught here and reported as FLAGGED_FOR_REVIEW rather than raised, so a
    Safety Judge outage never crashes the clinician workflow.
    """
    user_content = (
        f"ORIGINAL CLINICAL TEXT:\n{original_text}\n\n"
        f"STRUCTURED ORDERS:\n{format_orders(orders)}\n\n"
        f"SIMPLIFIED ENGLISH INSTRUCTIONS TO AUDIT:\n{simplified_en}"
    )
    try:
        protected = ProtectedText(user_content)
        raw = _chat(client, deployment, _SAFETY_JUDGE_SYSTEM_PROMPT, protected.masked)
        # Models sometimes wrap JSON in a code fence despite instructions.
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        payload = json.loads(cleaned)
        required = {"overall_verdict", "factual_drift_detected", "omitted_red_flags", "contradictory_advice", "clinical_risk_score", "explanation"}
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise ValueError("Incomplete judge audit.")
        if payload["overall_verdict"] not in {"PASS", "NEEDS_REVIEW", "FLAGGED_FOR_REVIEW"}:
            raise ValueError("Invalid verdict.")
        if type(payload["factual_drift_detected"]) is not bool or not isinstance(payload["explanation"], str):
            raise ValueError("Invalid audit field type.")
        for name in ("omitted_red_flags", "contradictory_advice"):
            if not isinstance(payload[name], list) or not all(isinstance(v, str) for v in payload[name]):
                raise ValueError("Invalid finding list.")
            payload[name] = [protected.restore(v, require_all=False) for v in payload[name]]
        score = payload["clinical_risk_score"]
        if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid risk score.")
        return SafetyJudgeResult(
            overall_verdict=payload.get("overall_verdict", "NEEDS_REVIEW"),
            factual_drift_detected=bool(payload.get("factual_drift_detected", False)),
            omitted_red_flags=list(payload.get("omitted_red_flags", [])),
            contradictory_advice=list(payload.get("contradictory_advice", [])),
            clinical_risk_score=float(payload.get("clinical_risk_score", 0.0)),
            explanation=protected.restore(str(payload.get("explanation", "")), require_all=False),
        )
    except Exception:
        # Do not include exception details: they may echo request/response
        # content, and the resilience rule only requires a safe fallback verdict.
        return SafetyJudgeResult(
            overall_verdict="FLAGGED_FOR_REVIEW",
            factual_drift_detected=False,
            omitted_red_flags=[],
            contradictory_advice=[],
            clinical_risk_score=0.0,
            explanation="Safety Judge call failed or returned an unparseable response; flagged for manual review.",
        )
