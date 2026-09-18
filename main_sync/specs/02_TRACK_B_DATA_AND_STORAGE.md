# 02: Track B Specification — Data, In-Memory Loader, Storage & Exporters

**Assigned**: Participant 2  
**Module Directory**: `schemas/`, `storage/`, `exporters/`  
**Test Suite**: `tests/test_github_loader.py`, `tests/test_components.py`

---

## 1. Responsibilities & Objectives
Participant 2 owns the data lifecycle, security compliance, persistence, and printable artifact generation:
1. **Canonical Schema Contract (`schemas/instruction_packet.py`)**: Defines shared data interfaces across all tracks.
2. **In-Memory GitHub App Loader (`storage/github_loader.py`)**: Fetches clinical modules and orders on the fly from a private GitHub repo (`stjude-biohackathon/team7-data`) via GitHub App authentication with zero local copies on disk.
3. **Versioned Library Persistence (`storage/gold_library.py`)**: Stores independent finalized review snapshots in session memory only.
4. **Bilingual PDF Generator (`exporters/pdf_generator.py`)**: Renders full-width English or requested 2-column bilingual clinical discharge handouts with physician verification badges and protocol version tracking.

---

## 2. Component Specifications

### 2.1 Canonical Data Schema (`schemas/instruction_packet.py`)
- **Key Models**:
  - `MedicationOrder`: Name, dose, route, frequency, special instructions.
  - `ClinicalOrders`: Patient ID, age, diagnosis, medications list, urgent/emergency fever thresholds, daytime/after-hours phone numbers, `order_id`, `order_version`.
  - `EvaluationMetrics`: Readability scores (FKGL), verbatim preservation match/mismatch flags, Safety Judge verdict.
  - `InstructionPacket`: Master packet binding original input, simplified EN, translated ES, back-translated EN, review status (`APPROVED`, `EDITED_AND_APPROVED`, `REJECTED_DRIFT`, `PENDING`), `module_version`, `order_version`, `parent_packet_id`, and `is_simulation`.
- **Physician Annotation Logic**:
  - `get_physician_annotation(packet)` helper returning:
    - `"Approved by physician"`
    - `"Edited and approved by physician"`
    - `"Rejected by physician"`
    - `"Pending physician review"`

### 2.2 In-Memory GitHub App Loader (`storage/github_loader.py`)
- **Configuration Contract**:
  - Credentials must be parsed from the `[dataloader]` section in `.streamlit/secrets.toml` or environment variables:
    ```toml
    [dataloader]
    GITHUB_APP_ID = "..."
    GITHUB_INSTALLATION_ID = "..."
    GITHUB_APP_PRIVATE_KEY_PATH = "..."
    GITHUB_DATA_REPO = "stjude-biohackathon/team7-data"
    MODULES_PATH = "data/modules/pediatric_discharge_instruction_templates.json"
    ORDERS_PATH = "data/orders/synthetic_orders.json"
    ```
- **Zero-Disk Streaming Protocol**:
  1. Load private key directly from `GITHUB_APP_PRIVATE_KEY_PATH` without printing or logging key contents.
  2. Mint short-lived RS256 JWT using `jwt.encode({"iat": now - 60, "exp": now + 570, "iss": app_id}, private_key, algorithm="RS256")`.
  3. Exchange JWT for installation access token (`POST https://api.github.com/app/installations/{id}/access_tokens`).
  4. Cache installation token in-memory for 50 minutes.
  5. Fetch file content via REST API (`GET https://api.github.com/repos/{repo}/contents/{path}`) with header `Authorization: token {token}`.
  6. Decode base64 payload directly in-memory using `json.loads` or `ast.literal_eval`.
  7. **Strict Privacy Rule**: Never save or cache fetched data files to the local file system.

### 2.3 Session Review Library (`storage/gold_library.py`)
- `ReviewLibrary` is owned by one Streamlit session; no module-global clinical store or disk persistence.
- `save_to_gold_library(packet, *, library=None)` stores a deep copy of a reviewed packet. Missing review metadata is filled on the saved copy, never on the caller.
- Pending records and rejections without category/reason are refused. Repeated identical saves are idempotent; changed content under an existing ID is refused.
- `load_gold_records(*, library=None)` returns independent copies, preserving immutable review history. Revisions carry `parent_packet_id`.
- Session reset/server restart loses history. Durable audit storage is not implemented. This supersedes the earlier JSONL specification to comply with AGENTS.md's no-local-data rule.

### 2.4 Bilingual PDF Exporter (`exporters/pdf_generator.py`)
- **Engine**: ReportLab Platypus document framework.
- **Visual Design**:
  - Professional header with St. Jude / Pediatric Hospital clean styling.
  - **Physician Verification Banner**:
    - Approved: Light green background (`#F0FFF4`), dark green border (`#38A169`), text: "Approved by physician".
    - Edited & Approved: Light blue background (`#EBF8FF`), blue border (`#3182CE`), text: "Edited and approved by physician".
    - Rejected PDFs include an audit-only/not-for-patient-use label on every page.
    - Rejected: Light red background (`#FFF5F5`), red border (`#E53E3E`), text: "Rejected by physician" with rejection notice.
  - **Language-Aware Layout**:
    - English-only output uses one full-width column and an English Handout banner, with no blank Spanish column.
    - Requested bilingual output uses two side-by-side columns. User-facing metadata says Patient MRN, Module, and Record ID.
  - Long cells split across pages with repeated language headers; table widths fit the available page frame.
    - Left column: English simplified instructions with bolded verbatim markers.
    - Right column: Spanish translation.
  - **Audit Sign-off Footer**:
    - Includes `Module Ver`, `Order Set Ver`, physician signature line, and verification timestamp.
  - **Formatting Rule**: ReportLab paragraphs require `<font size="8.5">` instead of HTML `<span style="...">`.

---

## 3. Test-Driven Development (TDD) Milestones
1. **GitHub Loader Tests (`tests/test_github_loader.py`)**:
   - `test_configured_check()`: Verifies app credentials detection.
   - `test_dataloader_section_parsing()`: Verifies `[dataloader]` section parsing from TOML.
   - `test_fetch_file_decodes_base64_in_memory()`: Verifies zero-disk base64 decoding with mocked GitHub REST response.
   - `test_token_caching()`: Validates that installation tokens are reused until expiration.
2. **PDF Generator Tests (`tests/test_components.py`)**:
   - Validates PDF generation across all three review decisions (`APPROVED`, `EDITED_AND_APPROVED`, `REJECTED_DRIFT`).
   - Ensures no ReportLab parser exceptions occur during XML markup rendering.
