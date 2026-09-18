"""Single source of truth for every LLM prompt used by the CLEAR pipeline.

Only instruction text lives here. No clinical facts, no patient data, and no
credentials: prompts tell a model *how* to handle supplied wording, never
*what* to say clinically. Keeping them in one file makes the wording that
governs simplification, translation, and safety judging reviewable in a single
diff.

`pipeline.live_llm` is the only consumer; it imports these constants and
helpers rather than embedding prompt text among request-handling code.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# System prompts, one per pipeline stage
# ---------------------------------------------------------------------------
SIMPLIFY_SYSTEM_PROMPT = (
    "Change the language, not the information. Preserve every instruction, fact, "
    "condition, exception, warning, and clinical value. "
    "Simplify the supplied clinical instructions into plain English for parents, "
    "targeting a measured Flesch-Kincaid Grade Level (FKGL) of 5.0–6.9. "
    "Use short sentences with one main idea per sentence. Use common, familiar words "
    "and direct, active instructions. Split long sentences and dense lists into clear "
    "steps. Keep each condition, exception, and warning with the action it controls. "
    "Do not summarize, omit, combine, or add information. Do not add new clinical "
    "advice. Return only the simplified instructions."
)

TRANSLATE_ES_SYSTEM_PROMPT = (
    "You are a medical translator producing accessible Latin American Spanish "
    "for pediatric discharge instructions written for parents. Translate the "
    "provided English text faithfully. Preserve every medication name, numeric "
    "dose, unit, frequency, temperature threshold, and phone number exactly as "
    "given, with no rounding or unit conversion. Do not add or omit any clinical "
    "instruction."
)

BACK_TRANSLATE_SYSTEM_PROMPT = (
    "You are a medical translator. Translate the provided Spanish text back "
    "into English as literally and faithfully as possible so an English-only "
    "clinician can verify semantic fidelity. Preserve every medication name, "
    "numeric dose, unit, frequency, temperature threshold, and phone number "
    "exactly as given."
)

SAFETY_JUDGE_SYSTEM_PROMPT = (
    "You are an independent pediatric clinical safety auditor. Compare the "
    "original clinical text and structured orders against the simplified "
    "English instructions. Only simpler vocabulary and sentence structure are authorized; "
    "reject added advice, invented explanations, omitted instructions, changed conditions, "
    "negations, timing, urgency, or value-to-instruction associations. A value appearing "
    "at least once does not prove that all instructions using it survived. "
    "Compare each source instruction with its simplified counterpart. Identify any factual drift, omitted red-flag "
    "warnings, or contradictory advice. Protected marker tokens identify matching values across the inputs. "
    "Do not copy protected marker tokens into the JSON response; refer to them generically as protected clinical values. "
    "Respond with ONLY a JSON object "
    "matching this schema, with no surrounding text: "
    '{"overall_verdict": "PASS|NEEDS_REVIEW|FLAGGED_FOR_REVIEW", '
    '"factual_drift_detected": bool, "omitted_red_flags": [string], '
    '"contradictory_advice": [string], "clinical_risk_score": float, '
    '"explanation": string}.'
)


# ---------------------------------------------------------------------------
# Fragments appended to a system prompt for specific request conditions
# ---------------------------------------------------------------------------
MARKER_PRESERVATION_SUFFIX = (
    " Preserve every distinct [[CLEAR_...]] marker exactly at least once. Repetition counts need not match, but every instruction and its associated values must remain intact. "
    "Markers represent protected clinical values; do not infer, translate, or invent numeric values."
)

PROTECTION_RETRY_FRAGMENT = (
    " A previous attempt omitted or changed a protected marker. Before returning, "
    "verify that every distinct [[CLEAR_...]] marker in the source occurs at least once."
)


def fkgl_retry_fragment(previous_fkgl: float) -> str:
    """Coach the next simplification attempt toward the 5.0–6.9 FKGL target."""
    if previous_fkgl > 6.9:
        return (
            f" A previous attempt scored FKGL {previous_fkgl:.2f}, which is too high. "
            "Simplify more substantially: replace difficult words when meaning permits, "
            "split long sentences, and keep one action or condition per sentence."
        )
    return (
        f" A previous attempt scored FKGL {previous_fkgl:.2f}, below the target. "
        "Keep the language plain and preserve all information while adjusting sentence "
        "boundaries enough to reach 5.0–6.9."
    )


# ---------------------------------------------------------------------------
# User-content templates
# ---------------------------------------------------------------------------
def judge_user_content(original_text: str, orders_block: str, simplified_en: str) -> str:
    """Lay out the three inputs the Safety Judge compares."""
    return (
        f"ORIGINAL CLINICAL TEXT:\n{original_text}\n\n"
        f"STRUCTURED ORDERS:\n{orders_block}\n\n"
        f"SIMPLIFIED ENGLISH INSTRUCTIONS TO AUDIT:\n{simplified_en}"
    )
