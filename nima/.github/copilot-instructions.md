# CLEAR — Engineering, Architecture & Governance Guidelines

## 1. Build, Test, and Lint Commands

Use Python available in the environment (`python`).

- **Syntax & Compilation Validation**:
  ```bash
  python -m py_compile app/clinician_ui.py
  python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
  ```

- **Run Full Test Suites**:
  ```bash
  python tests/test_components.py
  python tests/test_github_loader.py
  python tests/test_llm_config.py
  ```

- **Run Single Test Files or Individual Test Cases**:
  ```bash
  # Run a specific test module
  python tests/test_pipeline.py

  # Run an individual test case or method via unittest
  python -m unittest tests/test_pipeline.py -k test_verbatim_regex
  python -m unittest tests/test_github_loader.py -k test_dataloader_section_parsing
  ```

- **Run Application Dashboard**:
  ```bash
  streamlit run app/clinician_ui.py
  ```

---

## 2. High-Level Architecture

The CLEAR system is an AI-assisted pediatric discharge instruction simplification platform with clinician-in-the-loop review. It simplifies clinical instructions to a 5th–6th grade reading level (FKGL 5.0–6.9) in bilingual (English & Spanish) formats while locking all clinical values (dosages, thresholds, contact numbers) verbatim.

The architecture decouples into three tracks centered around a canonical Pydantic interface contract:

```
                            ┌────────────────────────────┐
                            │ schemas/instruction_packet │ (Canonical Contract)
                            └─────────────┬──────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         │                                │                                │
         ▼                                ▼                                ▼
  [Track A: Pipeline]             [Track B: Storage]               [Track C: UI/UX]
  `pipeline/`                     `storage/`, `exporters/`         `app/`
  • LLM1 Simplifier (5-6th gr)    • In-Memory GitHub App Loader    • Streamlit 4-Pane Dashboard
  • Quality Gate: FKGL + Regex      (RS256 JWT, zero-disk stream)  • Dynamic LLM1/LLM2 Selectors
  • LLM2 Factual Safety Judge     • Versioned Library (JSONL)      • Protocol Version Selectors
  • LLM1 ES Translation           • Bilingual PDF Generator        • Inline Editing & Re-check
  • LLM2 Back-Translation (EN)      (ReportLab + Status Badges)    • Review Governance Gates
  • Scenario C Drift Simulator                                     • Library Record Viewer
```

### Core Subsystems & Responsibilities

- **Canonical Interface Contract (`schemas/instruction_packet.py`)**:
  - Authoritative models: `InstructionPacket`, `ClinicalOrders`, `MedicationOrder`, `EvaluationMetrics`, `SafetyJudgeResult`.
  - Serves as the single source of truth across all modules.

- **Track A: Pipeline, Quality Gate & Safety Judge (`pipeline/`)**:
  - `orchestrator.py` & `llms.py`: Dynamic client routing for models (`gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local1`, `local2`).
  - `evaluator.py`: Automated quality gates checking Flesch-Kincaid Grade Level via `textstat` and verbatim regex matching on critical anchors (doses: `mg|mL|mcg|g`, fever thresholds: `°[FC]`, phone numbers).
  - LLM2 Safety Judge: Audits simplified English against source clinical text for factual drift, omitted red flags, and contradictions; yields `PASS`, `NEEDS_REVIEW`, or `FLAGGED_FOR_REVIEW`.
  - Bilingual Translation Loop: LLM1 translates simplified English to Spanish; LLM2 back-translates Spanish to English for clinician verification.
  - Scenario C Drift Simulator: Injects synthetic clinical hallucinations for safety gate regression testing.

- **Track B: In-Memory Data Loader, Persistence & PDF Exporters (`storage/`, `exporters/`)**:
  - `github_loader.py`: In-memory data loader reading `[dataloader]` credentials in `.streamlit/secrets.toml`, minting RS256 JWTs, obtaining short-lived installation access tokens, and fetching remote files via GitHub REST Contents API directly into memory.
  - `gold_library.py`: Append-only versioned JSONL storage (`data/gold_library/versioned_instructions.jsonl`).
  - `pdf_generator.py`: ReportLab Platypus generator rendering 2-column bilingual handouts with physician verification banners (`Approved by physician`, `Edited and approved by physician`, `Rejected by physician`) and protocol version audit footers.

- **Track C: Clinician Review UI/UX Dashboard (`app/clinician_ui.py`)**:
  - Streamlit dashboard providing 4-way comparative columns: (1) Original Clinical Orders, (2) Simplified English Handout, (3) Spanish Translation, (4) Back-Translated English.
  - Telemetry badges displaying FKGL score, verbatim lock status, and safety judge verdicts.
  - Action workflow gates: "Save and check edits" (re-evaluates while retaining `PENDING`), "Approve & publish" (sole approval gate; sets `APPROVED` or `EDITED_AND_APPROVED`), and "Reject & log drift" (modal capturing drift taxonomy).

---

## 3. Key Conventions & Safety Governance

### Clinical Safety & Translation Governance
- **Spec-Driven Development (SDD):** `plan.md` and `specs/` are authoritative specifications. Build strictly to documented schemas, state machines, and API contracts.
- **Zero AI-Originated Clinical Prose:** Medical instructions originate solely from clinician-vetted templates and orders. LLMs only simplify syntactic complexity—never generate or re-invent clinical rules.
- **Sentinel Protection & Verbatim Parity:** Dosages, units, fever return limits, and phone numbers are locked via regex. Any unrounded/modified number or unit mismatch is a hard sign-off block.
- **Authorized Translation Gate:** Clinicians inspect back-translated English side-by-side with Spanish text to verify translation fidelity before sign-off.
- **Zero Real Patient Data & Zero Disk Storage:** Use synthetic patient IDs (`SYN-PED-xxx`) only. Clinical templates and order files fetched via GitHub App are streamed in-memory and must never be written to local disk (`data/modules/`, `data/orders/`).

### Streamlit UI State Management Conventions
- **Prevent Widget State Collisions:** Never programmatically overwrite widget keys (such as `st.session_state["txt_clinician_en"]`) downstream after `st.text_area(key="txt_clinician_en")` is instantiated. Use Streamlit two-way binding.
- **Review Status Transitions:**
  - "Save and check edits": Triggers automated re-scoring and re-translation of edits, but strictly keeps `status = PENDING`.
  - "Approve & publish": Checks if text was modified from original generation; sets `APPROVED` if untouched, or `EDITED_AND_APPROVED` if modified.
  - "Reject & log drift": Requires drift classification category and justification, setting `status = REJECTED_DRIFT`.

### Git Branching & Track Coordination
- Never commit directly to `main`. Work on dedicated track branches (`feature/track-a-pipeline`, `feature/track-b-storage`, `feature/track-c-ui` or user dedicated branches).
- Before starting work, pull branch updates (`git fetch --all && git pull`).
- Verify synchronization points through the integration test suite prior to opening PRs to `main`.

### Secrets & Security Rules
- Store all credentials (GitHub App IDs, private keys, LLM endpoints, API keys) in `.streamlit/secrets.toml`.
- Never print, log, or commit API keys, tokens, private keys, or `.streamlit/` folders.
- Ensure `data/` and `.streamlit/` directories are listed in `.gitignore`.
