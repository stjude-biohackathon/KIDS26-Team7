# 01: Track A Specification — Pipeline, Quality Gates & Safety Judge

**Assigned**: Participant 1  
**Module Directory**: `pipeline/`  
**Test Suite**: `tests/test_pipeline.py`, `tests/test_llm_config.py`

---

## 1. Responsibilities & Objectives
Participant 1 owns the multi-LLM generation, translation, and safety verification engine:
1. **LLM1 Plain-Language Simplification**: Rewrites clinical instructions into 5th–6th grade language while preserving critical orders.
2. **Automated Quality Gate**: Measures FKGL readability via `textstat` and validates verbatim preservation of critical numbers using regex.
3. **LLM2 Safety Judge**: Performs zero-shot safety audit checking for factual drift, omitted red flags, and dangerous contradictions.
4. **Dual Translation**: Forward translation to Spanish (LLM1) and back-translation to English (LLM2) to expose translation drift.
5. **Scenario C Drift Simulator**: Negative testing module that injects synthetic hallucinations to prove quality gates catch errors.

---

## 2. Component Specifications

### 2.1 LLM1 Simplifier (`pipeline/orchestrator.py`)
- **System Prompt Requirements**:
  - Target Audience: Parents/guardians of pediatric patients.
  - Grade Level Constraint: 5th–6th grade reading level (FKGL 5.0–6.9).
  - Sentence Length: Maximum 15 words per sentence.
  - Active Voice: Use direct, second-person action instructions ("Give your child...", "Call immediately if...").
  - Anchor Preservation: Must copy medication names, numeric dosages, units, frequency, return temperature limits, and phone numbers without alteration.
- **Inputs**: `composite_template_text: str`, `orders: ClinicalOrders`.
- **Output**: `simplified_en: str`.

### 2.2 Automated Quality Gate (`pipeline/evaluator.py`)
- **Readability Metric**:
  - Implementation: `textstat.flesch_kincaid_grade(text)`.
  - Pass Criteria: Target 5.0 – 6.9 (flag if > 7.0 or < 4.0).
- **Verbatim Lock Extractor**:
  - Medication doses: Regex `r"(\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?))"`
  - Temperature thresholds: Regex `r"(\d{2,3}(?:\.\d+)?\s*°?[FC])"`
  - Phone numbers: Regex `r"(\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)"`
  - Matching Rule: Every token extracted from `orders` must exist verbatim in `simplified_en`. Mismatches populate `EvaluationMetrics.verbatim_mismatches`.

### 2.3 LLM2 Safety Judge (`pipeline/orchestrator.py`)
- **Prompt Architecture**:
  - Evaluates `simplified_en` against original `composite_template_text` and `clinical_orders`.
  - JSON output schema:
    ```json
    {
      "overall_verdict": "PASS | NEEDS_REVIEW | FLAGGED_FOR_REVIEW",
      "factual_drift_detected": false,
      "omitted_red_flags": [],
      "contradictory_advice": [],
      "clinical_risk_score": 0.0,
      "explanation": "Brief rationale"
    }
    ```
  - **Resilience Rule**: If the Safety Judge API fails or times out, catch the exception and mark `overall_verdict="FLAGGED_FOR_REVIEW"` without halting the clinician workflow.

### 2.4 Bilingual Dual Translation
- **Forward Translation (LLM1)**: Translates `simplified_en` into accessible Latin American Spanish (`translated_es`).
- **Back-Translation (LLM2)**: Translates `translated_es` back into English (`back_translated_en`).
- **Clinical Value**: Clinicians who do not speak Spanish can inspect the back-translation side-by-side to verify semantic fidelity.

### 2.5 Dynamic Model Resolution (`pipeline/llms.py`, `pipeline/orchestrator.py`)
- Supports dropdown choices: `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local1`, `local2`.
- Direct client instantiation:
  ```python
  client = OpenAI(base_url=target_url, api_key=api_key)
  ```
- Resolves credentials dynamically from `[model_name]` or role-based sections in `.streamlit/secrets.toml`.

### 2.6 Drift Simulator (Scenario C Negative Testing)
Provides 3 selectable error injections:
1. **Contradictory Advice**: "Withhold anti-emetic medications until patient vomits 5 times."
2. **Altered Fever Threshold**: Replaces `100.4°F` and `101.0°F` with `104.5°F` and `105.0°F`.
3. **Altered Medication Dose**: Doubles prescribed medication dose (e.g., `280 mg` -> `560 mg`).

---

## 3. Test-Driven Development (TDD) Milestones
1. **Unit Tests (`tests/test_pipeline.py`)**:
   - `test_readability_calculation()`: Confirms FKGL scoring accuracy.
   - `test_verbatim_regex()`: Validates that exact doses, temperatures, and phone numbers are matched and missing ones flagged.
   - `test_drift_simulator()`: Verifies that injected errors cause verbatim lock failures and Safety Judge flags.
2. **Configuration Tests (`tests/test_llm_config.py`)**:
   - Tests model resolution across all 6 model IDs.
   - Tests that API keys and endpoints are never printed or leaked to logs.
