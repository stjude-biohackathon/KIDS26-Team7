# 00: Project Architecture, Team Roles & Iterative Schedule

## 1. Executive Summary
This project builds an AI-assisted pediatric discharge instruction simplification platform with clinician-in-the-loop review. It simplifies complex clinical instructions into plain-language, bilingual (English & Spanish) handouts targeted at a 5th–6th grade reading level, while enforcing strict verbatim locks on medication dosages, temperature return thresholds, and contact numbers.

The system is engineered to be built by three participants working in parallel across decoupled tracks with frequent, automated merge checkpoints:
- **Track A (Participant 1)**: LLM Pipeline, Quality Gates & Safety Judge
- **Track B (Participant 2)**: Data Integration, In-Memory GitHub App Loader & Exporters
- **Track C (Participant 3)**: Clinician Review UI/UX Dashboard (Streamlit)

---

## 2. Shared Canonical Interface Contract
All tracks build against a single source of truth defined in `schemas/instruction_packet.py`:
- `InstructionPacket`: Central state container holding clinical input, generated outputs, evaluation metrics, and physician review metadata.
- `ClinicalOrders` & `MedicationOrder`: Structured schema for patient diagnosis, prescribed drugs, fever limits, and emergency contacts.
- `EvaluationMetrics` & `SafetyJudgeResult`: Container for readability scores, verbatim match flags, and judge findings.
- **Rule**: No participant may modify `schemas/instruction_packet.py` without team consensus during a sync gate.

---

## 3. Git Branching & Merge Strategy

```
main ──────────●──────────────────●──────────────────●──────────────────● (Release)
               │ (Sync 0)         │ (Sync 1)         │ (Sync 2)         │ (Sync 3)
               ├───────────────┐  ├───────────────┐  ├───────────────┐  │
track-a ───────┴──[Mock Pipe]──┴──┴──[Live LLM]───┴──┴──[Safety Test]─┴─ (Track A)
track-b ───────┴──[Mock Data]──┴──┴──[GH App REST]┴──┴──[PDF Badges]──┴─ (Track B)
track-c ───────┴──[Mock UI]────┴──┴──[Live UI]────┴──┴──[Governance]──┴─ (Track C)
```

### Branch Rules
1. `main`: Always deployable and protected. Direct commits prohibited.
2. `feature/track-a-pipeline`: Participant 1 feature branch.
3. `feature/track-b-storage`: Participant 2 feature branch.
4. `feature/track-c-ui`: Participant 3 feature branch.
5. Merge requires:
   - All tests passing (`python tests/test_components.py`, `python tests/test_github_loader.py`, `python tests/test_llm_config.py`).
   - Clean py_compile on all modified files.
   - Code review approval by at least one other team member.

---

## 4. Iterative Merge Cadence & Checkpoints

### Sync Point 0: Interface Lock & Scaffolding (Day 1 Morning)
- **Goal**: Lock Pydantic schemas, verify environment setup, and establish test harness.
- **Gate Test**: `python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"` passes on all participant machines.

### Sync Point 1: Mocked End-to-End Core Loop (Day 1 Midday)
- **Goal**: Connect mocked components into a functional local pipeline without API costs.
- **Track A**: Returns deterministic rule-based simplified text, FKGL, and verbatim checks.
- **Track B**: Returns mock templates/orders and writes to local test JSONL.
- **Track C**: Streamlit dashboard renders 4 columns from mock orchestrator.
- **Gate Test**: Clinician UI launches, generates a mock packet, and displays 4-way comparative pane without errors.

### Sync Point 2: Live Integrations (Day 1 EOD / Day 2 Morning)
- **Goal**: Swap mocks for live external services.
- **Track A**: Connects live LLM1 (simplifier + Spanish) and LLM2 (Safety Judge + back-translation) with dynamic model routing.
- **Track B**: Implements live in-memory GitHub App REST loader (`stjude-biohackathon/team7-data`) with zero disk copies.
- **Track C**: Wires dynamic model dropdowns, version selectors, and inline editing re-evaluation.
- **Gate Test**: Full live run: GitHub App fetches data on the fly -> LLM1 simplifies -> LLM2 judges -> UI renders live stream.

### Sync Point 3: Production UX, Hardening & Exporters (Day 2 Afternoon)
- **Goal**: Feature freeze, safety verification, and polished artifacts.
- **Track A**: Drift Simulator (Scenario C negative testing) for detecting hallucinations.
- **Track B**: ReportLab bilingual PDF generator with physician verification badges.
- **Track C**: Physician review governance (`Approve & publish`, `Save and check edits`, `Reject & log drift`), Gold library viewer.
- **Gate Test**: Full validation across all three clinical tracks (`sickle_cell_pain`, `fever_neutropenia`, `chemo_nausea_hydration`). PDF export verified.

---

## 5. Daily Team Sync Cadence
- **09:00 Standup (15 min)**: Review previous sync point, unblock dependencies, confirm daily branch targets.
- **12:30 Integration Check (30 min)**: Run merge dry-runs on integration branches; resolve schema or signature mismatches.
- **17:00 EOD Merge & Demo (45 min)**: Merge approved PRs into `main`, run comprehensive test suite, demo progress to clinician advisors.
