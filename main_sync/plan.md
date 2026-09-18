# AI-Assisted Patient Instruction Simplification with Clinician-in-the-Loop
## 2-Day Rapid Prototype & Demo Plan

---

## 1. Executive Summary & Objectives

### Purpose
Build and demonstrate a clinician-in-the-loop prototype using supplied, versioned clinical English and structured orders to produce bilingual (English & Spanish) handouts. The composer binds vetted source wording and orders, then LLM1 simplifies English to **FKGL 5.0–6.9**, measured after protected values are restored. Generation allows three attempts and fails explicitly if the benchmark is unmet. Translation follows a passing candidate; safety judgment and clinician approval remain mandatory.

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
   - Clinician-reviewed, immutable snapshots retained in session memory only; no JSONL/SQLite clinical-data persistence.
   - Dual-language, print-ready PDF generated dynamically.
   - Interactive responsive family-facing view.

---

## 2. End-to-End Pipeline Architecture

```
[Module Instruction (EN)] + [Synthetic Clinical Orders (EN)]
                      │
                      ▼
            ┌──────────────────┐
            │ Bind vetted text │ ◄── Supplied wording + structured order values
            └─────────┬────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │ LLM1: Simplify English  │
         │ Automated Quality Gate  │
         │  1. Readability (FKGL)  │
         │  2. Verbatim Extractor  │
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
         │ LLM2: Safety Judge      │
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
  • Vetted English Composer (5-6th gr)    • In-Memory GitHub App Loader    • Streamlit 4-Pane Dashboard
  • Quality Gate: FKGL Readability   (JWT RS256, REST Contents API) • Dynamic Model Selectors
  • Verbatim Lock Regex Engine     • Zero-Disk Data Streaming       • Protocol Version Selectors
  • LLM2: Factual Safety Judge     • Session Review Library      • Inline Editing & Re-check
  • LLM1: ES Translation           • Bilingual PDF Generator        • Action Gates (Approve/Reject)
  • LLM2: Back-Translation (EN)      (ReportLab + Badges)           • Drift Simulator (Negative Tests)
```

---

## Iterative Merge & Test Cadence

The project progresses through 4 iterative synchronization points:

| Phase | Duration / Focus | Track A Deliverables | Track B Deliverables | Track C Deliverables | Sync Point & Gate Test |
|---|---|---|---|---|---|
| **Phase 0** | Contract & Scaffolding | Pipeline interface stubs & test harness | Pydantic data schemas & test data mocks | Streamlit shell & component mocks | **Sync Point 0**: Merge `schemas/` and test runners; verify all mocks validate against schema. |
| **Phase 1** | Mock End-to-End Loop | Mock orchestrator (rule-based simplifier, FKGL, verbatim check) | Mock in-memory data loader + session review snapshots | 4-pane comparative review UI wired to mock orchestrator | **Sync Point 1**: Merge branches to `main`; smoke test end-to-end packet generation and review loop. |
| **Phase 2** | Live Integrations | Source composition + protected LLM1 English simplification and ES / LLM2 judge and back-EN | Live in-memory GitHub App REST loader (zero-disk) | Dynamic model dropdowns + protocol version selectors | **Sync Point 2**: Merge to `main`; integration test with live GitHub App streaming and live LLM calls. |
| **Phase 3** | UX Hardening & Exporters | Four synthetic drift scenarios, sentinel restoration, deterministic safety vetoes | Session-isolated immutable reviews; multipage bilingual PDFs with review badges | Current-revision approval, recheck, rejection, live generation without an Offline/Live selector, no UI emojis | Software acceptance implemented and tested across all three conditions. **Sync Point 3 clinical/live-service validation and merge remain pending.** |

---

## Detailed Track Specifications

### Track A: Pipeline, Quality Gate & Safety Judge (Participant 1)
- **Component 1 (Vetted English Composer)**:
  - Binds supplied versioned wording and orders, then LLM1 simplifies English with protected values. Measure actual restored-text FKGL; retry from the source with score feedback up to three attempts to reach 5.0–6.9. Failure stops generation before translation. Clinician edits are rechecked, never silently rewritten, and must meet the same approval benchmark.
- **Component 2 (Automated Quality Gate)**:
  - Readability score evaluator using `textstat` (FKGL target 5.0–6.9).
  - Verbatim lock regex extractor ensuring medication dosages, temperature thresholds, and clinic phone numbers are unrounded and unparaphrased.
- **Component 3 (Safety Judge - LLM2)**:
  - Evaluates factual drift, red-flag omission, and semantic contradictions.
  - Assigns `PASS`, `NEEDS_REVIEW`, or `FLAGGED_FOR_REVIEW`.
- **Component 4 (Bilingual Translation)**:
  - Forward Spanish translation (LLM1) and back-translation to English (LLM2) to expose semantic drift.
- **Component 5 (Scenario C Drift Simulator)**:
  - Injects doubled doses, altered fever thresholds, contradictory advice, and omitted source warnings into independent synthetic revisions. Deterministic evaluation inspects actual changes. Simulation packets cannot be approved for patient use.
  - Model inputs mask numeric values and units with sentinels; translation restoration rejects missing, duplicated, unknown markers and invented numeric values. Incomplete/malformed judge audits are flagged. New-value and FKGL checks can veto a passing model judge. Warning meaning is checked by the judge and clinician, allowing legitimate rephrasing; reported omissions block approval even with a PASS verdict.

### Track B: In-Memory Data Loader, Storage & PDF Exporter (Participant 2)
- **Component 1 (Canonical Contract)**:
  - `schemas/instruction_packet.py`: `InstructionPacket`, `ClinicalOrders`, `MedicationOrder`, `EvaluationMetrics`.
- **Component 2 (In-Memory GitHub App Loader)**:
  - Reads `[dataloader]` section in `.streamlit/secrets.toml` (`GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_DATA_REPO`, `MODULES_PATH`, `ORDERS_PATH`).
  - Mints RS256 JWT, fetches short-lived installation access token, and fetches contents on the fly via GitHub REST API without disk writes.
- **Component 3 (Versioned Library Persistence)**:
  - `ReviewLibrary` stores copied, reviewed snapshots in session memory. Reads return independent copies. Repeated identical saves are idempotent; conflicting records with the same ID are rejected. Pending packets and unexplained rejections are not saved.
  - Resolves the earlier JSONL/no-local-data conflict in favor of AGENTS.md: no clinical records are written to disk. Session reset/server restart loses history; durable multi-session audit storage is not implemented.
- **Component 4 (Bilingual PDF Generator)**:
  - ReportLab creates a 2-column bilingual layout with review badges, bold protected values, versions/timestamps, and page numbers. Long paragraphs split across pages with repeated language headers. Rejected PDFs are marked audit-only, not for patient use. Supplied text and metadata are escaped.

### Track C: Clinician Review UI/UX Dashboard (Participant 3)
- **Component 1 (Sidebar Controls)**:
  - Normal generation always uses the live simplification/translation pipeline; no Offline/Live selector is shown. Live failures do not substitute a mock packet. Local synthetic drift simulations remain available and cannot be approved.
  - AI Model selectors for LLM1 Spanish and LLM2 judge/back-translation (supporting `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local1`, `local2`).
  - Protocol and module-version choices come from loaded content and matching orders. Order-set selection shows the actual version and ID exposed by the loader (currently one order set per condition). History labels without archived content are not selectable.
  - Data source indicator badge and cache refresh button (`🔄`).
- **Component 2 (4-Way Comparative Review Pane)**:
  - 4 columns: Original Clinical Text, Simplified English, Spanish Handout, Back-Translated English.
  - Automated telemetry display on simplified English (FKGL score, verbatim lock badges, Safety Judge findings). Back-translated English is a fidelity comparison pane, without a separate FKGL score; deterministic safety checks also inspect its protected values.
- **Component 3 (Inline Editing & Feedback Loop)**:
  - Clinician text area with two-way widget state binding.
  - "Save and check edits" re-evaluates English and refreshes translations while keeping status `PENDING`. Failed live rechecks invalidate approval eligibility and clear outdated translations when local evaluation succeeds; they never manufacture mock Spanish.
  - Successful checks are bound to an exact packet snapshot within the session. Any subsequent English edit requires another successful check.
- **Component 4 (Action Gates & Governance)**:
  - "Approve & publish": Requires the exact checked revision, available evaluation, a passing safety judge with no unresolved findings, strict value preservation in all three output panes, and authorized Spanish-review attestation for that revision. The attestation is recorded in clinician notes; this prototype does not authenticate reviewer credentials.
  - Builds the PDF before saving the approved snapshot and updating UI status to `APPROVED` or `EDITED_AND_APPROVED`; export failure keeps the packet pending. A successful save unlocks PDF download.
  - "Reject & log drift": Persistent modal with Cancel and required category/reason. Rejects a copy of the current reviewed text, builds its audit PDF before saving, and preserves previous history on failure. Finalized packets require a new revision before a changed review.
  - Library viewer tab with "Physician Decision" and "PDF Annotation" columns.

---

## Specs Directory Artifacts to Generate

The following specification documents are maintained in `specs/`:
1. `specs/00_OVERVIEW_AND_SCHEDULE.md`: Project schedule, team standups, branching strategy (`git flow`), and merge gates.
2. `specs/01_TRACK_A_PIPELINE_AND_SAFETY.md`: Prompt specifications, verbatim regex rules, evaluator metrics, and test plan.
3. `specs/02_TRACK_B_DATA_AND_STORAGE.md`: GitHub App auth spec, REST API loader, session review-library contract, and PDF layout spec.
4. `specs/03_TRACK_C_CLINICIAN_UI_UX.md`: Streamlit architecture, state management patterns, UI wireframes, and action workflows.
5. `specs/04_INTEGRATION_TEST_PLAN.md`: End-to-end integration test checklist for each merge point.


## Phase 3 Verification Status

Run from `main_sync`: `../.venv/bin/python -B tests/run_suite.py` (or the installed environment's Python).
Verified on this iteration: **135 automated tests passed**, Python syntax checks passed, and `git diff --check` was clean. The suite uses synthetic fixtures and mocked external transports, blocks network requests/user-secret reads, and prohibits JSONL file access. It covers all three conditions and review outcomes, revision freshness, session isolation, drift injections, protected translation, and long PDF exports.

No live GitHub/model acceptance, authorized clinical validation, or merge has been performed. Spanish sign-off is a recorded reviewer attestation; credential authentication remains outside this prototype. Warning preservation is assessed semantically by the safety judge and clinician; exact source-sentence matching is not required after simplification.
