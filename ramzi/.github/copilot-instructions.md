# CLEAR (KIDS26-Team7) — Copilot Instructions

## Commands

### Environment Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Application Execution
```bash
streamlit run app/clinician_ui.py
```

### Build & Syntax Validation
```bash
python -m py_compile app/clinician_ui.py
python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
```

### Running Tests
- **Full Test Suite:**
  ```bash
  python tests/test_components.py
  python tests/test_pipeline.py
  python tests/test_github_loader.py
  python tests/test_llm_config.py
  ```
- **Single Test Suite (Unittest or Pytest):**
  ```bash
  python -m unittest tests/test_pipeline.py
  pytest tests/test_pipeline.py
  ```
- **Single Test Method:**
  ```bash
  python -m unittest tests.test_pipeline.TestPipeline.test_verbatim_regex
  pytest tests/test_pipeline.py -k "test_verbatim_regex"
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
1. **Canonical Schema (`schemas/instruction_packet.py`)**: Defines `InstructionPacket`, `ClinicalOrders`, `MedicationOrder`, `EvaluationMetrics`, and `SafetyJudgeResult`. All modules exchange data through this contract.
2. **Track A — Pipeline & Safety (`pipeline/`)**:
   - `pipeline/orchestrator.py`: Orchestrates multi-step LLM calls (LLM1 English simplification, LLM1 Spanish translation, LLM2 back-translation, LLM2 Safety Judge).
   - `pipeline/evaluator.py`: Computes Flesch-Kincaid Grade Level (FKGL target: 5.0–6.9) via `textstat` and extracts verbatim tokens (medication doses, fever limits, phone numbers) via regex to detect omissions.
   - `pipeline/llms.py`: Dynamic model dispatcher supporting `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, and `local` endpoints.
3. **Track B — Data, Loader & Exporters (`storage/`, `exporters/`)**:
   - `storage/github_loader.py`: Streams clinical instruction modules and synthetic orders on the fly from `stjude-biohackathon/team7-data` via GitHub App REST API authentication (RS256 JWT minted from private key). **Zero disk copies** of data fixtures.
   - `storage/gold_library.py`: Logs reviewed packets to `data/gold_library/versioned_instructions.jsonl`.
   - `exporters/pdf_generator.py`: Generates 2-column bilingual print-ready PDF handouts with physician verification banners (`Approved by physician`, `Edited and approved by physician`, `Rejected by physician`).
4. **Track C — Clinician UI/UX (`app/clinician_ui.py`)**:
   - Streamlit dashboard displaying 4 comparative review columns: Original Clinical Text, Simplified English, Spanish Handout, and Back-Translated English.
   - Enforces action gates: "Save and check edits" (re-scores, keeps `PENDING`), "Approve & publish" (`APPROVED` or `EDITED_AND_APPROVED`), and "Reject & log drift" (`REJECTED_DRIFT`).

---

## Key Conventions & Codebase Patterns

### 1. Spec-Driven & Test-Driven Development (SDD / TDD)
- Authoritative specs reside in `plan.md` and `specs/` (`00_OVERVIEW_AND_SCHEDULE.md` through `04_INTEGRATION_TEST_PLAN.md`).
- Changes to schemas in `schemas/instruction_packet.py` require multi-track consensus during sync gates.
- Core functions (especially verbatim matching, readability calculation, and token resolution) require failing unit tests prior to implementation.

### 2. Clinical Safety & Verbatim Anchors
- **Zero AI-Originated Clinical Prose**: Medical facts originate strictly from validated instructions and structured orders.
- **Verbatim Lock Regexes**:
  - Doses: `r"(\d+(?:\.\d+)?\s*(?:mg|mL|mcg|g|tablets?|capsules?|drops?))"`
  - Temperatures: `r"(\d{2,3}(?:\.\d+)?\s*°?[FC])"`
  - Phone Numbers: `r"(\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)"`
  Every token in `orders` must appear verbatim in `simplified_en`. Mismatches populate `EvaluationMetrics.verbatim_mismatches`.
- **Fail-Safe Safety Judge**: If the LLM2 Safety Judge API fails or times out, catch the exception and mark `overall_verdict="FLAGGED_FOR_REVIEW"` rather than crashing the workflow.

### 3. Streamlit State Invariants
- **Widget State Binding**: Never assign directly to `st.session_state["txt_clinician_en"]` after `st.text_area(key="txt_clinician_en")` is instantiated. This causes `StreamlitWidgetAlreadyInstantiatedError`.
- **Review Status Transition**:
  - "Save and check edits" triggers re-evaluation and updates translation/back-translation, but **must keep status as `PENDING`**.
  - Only "Approve & publish" sets status to `APPROVED` (if unmodified) or `EDITED_AND_APPROVED` (if modified).

### 4. Zero-Disk Streaming & Privacy Governance
- **Zero Disk Writes**: Never cache or write clinical instruction templates or synthetic patient data (`SYN-PED-xxx`) to disk. Data must stream in-memory through `storage/github_loader.py`.
- **Secrets Governance**:
  - Do not commit `.streamlit/secrets.toml` or any credentials.
  - Do not print, log, or commit private keys, JWTs, or API keys.
  - Do not commit `data/` directory contents.

### 5. Git Branching Discipline
- Never commit directly to `main`.
- Work on assigned track feature branches (`feature/track-a-pipeline`, `feature/track-b-storage`, `feature/track-c-ui`, or the assigned participant branch).
- Verify `py_compile` and unit test suites pass before opening PRs for merge sync points.
