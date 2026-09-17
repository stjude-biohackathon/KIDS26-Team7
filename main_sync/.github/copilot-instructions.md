# CLEAR (KIDS26-Team7) — Copilot Instructions

## Commands

### Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Application Execution
```bash
PYTHONPATH=. streamlit run app/clinician_ui.py
```

### Build & Syntax Validation
```bash
python3 -m py_compile schemas/instruction_packet.py app/clinician_ui.py app/mock_components.py pipeline/*.py tests/*.py
python3 -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
```

### Running Tests
- **Full Test Suite:**
  ```bash
  PYTHONPATH=. python3 -m unittest discover tests
  ```
- **Single Test Suite:**
  ```bash
  PYTHONPATH=. python3 -m unittest tests/test_ui_components.py
  PYTHONPATH=. python3 -m unittest tests/test_components.py
  PYTHONPATH=. python3 -m unittest tests/test_pipeline.py
  PYTHONPATH=. python3 -m unittest tests/test_llm_config.py
  ```
- **Single Test Method:**
  ```bash
  PYTHONPATH=. python3 -m unittest tests.test_ui_components.TestTrackCComponents.test_verbatim_extraction_and_evaluation
  PYTHONPATH=. python3 -m unittest tests.test_components.TestInstructionPacketSchema.test_clinical_orders_valid
  ```

---

## High-Level Architecture

CLEAR transforms complex pediatric discharge instructions into plain-language, bilingual (English & Spanish) family handouts at a **5th–6th grade reading level** with clinician-in-the-loop review. The system enforces strict verbatim locking of critical safety numbers (doses, return thresholds, emergency contacts).

The project is structured into three decoupled, spec-driven tracks around a canonical Pydantic schema:

```
                           ┌───────────────────────────┐
                           │ schemas/instruction_packet │ (Canonical Contract)
                           └─────────────┬─────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
  [Track A: Pipeline & Safety]      [Track B: Storage & Data]         [Track C: Clinician UI]
  `pipeline/`                       `storage/`, `exporters/`          `app/`
  • LLM1 Simplifier (5-6th grade)   • In-Memory GitHub App Loader     • 4-Way Streamlit Review UI
  • Quality Gate: FKGL Readability    (RS256 JWT, zero disk writes)   • Dynamic Model Selectors
  • Verbatim Lock Regex Engine      • Append-only JSONL Library       • Inline Two-Way Text Area
  • LLM2 Factual Safety Judge       • Bilingual ReportLab PDF         • Review Action Gates
  • Bilingual Dual Translation        with Physician Badges           • Scenario C Drift Simulator
    (LLM1 ES -> LLM2 Back-EN)
```

### Component Responsibilities & Data Flow
1. **Canonical Schema (`schemas/instruction_packet.py`)**: Authoritative definition of `InstructionPacket`, `ClinicalOrders`, `MedicationOrder`, `EvaluationMetrics`, and `SafetyJudgeResult`. All tracks exchange data strictly via these models.
   - `ClinicalOrders` uses: `age`, `urgent_fever_threshold`, `emergency_fever_threshold`, `daytime_phone`, `after_hours_phone`, `emergency_phone`.
   - `InstructionPacket` uses: `original_clinical_text`, `evaluation_metrics`, `simplified_en`, `translated_es`, `back_translated_en`, `status`, `physician_decision`, `rejection_reason`, `rejection_category`, `edited_by_physician`, `reviewed_at`.
2. **Track A — Pipeline & Safety (`pipeline/`)**:
   - `pipeline/orchestrator.py`: `PipelineOrchestrator.generate()` binds structured order values into supplied templates and returns a new `PENDING` packet with real evaluation metrics; multi-step LLM calls cover LLM1 English simplification, LLM1 Spanish translation, LLM2 back-translation, LLM2 Safety Judge. `recheck_edits()` returns a new pending revision with a new ID/timestamp, preserves the old packet, clears its review metadata, and invalidates the previous bilingual output.
   - Templates use Python `string.Template` placeholders: `$urgent_fever_threshold`, `$emergency_fever_threshold`, `$daytime_phone`, `$after_hours_phone`, `$emergency_phone`; `$medication_0_name`, `$medication_0_dose`, `$medication_0_route`, `$medication_0_frequency`, `$medication_0_special_instructions` (index N = Nth medication). `${medication_0_dose}` also works; `$$` is a literal `$`. Missing/malformed placeholders, blank templates, missing source/version metadata, or failed/nonfinite readability calculations raise `ValueError` — callers should display the error and keep the previous packet.
   - `pipeline/evaluator.py`: Computes Flesch-Kincaid Grade Level (FKGL target: 5.0–6.9; below 4.0 or above 7.0 also triggers a wider review flag) via `textstat` and extracts verbatim tokens (medication doses, fever limits, phone numbers) via regex to detect omissions. Repeated identical protected values count once; empty order fields are skipped.
   - `pipeline/llms.py`: Dynamic model dispatcher supporting `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, and `local` endpoints.
   - `python -m pipeline.demo` runs the four text outputs offline, with no APIs or file writes. See `pipeline/README.md` for the full Track A handoff notes.
3. **Track B — Data, Loader & Exporters (`storage/`, `exporters/`)**:
   - `storage/github_loader.py`: Streams clinical instruction modules and synthetic orders on the fly from `stjude-biohackathon/team7-data` via GitHub App REST API authentication (RS256 JWT minted from private key). **Zero disk copies** of data fixtures.
   - `storage/gold_library.py`: Logs reviewed packets to `data/gold_library/versioned_instructions.jsonl`.
   - `exporters/pdf_generator.py`: Generates 2-column bilingual print-ready PDF handouts with physician verification banners (`Approved by physician`, `Edited and approved by physician`, `Rejected by physician`).
4. **Track C — Clinician UI/UX (`app/clinician_ui.py`)**:
   - Streamlit dashboard displaying 4 comparative review columns: Original Clinical Text, Simplified English, Spanish Handout, and Back-Translated English.
   - Enforces action gates: "Save & Check Edits" (re-scores, keeps `PENDING`), "Approve & Publish" (`APPROVED` or `EDITED_AND_APPROVED`), and "Reject & Log Drift" (`REJECTED_DRIFT`).

---

## Key Conventions & Codebase Patterns

### 1. Spec-Driven & Test-Driven Development (SDD / TDD)
- Authoritative specs reside in `plan.md` and `specs/` (`00_OVERVIEW_AND_SCHEDULE.md` through `04_INTEGRATION_TEST_PLAN.md`).
- Changes to schemas in `schemas/instruction_packet.py` require multi-track consensus during sync gates.
- Core functions (especially verbatim matching, readability calculation, and token resolution) require failing unit tests prior to implementation.
- **Track-specific implementation**: before implementing, determine which participant/track (A, B, or C) the user is assigned to per `plan.md`/`specs/`, and only build the track(s) assigned to them. A user may be assigned more than one track.
- The rule-based/mock engine **binds supplied wording; it does not rewrite clinical prose**. Neutral synthetic examples used in tests/demo are not vetted clinical instructions, and mock Spanish/back-translation templates are not model-generated or human-authorized translations.

### 2. Clinical Safety & Verbatim Anchors
- **Zero AI-Originated Clinical Prose**: Medical facts originate strictly from validated instructions and structured orders.
- **Verbatim Lock Regexes**:
  - Doses: `r"(\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?))"`
  - Temperatures: `r"(\d{2,3}(?:\.\d+)?\s*°?[FC])"`
  - Phone Numbers: `r"(\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)"`
  Every token in `ClinicalOrders` must appear verbatim in `simplified_en`. Mismatches populate `EvaluationMetrics.verbatim_mismatches`.
- **Authorized Translation Gate**: All patient-facing Spanish guidance must be vetted by authorized personnel (or dual LLM translation + back-translation verification).
- **Fail-Safe Safety Judge**: If the LLM2 Safety Judge API fails or times out, catch the exception and mark `overall_verdict="FLAGGED_FOR_REVIEW"` rather than crashing the workflow.

### 3. Streamlit State Invariants
- **`sys.path` Resolution**: Streamlit sets `sys.path[0]` to `app/`. Project root must be resolved and added to `sys.path` before top-level imports (`from schemas.instruction_packet import ...`).
- **Widget State Binding**: Never assign directly to `st.session_state["txt_clinician_en"]` after `st.text_area(key="txt_clinician_en")` is instantiated to prevent `StreamlitWidgetAlreadyInstantiatedError`.
- **Review Status Transition**:
  - "Save & Check Edits" triggers re-evaluation and updates translation/back-translation, but **must keep status as `PENDING`**.
  - Only "Approve & Publish" sets status to `APPROVED` (if unmodified) or `EDITED_AND_APPROVED` (if modified).

### 4. Zero-Disk Streaming & Privacy Governance
- **Zero Real Patient Data & Zero Disk Writes**: Use synthetic, de-identified fixtures only. Never cache or write clinical instruction templates or synthetic patient data (`SYN-PED-xxx`) to disk. Data must stream in-memory through `storage/github_loader.py`.
- **Secrets Governance**:
  - Do not commit `.streamlit/secrets.toml` or any credentials. Instruct users to move `.streamlit` to their home directory or add to `.gitignore`.
  - Do not print, log, or commit private keys, JWTs, or API keys.
  - Do not commit `data/` directory contents.

### 5. Git Branching & Track Discipline
- Never commit directly to `main`.
- Work on assigned participant/feature branches (e.g. `ramzi` or `feature/track-c-ui`).
- Fetch and pull before starting work:
  ```bash
  git checkout <branch>
  git fetch --all
  git pull
  ```
- Pause at designated synchronization points defined in `specs/00_OVERVIEW_AND_SCHEDULE.md` and instruct the user to commit, push, and open a PR into `main`.
