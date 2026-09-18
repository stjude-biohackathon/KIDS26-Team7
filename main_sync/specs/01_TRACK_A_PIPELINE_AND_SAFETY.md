# 01: Track A Specification — Pipeline, Quality Gates & Safety Judge

**Assigned**: Participant 1  
**Module Directory**: `pipeline/`  
**Test Suite**: `tests/test_pipeline.py`, `tests/test_llm_config.py`

---

## 1. Responsibilities & Objectives
Participant 1 owns the multi-LLM generation, translation, and safety verification engine:
1. **Vetted English Composition**: Binds supplied versioned wording and structured orders. LLM1 then simplifies English while preserving clinical facts and protected values.
2. **Automated Quality Gate**: Measures FKGL readability via `textstat` and validates verbatim preservation of critical numbers using regex.
3. **LLM2 Safety Judge**: Performs zero-shot safety audit checking for factual drift, omitted red flags, and dangerous contradictions.
4. **Dual Translation**: Forward translation to Spanish (LLM1) and back-translation to English (LLM2) to expose translation drift.
5. **Scenario C Drift Simulator**: Negative testing module that injects synthetic hallucinations to prove quality gates catch errors.

---

## 2. Component Specifications

### 2.1 Vetted English Composer (`pipeline/orchestrator.py`)
- `compose_clinical_text` binds template placeholders and appends supplied structured order fields when required values are absent. It does not invent clinical instructions.
- LLM1 performs protected English simplification followed by protected Spanish translation. English must measure FKGL 5.0–6.9 after restoration. Retry from the original composed source with score feedback, at most three attempts; an unmet target raises an explicit readability error before translation.
- Inputs: versioned clinical source and `ClinicalOrders`; output: `simplified_en` (LLM1 plain-language English for clinician review).
- Target FKGL is 5.0–6.9 inclusive. Manual edits are not automatically rewritten; live rechecking measures them and an out-of-range score blocks approval.

### 2.2 Automated Quality Gate (`pipeline/evaluator.py`)
- **Readability Metric**:
  - Implementation: `textstat.flesch_kincaid_grade(text)`.
  - Pass Criteria: Finite score in 5.0–6.9 inclusive; anything outside this range blocks approval.
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

### 2.4 Optional Bilingual Dual Translation
- The UI defaults to English-only and passes `translate=False` to `generate_live` and `recheck_edits_live`; skip both translation calls and leave both fields empty. LLM2 still judges English, and all English readability/value gates apply. The API retains `translate=True` as its compatibility default; UI callers always pass the explicit family preference.
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
Provides 4 selectable synthetic error injections, operating on independent revisions:
1. **Contradictory Advice**: "Withhold anti-emetic medications until patient vomits 5 times."
2. **Altered Fever Threshold**: Adds 4.1 to supplied temperature values, preserving units (e.g. `100.4°F` -> `104.5°F`).
3. **Altered Medication Dose**: Doubles a supplied medication dose (e.g., `280 mg` -> `560 mg`).
4. **Omitted Red Flag**: Removes a detected source warning line.

No matching value/warning means the requested injection fails explicitly. Packets are marked `is_simulation`, retain parent revision identity, and cannot be approved. Tests inspect content changes, not merely the scenario label.

### 2.7 Protection and Final Safety Vetoes
- A protection failure with a model response returns a `PENDING` review-only draft instead of discarding it. `EvaluationMetrics.protection_failures` lists missing/duplicated values with occurrence counts, unexpected numbers, and unknown/altered markers, labeled by pipeline stage.
- Restore exact known markers for display only; never insert missing values or guess corrupted markers. Unrecoverable markers display `[UNRESOLVED PROTECTED VALUE]`. Failures stay in session memory and never appear in exception text or logs.
- Stop at the failed stage and retain all available panes; downstream translation/back-translation and model judging are skipped. The review verdict is deterministically `FLAGGED_FOR_REVIEW`, not a claimed completed model audit.
- Fresh English rechecks compare numeric values and occurrence counts against composed source/orders, including source-only values and unresolved placeholders. A repaired draft creates a new revision; successful checks clear failures only on that revision. Approval, approved PDF export, and approved library saving reject unresolved protection failures.
- Configuration/transport failures without a usable response still fail explicitly. FKGL-only retries retain the existing three-attempt limit; this draft-recovery behavior applies to protected-value failures.

- Simplification/translation/back-translation inputs mask numeric values and associated units before model calls. Restoration requires the exact sentinel multiset and rejects invented numbers.
- Judge inputs are masked too; complete typed audit fields are required. Invalid, incomplete, or unavailable audits yield `FLAGGED_FOR_REVIEW`.
- Required values must survive in English and, when requested, Spanish and back-translation. Additional unsupplied doses/thresholds/phone numbers and out-of-range FKGL block approval even if the judge says PASS. Warnings may be rephrased; the judge checks their meaning and reported omissions or contradictions block approval regardless of verdict.
- These conservative checks do not certify clinical meaning. Authorized Spanish review remains a separate per-revision human attestation.

---

## 3. Test-Driven Development (TDD) Milestones
1. **Unit Tests (`tests/test_pipeline.py`)**:
   - `test_readability_calculation()`: Confirms FKGL scoring accuracy.
   - `test_verbatim_regex()`: Validates that exact doses, temperatures, and phone numbers are matched and missing ones flagged.
   - `test_drift_simulator()`: Verifies that injected errors cause verbatim lock failures and Safety Judge flags.
2. **Configuration Tests (`tests/test_llm_config.py`)**:
   - Tests model resolution across all 6 model IDs.
   - Tests that API keys and endpoints are never printed or leaked to logs.
