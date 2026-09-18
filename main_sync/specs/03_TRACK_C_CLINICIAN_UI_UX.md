# 03: Track C Specification — Clinician Review Dashboard & Streamlit UI/UX

**Assigned**: Participant 3  
**Module Directory**: `app/`  
**Core File**: `app/clinician_ui.py`  
**Test Suite**: Compilation check (`python -m py_compile app/clinician_ui.py`), UI component integration tests

---

## 1. Responsibilities & Objectives
Participant 3 owns the clinician-facing interface and review workflow:
1. **Sidebar Model & Protocol Controls**: Enables clinicians to select LLM1/LLM2 models dynamically, choose protocol/order versions, and monitor data source status.
2. **In-Memory Data Integration**: Calls `storage.github_loader` to fetch templates and orders on the fly with in-memory caching and manual refresh.
3. **Adaptive Comparative Review**: Defaults to original and simplified English; includes Spanish and back-translated English only when requested for the family.
4. **Interactive Inline Editing & Safety Re-check**: Provides two-way text editing with automated re-scoring while preventing Streamlit widget state conflicts.
5. **Physician Review Governance**: Enforces clear action gates (`Approve & publish`, `Save and check edits`, `Reject & log drift`) with audit logging.
6. **Library Explorer**: Displays versioned library records with physician review annotations.

---

## 2. Component Specifications

### 2.1 Sidebar Architecture (`app/clinician_ui.py`)
- **AI Model Selection**:
  - Normal generation always uses live models. Hide the Offline/Live selector; live failures are explicit and do not substitute mock output. Scenario C remains a local synthetic simulation that cannot be approved.
  - LLM1 simplification/optional Spanish dropdown: Default `gpt4o`, options: `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local1`, `local2`.
  - LLM2 dropdown: Default `gpt4o`, options: `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`, `local1`, `local2`.
- **Protocol Refresh and Errors**:
  - Remove the In-Memory Data Stream section and provenance badge from the UI.
  - Keep the compact GitHub App Refresh button to clear the source cache and current review, then rerun.
  - Loading errors block generation; show actionable errors and upstream data-quality notices without exposing secrets. A mock or fallback load is also blocked even when it has no error detail: only a reported `github_app` result may supply original clinical instructions.
- **Protocol Version Selectors**:
  - Protocol choices require matching loaded templates and orders; module versions come from available content, not hardcoded labels.
  - Order Set Version displays the actual loaded version and order ID. The current loader exposes one order set per condition. Historical labels without archived content are not offered.
  - Do not display a redundant active-protocol summary beneath the selectors.
- **Clinical Orders Customization**:
  - Every field is initialized from the loaded Team7 order and acts as an explicit physician override: patient synthetic ID (shown as MRN), age, diagnosis, weight, medications, hydration, fever thresholds, red flags, contraindications, and contacts. Missing Team7 values start blank.
  - Medication expanders (Name, Dose, Frequency, Route, Special instructions), with an Add medication control that appends a blank medication row.
  - Fever threshold inputs use the exact loaded Team7 values. The UI does not supply default thresholds, routes, ages, or contact numbers.
  - Daytime clinic, 24/7 triage, and emergency contact numbers.
- **Scenario C Drift Simulator Expander**:
  - Allows clinicians to test error detection by injecting simulated clinical contradictions, altered thresholds, or altered dosages.

### 2.2 Source Preview and Comparative Review
The front page has reduced top padding and the title "Pediatric Discharge Instruction Review". Two patient-summary lines display the hardcoded prototype name John Doe and sex M with the active MRN and age, followed by a larger selected-module name. Generate Simplified Instructions and an unchecked `Generate Spanish` checkbox are centered together. A full-width scrollable source preview follows, with clear headings, labeled fields, indented medication cards, and readable spacing rather than raw delimiter headings. The top Streamlit status/loading decoration is hidden. During generation an in-page spinner is shown directly beneath the page heading. The source preview remains on screen until the completed simplified packet replaces the front page.

Generation replaces those controls with FKGL (one decimal), verbatim percentage (whole number), and judge verdict. Verbatim help lists only missing safety tokens; correctly preserved tokens are not listed. New Generation returns to the preview. No viewport slider is shown. Original clinical orders and the label-free simplified-English editor start at equal width and height; the original pane has a horizontal resize handle that gives its remaining width to the editor. When Spanish is requested, Spanish and back-translated English appear as a second equal-width row.

1. **Original Clinical Orders & Instructions (Col 1)**:
   - Displays the complete, unsimplified Team7 module wording and immutable Team7 synthetic order snapshot. Every source instruction remains present verbatim; formatting may add visual headings and spacing but cannot rewrite, omit, or supplement clinical information. The same source renderer is used before and after generation.
   - When sidebar values differ from the Team7 order, an override notice names the changed fields. The original pane continues to show Team7 values. Generation, safety evaluation, export, and review history use the separately recorded effective order containing the physician overrides.
2. **Simplified English Handout (Col 2)**:
   - Displays LLM1 simplified English with restored order values (required FKGL 5.0–6.9). Live generation allows three attempts. If readability, protected values, or the safety judge fails, the simplified draft remains visible with its failure reason and a not-for-patient-use warning. Clinician edits must pass fresh checks before approval.
   - Telemetry badges: FKGL score, verbatim lock status (matches/mismatches), and Safety Judge verdict.
   - Interactive `st.text_area` for clinician inline edits.
3. **Spanish Translation (Col 3)**:
   - Forward translation generated by LLM1 only when Spanish was requested; otherwise this pane and its model call are absent.
4. **Back-Translated English (Col 4)**:
   - Back-translation produced by LLM2 only when Spanish was requested; English safety judging always runs.
   - Exposes translation drift or dropped nuances directly to English-speaking clinicians.

### 2.3 State Management & Safe Widget Handling
- **Streamlit Widget Invariant**:
  - **Rule**: Never mutate `st.session_state["txt_clinician_en"]` downstream after `st.text_area(key="txt_clinician_en")` is instantiated.
  - Doing so raises `StreamlitWidgetAlreadyInstantiatedError`.
  - Instead, use Streamlit's native two-way widget state binding and read values directly from session state.
- **Session State Variables**:
  - `current_packet`: Active `InstructionPacket`.
  - `clean_backup_packet`: Unaltered generated packet (used for diffing and reverting).
  - `review_inputs`: Hash of module/version/source, orders, selected models, and drift scenario. Any change clears the current review, checks and PDF before rendering.
  - `spanish_requested`: Translation choice for the generated review; remains fixed during rechecking.
  - Clinical-order widgets are keyed by module and source-order contents to prevent stale values across modules or refreshes.
  - `edits_checked_banner`: Boolean triggering re-evaluation success banner.

### 2.4 Action Footer & Review Governance
- **Failed protected-value drafts**: Keep the English draft and all requested translation panes visible. Translation, back-translation, and judging continue after check failures and accumulate findings; they cannot override an earlier failure. Show a not-for-patient-use banner, stage-specific failed safety tokens inside a red-bordered box, and a FAILED verbatim metric with detailed help. Missing values are not auto-filled; corrupted markers are labeled unresolved. Clear approval eligibility and PDF downloads. Only a fresh passing revision can be published; rejection may still create a marked audit copy.
- **Editor formatting**: Convert LLM Markdown to plain editable text before scoring and display. Remove headings, emphasis markers, code fences, link URLs, and HTML presentation tags while retaining the words, paragraph breaks, and normalized bullet structure.

- **Button 1: "Save and check edits"**:
  - Re-runs automated quality gates (FKGL readability + verbatim locks) on user-edited text.
  - Re-generates Spanish translation and back-translation to match edits only when requested. English-only rechecks call the safety judge without translation calls. Successful checks are bound to the exact packet revision; later edits invalidate eligibility.
  - A failed live recheck blocks approval. Local re-evaluation may produce a pending revision with translations cleared; do not substitute mock Spanish.
  - **Status Invariant**: Keeps status as `PENDING` (does not approve or publish).
  - Renders an informative banner: "Edits re-evaluated and checked. Click 'Approve & publish' when ready to finalize."
- **Button 2: "Approve & publish" (Sole Approval Gate)**:
  - Requires current-revision checks, finite readability evaluation, a passing judge without unresolved findings, exact protected values in all output panes, and an authorized Spanish-review attestation for that revision if Spanish is requested. English-only reviews require empty Spanish/back-translation fields and record an English-only note, never a Spanish attestation.
  - Attestation resets for a new revision and is recorded in clinician notes; credential authentication is not implemented.
  - Build the PDF before persisting approval. Export failure leaves the packet pending.
  - If text was edited, sets status to `EDITED_AND_APPROVED`.
  - If unedited, sets status to `APPROVED`.
  - Saves an independent record in the session-only review library; no clinical data is written to disk.
  - Unlocks PDF download button with "Approved by physician" or "Edited and approved by physician" banner.
- **Button 3: "Reject & log drift"**:
  - Opens a modal dialog with optional drift taxonomy categorization and optional clinical rationale. Available categories are:
    - `Unsafe dosage alteration`
    - `Altered return/fever threshold`
    - `Omitted critical red flag`
    - `Contradictory clinical advice`
    - `Spanish translation drift`
  - Requires a pending packet; captures current editor text in a separate revision when changed. Builds the rejected audit PDF before saving and sets `REJECTED_DRIFT` only after success. Cancel or export failure leaves the original unchanged.

### 2.5 Library Explorer
- Expander title: **"View versioned library records"** (reflecting both approved and rejected records).
- Columns displayed, in order:
  - `Module`
  - `Status`
  - `Physician Decision` (`Approved by physician`, `Edited and approved by physician`, `Rejected by physician`)
  - `Timestamp` (review time when available, otherwise creation time)

---

## 3. UI/UX Verification Checklist
1. App compiles cleanly without syntax or import errors: `python -m py_compile app/clinician_ui.py`.
2. Selecting different models from dropdowns updates pipeline routing.
3. Editing text in Col 2 and clicking "Save and check edits" re-scores readability without crashing Streamlit.
4. "Approve & publish" commits packet to library and generates valid PDF with physician badge.
5. "Reject & log drift" captures reason and displays rejected annotation in library table.

### Phase 3 UX behavior
- User-facing language uses instructions, review, record, and module; the internal `InstructionPacket` schema stays unchanged.
- No decorative emojis in application controls or exported review banners.
- The library explains its session-only lifetime. Independent browser sessions cannot read each other's reviewed packets.
- Synthetic drift packets are prominently marked and cannot be approved.
- Back-translated English remains a meaning-comparison pane, without a separate FKGL score. Its protected values still participate in approval checks.
