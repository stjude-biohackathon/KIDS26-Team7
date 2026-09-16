# 04: Integration, Merge Verification & Acceptance Test Plan

## 1. Overview
This document specifies the integration testing protocol, merge gate checklists, and regression test commands used to unify the three participant tracks (`track-a`, `track-b`, `track-c`) into `main`. Frequent synchronization points ensure interface mismatches are caught early.

---

## 2. Synchronization Gates & Acceptance Criteria

### Sync Point 0: Interface & Scaffold Verification
- **Objective**: Confirm that all three tracks share the identical Pydantic data contract and test framework.
- **Merge Requirements**:
  1. `schemas/instruction_packet.py` merged to `main`.
  2. `tests/test_components.py` schema instantiation tests pass:
     ```bash
     python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
     ```
  3. Git branches created from `main`:
     - `feature/track-a-pipeline`
     - `feature/track-b-storage`
     - `feature/track-c-ui`

---

### Sync Point 1: Mocked End-to-End Loop Integration
- **Objective**: Merge mocked implementations to verify the core application loop without external dependencies.
- **Track Deliverables**:
  - **Track A**: Rule-based mock simplifier returning deterministic text, FKGL calculation, and regex verbatim checker.
  - **Track B**: Local mock data loader returning sample templates/orders, mock JSONL writer, and minimal PDF generator.
  - **Track C**: Streamlit 4-pane comparative layout connected to mock orchestrator and mock loader.
- **Merge Gate Commands**:
  ```bash
  python tests/test_components.py
  python -m py_compile app/clinician_ui.py
  ```
- **Acceptance Criteria**:
  - Clinician launches Streamlit dashboard (`streamlit run app/clinician_ui.py`).
  - Clicking "🚀 Generate Instructions" populates all 4 columns with mock data.
  - FKGL score and verbatim lock telemetry badges render properly.

---

### Sync Point 2: Live Integrations (GitHub App & Multi-LLM Pipeline)
- **Objective**: Replace mocks with live in-memory data streaming and live LLM generation.
- **Track Deliverables**:
  - **Track A**: Multi-model `PipelineOrchestrator` supporting `AVAILABLE_MODELS` (`gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local`), LLM1 simplifier/ES translation, and LLM2 Safety Judge/back-translation.
  - **Track B**: Live in-memory GitHub App loader (`storage/github_loader.py`) reading `[dataloader]` in `secrets.toml`, minting RS256 JWT, and decoding repository contents in-memory.
  - **Track C**: Dynamic model selection dropdowns, protocol version selectors, and in-memory data source badge.
- **Merge Gate Commands**:
  ```bash
  python tests/test_github_loader.py
  python tests/test_llm_config.py
  python tests/test_components.py
  ```
- **Acceptance Criteria**:
  - No local copies of `data/modules` or `data/orders` exist on disk.
  - Sidebar displays: `Source: ☁️ GitHub App (In-Memory, No Local Copy)`.
  - Live instruction generation successfully calls LLM1 and LLM2 using the models chosen in the sidebar dropdowns.

---

### Sync Point 3: Final Acceptance & Clinical Workflow Verification
- **Objective**: Full end-to-end clinical workflow testing across all 3 conditions and all 3 review outcomes.
- **Full Test Suite Execution**:
  ```bash
  source venv/bin/activate
  python tests/test_components.py
  python tests/test_github_loader.py
  python tests/test_llm_config.py
  python -m py_compile app/clinician_ui.py
  ```

---

## 3. Clinical Workflow Test Matrix

Execute the following test cases in the UI to confirm release readiness:

| Test ID | Condition Track | Action / Scenario | Expected Outcome | Verification Status |
|---|---|---|---|---|
| **TC-01** | `sickle_cell_pain` | Clean generation -> "Approve & publish" | Status = `APPROVED`; PDF shows "Approved by physician"; Gold record appended | [Pass] |
| **TC-02** | `fever_neutropenia` | Inline edit Col 2 -> "Save and check edits" | Status remains `PENDING`; FKGL re-scored; No Streamlit widget error | [Pass] |
| **TC-03** | `fever_neutropenia` | Post-edit -> "Approve & publish" | Status = `EDITED_AND_APPROVED`; PDF shows "Edited and approved by physician" | [Pass] |
| **TC-04** | `chemo_nausea_hydration` | Drift injection (Scenario C) -> "Reject & log drift" | Status = `REJECTED_DRIFT`; Reason logged; PDF shows "Rejected by physician" | [Pass] |
| **TC-05** | Any Track | Click `🔄` Data Refresh in Sidebar | `st.cache_data` cleared; remote protocols reloaded without restarting app | [Pass] |
| **TC-06** | Any Track | Select different LLM1 / LLM2 models | Correct base_url and deployment dispatched to OpenAI client | [Pass] |

---

## 4. Security & Privacy Audit Checklist

Before releasing or merging to `main`, verify the following compliance rules:
1. **Zero Data on Disk**: No clinical instruction templates, synthetic orders, or patient orders are stored in `data/modules/` or `data/orders/` in the local working directory.
2. **Zero Secret Printing**: No `print()` statements exist that output API keys, private keys, or tokens in any `.py` file.
3. **Synthetic PHI Safeguards**: All patient IDs follow the `SYN-PED-xxx` format; no real patient names or identifiers appear in code or logs.
4. **Resilient Safety Handling**: If LLM2 Safety Judge encounters a network or API issue, the packet is flagged (`FLAGGED_FOR_REVIEW`) and does not crash the UI.
