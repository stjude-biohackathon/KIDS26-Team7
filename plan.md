# AI-Assisted Patient Instruction Simplification with Clinician-in-the-Loop
## 2-Day Rapid Prototype & Demo Plan

---

## 1. Executive Summary & Objectives

### Purpose
Build and demonstrate a functional, clinician-in-the-loop prototype that transforms complex pediatric discharge instructions into plain-language, bilingual (English & Spanish) family handouts at a **5th–6th grade reading level**, while guaranteeing that critical clinical facts (doses, return thresholds, contact triggers) are preserved verbatim.

### Key Success Metrics for the 2-Day Demo
1. **End-to-End Execution across 3 Core Modules**:
   - Sickle Cell Pain (>10 templates in library)
   - Fever & Neutropenia (>10 templates in library)
   - Post-Chemo Nausea & Hydration (>10 templates in library)
2. **Safety & Factual Drift Safeguards**:
   - Automated verbatim regex lock on numeric doses, unit labels, fever thresholds, and phone numbers.
   - LLM2 judge detects omissions and factual drift with confidence scoring.
   - Clinician review UI supports three distinct workflow outcomes: **Approve**, **Inline Edit & Approve**, and **Reject due to Drift**.
3. **Dual Delivery Handouts**:
   - Clinician-reviewed, versioned record logged in JSONL/SQLite.
   - Dual-language, print-ready PDF generated dynamically.
   - Interactive responsive family-facing view.

---

## 2. End-to-End Pipeline Architecture

```
[Module Instruction (EN)] + [Synthetic Clinical Orders (EN)]
                      │
                      ▼
            ┌──────────────────┐
            │  LLM 1: Simplify │ ◄── Enforce 5th–6th grade + verbatim anchor tags
            └─────────┬────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │ Automated Quality Gate  │
         │  1. Readability (FKGL)  │
         │  2. Verbatim Extractor  │
         │  3. LLM 2 Judge (Drift) │
         └────────────┬────────────┘
                      │
                      ▼
            ┌──────────────────┐
            │ LLM 1: Translate │ (EN -> Spanish)
            └─────────┬────────┘
                      │
                      ▼
            ┌──────────────────┐
            │ LLM 2: Back-Trans│ (Spanish -> EN)
            └─────────┬────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │ Clinician Review UI     │
         │ • Original vs Simple    │
         │ • ES vs Back-Trans EN   │
         │ • Safety / Metric Badges│
         │ • [Approve|Edit|Reject] │
         └────────────┬────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Approved / Edited Log]   [Family Artifacts]
- Versioned Library            - Bilingual PDF (Print)
- Continuous Feedback Loop     - Interactive Mobile/Web Card
```

# Iterative 3-Track Spec-Driven Implementation Plan 

## Objective
Devise a comprehensive, test-driven, spec-driven blueprint to build an AI-assisted pediatric discharge instruction simplification platform with clinician-in-the-loop review. The work is divided into three parallel, decoupled participant tracks with strict interface contracts, progressive milestones, and frequent merge/test checkpoints.

---

## Architecture & Team Division

```
                           ┌───────────────────────────┐
                           │ schemas/instruction_packet │ (Canonical Contract)
                           └─────────────┬─────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
  [Track A: Participant 1]             [Track B: Participant 2]             [Track C: Participant 3]
  Pipeline & Safety Engine         Data, Storage & Exporters        Clinician UI/UX Dashboard
  ────────────────────────         ─────────────────────────        ─────────────────────────
  • LLM1: Simplifier (5-6th gr)    • In-Memory GitHub App Loader    • Streamlit 4-Pane Dashboard
  • Quality Gate: FKGL Readability   (JWT RS256, REST Contents API) • Dynamic Model Selectors
  • Verbatim Lock Regex Engine     • Zero-Disk Data Streaming       • Protocol Version Selectors
  • LLM2: Factual Safety Judge     • Versioned Library (JSONL)      • Inline Editing & Re-check
  • LLM1: ES Translation           • Bilingual PDF Generator        • Action Gates (Approve/Reject)
  • LLM2: Back-Translation (EN)      (ReportLab + Badges)           • Drift Simulator (Negative Tests)
```

---

## Iterative Merge & Test Cadence

The project progresses through 4 iterative synchronization points:

| Phase | Duration / Focus | Track A Deliverables | Track B Deliverables | Track C Deliverables | Sync Point & Gate Test |
|---|---|---|---|---|---|
| **Phase 0** | Contract & Scaffolding | Pipeline interface stubs & test harness | Pydantic data schemas & test data mocks | Streamlit shell & component mocks | **Sync Point 0**: Merge `schemas/` and test runners; verify all mocks validate against schema. |
| **Phase 1** | Mock End-to-End Loop | Mock orchestrator (rule-based simplifier, FKGL, verbatim check) | Mock in-memory data loader + JSONL persistence | 4-pane comparative review UI wired to mock orchestrator | **Sync Point 1**: Merge branches to `main`; smoke test end-to-end packet generation and review loop. |
| **Phase 2** | Live Integrations | Dual LLM pipeline (LLM1 simplifier/ES, LLM2 judge/back-EN) | Live in-memory GitHub App REST loader (zero-disk) | Dynamic model dropdowns + protocol version selectors | **Sync Point 2**: Merge to `main`; integration test with live GitHub App streaming and live LLM calls. |
| **Phase 3** | UX Hardening & Exporters | Drift simulator (Scenario C negative testing) | ReportLab bilingual PDF with physician badges | 3 review outcomes (`Approve & publish`, `Save and check edits`, `Reject`) | **Sync Point 3 (Final)**: Full clinical validation across all 3 tracks; verify zero data leakage. |

---

## Detailed Track Specifications

### Track A: Pipeline, Quality Gate & Safety Judge (Participant 1)
- **Component 1 (Simplification Engine - LLM1)**:
  - System prompts enforcing 5th–6th grade reading level, short sentences (<15 words), and structured verbatim preservation.
- **Component 2 (Automated Quality Gate)**:
  - Readability score evaluator using `textstat` (FKGL target 5.0–6.9).
  - Verbatim lock regex extractor ensuring medication dosages, temperature thresholds, and clinic phone numbers are unrounded and unparaphrased.
- **Component 3 (Safety Judge - LLM2)**:
  - Evaluates factual drift, red-flag omission, and semantic contradictions.
  - Assigns `PASS`, `NEEDS_REVIEW`, or `FLAGGED_FOR_REVIEW`.
- **Component 4 (Bilingual Translation)**:
  - Forward Spanish translation (LLM1) and back-translation to English (LLM2) to expose semantic drift.
- **Component 5 (Scenario C Drift Simulator)**:
  - Injects synthetic errors (doubled dose, altered fever threshold, withheld anti-emetic) for pipeline safety verification.

### Track B: In-Memory Data Loader, Storage & PDF Exporter (Participant 2)
- **Component 1 (Canonical Contract)**:
  - `schemas/instruction_packet.py`: `InstructionPacket`, `ClinicalOrders`, `MedicationOrder`, `EvaluationMetrics`.
- **Component 2 (In-Memory GitHub App Loader)**:
  - Reads `[dataloader]` section in `.streamlit/secrets.toml` (`GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_DATA_REPO`, `MODULES_PATH`, `ORDERS_PATH`).
  - Mints RS256 JWT, fetches short-lived installation access token, and fetches contents on the fly via GitHub REST API without disk writes.
- **Component 3 (Versioned Library Persistence)**:
  - Appends reviewed packets to `versioned_instructions.jsonl` with status, timestamp, and audit trail.
- **Component 4 (Bilingual PDF Generator)**:
  - ReportLab generator creating clean 2-column bilingual layout with physician verification status banner and audit footer.

### Track C: Clinician Review UI/UX Dashboard (Participant 3)
- **Component 1 (Sidebar Controls)**:
  - AI Model selectors for LLM1 and LLM2 (supporting `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local`).
  - Protocol & order set version selectors, data source indicator badge, cache refresh button (`🔄`).
- **Component 2 (4-Way Comparative Review Pane)**:
  - 4 columns: Original Clinical Text, Simplified English, Spanish Handout, Back-Translated English.
  - Automated telemetry display (FKGL score, verbatim lock badges, Safety Judge findings).
- **Component 3 (Inline Editing & Feedback Loop)**:
  - Clinician text area with two-way widget state binding.
  - "Save and check edits" button triggering automated re-evaluation while keeping status as `PENDING`.
- **Component 4 (Action Gates & Governance)**:
  - "Approve & publish": Sets status to `APPROVED` or `EDITED_AND_APPROVED`, logs to library, unlocks PDF download.
  - "Reject & log drift": Modal dialog requiring drift taxonomy classification and explanation.
  - Library viewer tab with "Physician Decision" and "PDF Annotation" columns.

---

## Specs Directory Artifacts to Generate

Upon plan approval, the following specification documents will be created in `specs/`:
1. `specs/00_OVERVIEW_AND_SCHEDULE.md`: Project schedule, team standups, branching strategy (`git flow`), and merge gates.
2. `specs/01_TRACK_A_PIPELINE_AND_SAFETY.md`: Prompt specifications, verbatim regex rules, evaluator metrics, and test plan.
3. `specs/02_TRACK_B_DATA_AND_STORAGE.md`: GitHub App auth spec, REST API loader, JSONL library schema, and PDF layout spec.
4. `specs/03_TRACK_C_CLINICIAN_UI_UX.md`: Streamlit architecture, state management patterns, UI wireframes, and action workflows.
5. `specs/04_INTEGRATION_TEST_PLAN.md`: End-to-end integration test checklist for each merge point.
