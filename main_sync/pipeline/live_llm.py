"""Live LLM1/LLM2 calls for Phase 2 (Track A).

Each function makes exactly one chat-completion request and returns plain
text or a parsed `SafetyJudgeResult`. Nothing here ever prints, logs, or
raises with request/response content that could contain a credential; the
`llms.get_client` helper is the only place credentials are read.
"""

from __future__ import annotations

import json
import math
from pipeline import prompts
from pipeline.protection import ProtectedText, ProtectionError
from pipeline.text_formatting import to_editor_plain_text

from schemas.instruction_packet import ClinicalOrders, SafetyJudgeResult


class _EmptyModelResponseError(ValueError):
    """A model request succeeded but did not contain usable text."""


# Prompt text lives in `pipeline.prompts`; these aliases keep the existing
# import paths working for callers and regression tests.
_SIMPLIFY_SYSTEM_PROMPT = prompts.SIMPLIFY_SYSTEM_PROMPT
_TRANSLATE_ES_SYSTEM_PROMPT = prompts.TRANSLATE_ES_SYSTEM_PROMPT
_BACK_TRANSLATE_SYSTEM_PROMPT = prompts.BACK_TRANSLATE_SYSTEM_PROMPT
_SAFETY_JUDGE_SYSTEM_PROMPT = prompts.SAFETY_JUDGE_SYSTEM_PROMPT


def _chat(
    client,
    deployment: str,
    system_prompt: str,
    user_content: str,
    *,
    preserve_markers_in_response: bool = True,
) -> str:
    if preserve_markers_in_response:
        system_prompt += prompts.MARKER_PRESERVATION_SUFFIX
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
        raise _EmptyModelResponseError("Model returned an empty response.")
    return content.strip()


def format_orders(orders: ClinicalOrders) -> str:
    """Render clinical instructions, excluding patient demographics."""
    lines = [f"Diagnosis: {orders.diagnosis}"]
    for med in orders.medications:
        lines.append(
            f"Medication: {med.name} | Dose: {med.dose} | Route: {med.route} | "
            f"Frequency: {med.frequency} | Notes: {med.special_instructions or ''}"
        )
    if orders.hydration_order:
        lines.append(f"Hydration: {orders.hydration_order}")
    if orders.urgent_fever_threshold:
        lines.append(f"Urgent fever threshold: {orders.urgent_fever_threshold}")
    if orders.emergency_fever_threshold:
        lines.append(f"Emergency fever threshold: {orders.emergency_fever_threshold}")
    lines.extend(f"Red flag: {item}" for item in orders.red_flag_symptoms)
    lines.extend(f"Contraindication: {item}" for item in orders.contraindications)
    if orders.daytime_phone:
        lines.append(f"Daytime phone: {orders.daytime_phone}")
    if orders.after_hours_phone:
        lines.append(f"After-hours phone: {orders.after_hours_phone}")
    if orders.emergency_phone:
        lines.append(f"Emergency contact: {orders.emergency_phone}")
    return "\n".join(lines)


def simplify_to_plain_language(
    client,
    deployment: str,
    composite_template_text: str,
    orders: ClinicalOrders,
    *,
    previous_fkgl: float | None = None,
    previous_protection_failure: bool = False,
) -> str:
    """LLM1: simplify existing wording without adding or changing instructions."""
    protected = ProtectedText(composite_template_text)
    prompt = prompts.SIMPLIFY_SYSTEM_PROMPT
    if previous_fkgl is not None:
        prompt += prompts.fkgl_retry_fragment(previous_fkgl)
    if previous_protection_failure:
        prompt += prompts.PROTECTION_RETRY_FRAGMENT
    response = _chat(client, deployment, prompt, protected.masked)
    try:
        restored = protected.restore(response)
    except ProtectionError as exc:
        raise ProtectionError(
            "Protected values failed validation; draft requires review.",
            draft_text=(to_editor_plain_text(exc.draft_text)
                        if exc.draft_text is not None else None),
            findings=exc.findings,
        ) from None
    return to_editor_plain_text(restored)


def translate_to_spanish(client, deployment: str, simplified_en: str) -> str:
    """LLM1: forward-translate the simplified English pane into Spanish."""
    protected = ProtectedText(simplified_en)
    return protected.restore(_chat(client, deployment, prompts.TRANSLATE_ES_SYSTEM_PROMPT, protected.masked))


def back_translate_to_english(client, deployment: str, translated_es: str) -> str:
    """LLM2: back-translate the Spanish pane into English to expose drift."""
    protected = ProtectedText(translated_es)
    return protected.restore(_chat(client, deployment, prompts.BACK_TRANSLATE_SYSTEM_PROMPT, protected.masked))


def _judge_failure(category: str) -> SafetyJudgeResult:
    """Return a safe diagnostic without including exceptions or model output."""
    messages = {
        "REQUEST_FAILED": "The Safety Judge request did not complete.",
        "EMPTY_RESPONSE": "The Safety Judge returned no review content.",
        "INVALID_JSON": "The Safety Judge response was not valid JSON.",
        "INVALID_SCHEMA": "The Safety Judge response did not match the required fields and types.",
        "PROTECTED_MARKER_ERROR": "The Safety Judge response contained an invalid protected marker.",
    }
    return SafetyJudgeResult(
        overall_verdict="FLAGGED_FOR_REVIEW",
        factual_drift_detected=False,
        omitted_red_flags=[],
        contradictory_advice=[],
        clinical_risk_score=0.0,
        explanation=f"{category}: {messages[category]} Manual review is required.",
        failure_category=category,
    )


def judge_safety(
    client, deployment: str, original_text: str, simplified_en: str, orders: ClinicalOrders
) -> SafetyJudgeResult:
    """LLM2: audit the simplified text for drift, omissions, and contradictions.

    Resilience rule (specs/01 Section 2.3): any request/parse failure is
    caught here and reported as FLAGGED_FOR_REVIEW rather than raised, so a
    Safety Judge outage never crashes the clinician workflow.
    """
    user_content = prompts.judge_user_content(
        original_text, format_orders(orders), simplified_en
    )
    try:
        protected = ProtectedText(user_content)
    except ProtectionError:
        return _judge_failure("PROTECTED_MARKER_ERROR")

    try:
        raw = _chat(
            client,
            deployment,
            prompts.SAFETY_JUDGE_SYSTEM_PROMPT,
            protected.masked,
            preserve_markers_in_response=False,
        )
    except _EmptyModelResponseError:
        return _judge_failure("EMPTY_RESPONSE")
    except Exception:
        return _judge_failure("REQUEST_FAILED")

    try:
        # Models sometimes wrap JSON in a code fence despite instructions.
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return _judge_failure("INVALID_JSON")

    try:
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
    except ProtectionError:
        return _judge_failure("PROTECTED_MARKER_ERROR")
    except Exception:
        # Invalid values are intentionally reduced to a category. Exception
        # details and raw output may contain clinical text and are never stored.
        return _judge_failure("INVALID_SCHEMA")
