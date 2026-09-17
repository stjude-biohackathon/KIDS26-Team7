# 05 — Phase 2 Live Integration Remediation Plan (Spec-Driven)

**Status:** Proposed — not yet implemented
**Scope:** Tracks A (live LLMs), B (live GitHub App data), C (honest UI state)
**Governing specs:** `01_TRACK_A_PIPELINE_AND_SAFETY.md`, `02_TRACK_B_DATA_AND_STORAGE.md`,
`03_TRACK_C_CLINICIAN_UI_UX.md`, `04_INTEGRATION_TEST_PLAN.md`

---

## 1. Problem Statement

Phase 2 was declared complete, but the running application is still producing
**mock output in both data and model paths** while presenting a green "live" badge.
Two user-visible symptoms were reported:

1. Every generation shows:
   `⚠️ Live model call unavailable (unconfigured model or endpoint error); showing offline mock output instead.`
2. The sidebar shows `☁️ GitHub App (In-Memory, No Local Copy)` / "Zero local copies • In-memory stream"
   in green, yet the modules and orders rendered in the review pane are the bundled
   synthetic fixtures, not the content of `stjude-biohackathon/team7-data`.

This document records the investigated root causes and the spec-conformant fix
required for each. **No assumptions or masking** — each root cause below was
confirmed by direct runtime observation.

---

## 2. Confirmed Root Causes

### RC-1 — Track A: model secret key names do not match the resolver (LLMs never go live)

`pipeline/llms.py::resolve_model_config()` reads the per-alias secrets section
looking for the generic keys `base_url`, `api_key`, and `model`.

The actual provisioned secrets use **Azure OpenAI key names**. Observed section
key names (names only; no values were read, printed, or logged):

| Section | Keys present |
|---|---|
| `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5` | `AZURE_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_ENDPOINT`, `MODEL_DEPLOYMENT` |
| `local1`, `local2` | `AZURE_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_ENDPOIN` *(note: truncated key name upstream)*, `MODEL_DEPLOYMENT` |

Because none of `base_url` / `api_key` / `model` exist, `resolve_model_config()`
raises `ValueError` for **every** alias. `PipelineOrchestrator.generate_live()`
therefore always throws, `app/clinician_ui.py` sets `live_failed = True`, and the
UI falls back to `run_mock_pipeline`. This is the sole cause of symptom (1).

Additional structural facts confirmed (shape only, no secret values):
- Remote aliases: `AZURE_OPENAI_ENDPOINT` is a bare Azure resource URL;
  `AZURE_BASE_URL` is a longer URL containing an `/openai` path segment;
  `AZURE_OPENAI_API_VERSION` is populated (e.g. an Azure preview date string);
  `MODEL_DEPLOYMENT` holds the Azure deployment name, which differs from the alias.
- Local aliases: `AZURE_OPENAI_API_VERSION` is empty and there is no usable
  endpoint key, but `AZURE_BASE_URL` is a plain local OpenAI-compatible URL.

**Implication:** remote aliases require the `AzureOpenAI` client
(`azure_endpoint` + `api_version` + `api_key`, `model=MODEL_DEPLOYMENT`), while
local aliases require the plain `OpenAI` client (`base_url` + `api_key`).
A single `OpenAI(base_url=...)` construction cannot serve both.

### RC-2 — Track B: upstream data file is not strict JSON (live fetch always fails)

`data/modules/pediatric_discharge_instruction_templates.json` in
`stjude-biohackathon/team7-data` contains a **trailing comma** in the `_readme`
object (`"... patient-facing use.",\n  },`). `json.loads()` raises
`JSONDecodeError: Expecting property name enclosed in double quotes (line 22)`.

The network layer itself is healthy: JWT minting, installation-token exchange,
and in-memory file fetch all succeed (17,324-byte payload retrieved). Only the
parse step fails.

### RC-3 — Track B: real upstream schema differs entirely from the loader's expected shape

Even with RC-2 repaired, `fetch_remote_templates_and_orders()` cannot consume the
data. It expects `Dict[condition][version] -> template_str` and
`Dict[condition] -> ClinicalOrders`, but the repository actually publishes:

```
modules file:
  { version, version_history[], _readme{}, handout_template_structure[],
    instructions[ { id, category, type, instruction_text } ] }      # 48 records

orders file:
  { version, version_history[], synthetic_orders[ {
      order_id, version, version_label, category, diagnosis,
      patient_synthetic_id, patient_age, weight_kg,
      medications[ {name, dose, route, frequency} ],
      hydration_order, temperature_threshold_urgent,
      temperature_threshold_emergency, red_flag_symptoms[],
      clinic_phone_daytime, clinic_phone_after_hours, emergency_contact
    } ] }                                                            # 6 records
```

`categories` are `sickle_cell_pain`, `fever_neutropenia`, `chemo_nausea_hydration`
(matching the UI selector). `instructions[].type` provides the section taxonomy
(`supportive_home_care`, `pain_management`, `hydration_nutrition`, `warning_sign`,
`when_to_call_your_care_team`, `when_to_seek_urgent_or_emergency_care`), and
`handout_template_structure[]` defines the canonical section ordering.
Orders exist at both `v1.2.0` and `v1.1.0`; module `instructions` exist only for
the file's current `version`.

`ClinicalOrders.model_validate()` over these records fails outright (field names
do not align: `patient_synthetic_id` vs `patient_id`, `patient_age` vs `age`,
`temperature_threshold_urgent` vs `urgent_fever_threshold`, etc.).

### RC-4 — Track B/C: silent failure masking makes the UI dishonest

`fetch_remote_templates_and_orders()` ends in a bare
`except Exception: return load_mock_templates_and_orders()`. RC-2/RC-3 failures
are therefore swallowed with no signal. Meanwhile the sidebar badge is driven only
by `_is_live_data_configured()` → `is_github_app_configured()`, which merely checks
that credentials *exist*. Result: **green "live" badge over mock content** — the
exact condition reported in symptom (2). This violates the Track C requirement
that provenance display be truthful and the project rule to surface, not mask,
root causes.

### RC-5 — Track C: empty live template silently degrades to mock without notice

In `app/clinician_ui.py`, `raw_template = live_templates.get(condition, {}).get(module_version, "")`.
When the live shape yields no match (RC-3), `raw_template.strip()` is falsy, so the
live branch is skipped entirely and `live_failed` stays `False` — mock output is
rendered **with no warning at all**. This is a second, independent masking path.

---

## 3. Required Fixes

### FIX-A1 — Azure-aware model credential resolution (`pipeline/llms.py`)

- Extend `ModelConfig` with `azure_endpoint: str = ""` and `api_version: str = ""`,
  plus an `is_azure` property (true when both are populated).
- In `resolve_model_config()`, resolve each field from, in order:
  1. the alias's secrets section under the **Azure key names**
     (`AZURE_OPENAI_ENDPOINT` — tolerating the upstream `AZURE_OPENAI_ENDPOIN`
     spelling —, `AZURE_BASE_URL`, `AZURE_OPENAI_API_KEY`,
     `AZURE_OPENAI_API_VERSION`, `MODEL_DEPLOYMENT`),
  2. the existing generic key names (`base_url`, `api_key`, `model`) for
     backward compatibility with the current test suite,
  3. `{ALIAS}_BASE_URL` / `{ALIAS}_API_KEY` / `{ALIAS}_MODEL` environment variables,
  4. local-alias defaults.
- `get_client()` returns `(AzureOpenAI(azure_endpoint=…, api_version=…, api_key=…), deployment)`
  when `config.is_azure`, else `(OpenAI(base_url=…, api_key=…), deployment)`.
- Error messages must continue to name only the alias and the expected *key names*
  — never a value.

### FIX-B1 — Tolerant-but-explicit JSON parsing (`storage/github_loader.py`)

- Parse with `json.loads()` first. Only on `JSONDecodeError`, retry once after
  stripping trailing commas (`re.sub(r",(\s*[}\]])", r"\1", raw)`), then parse again.
- If the lenient retry succeeds, record a non-fatal data-quality warning
  (surfaced per FIX-B3) so the upstream file can be corrected at source rather
  than the defect being hidden indefinitely.
- Do **not** write the repaired text to disk (zero-disk rule).

### FIX-B2 — Upstream→canonical adapters (`storage/github_loader.py`)

Add two pure, unit-testable functions:

- `adapt_modules(raw: dict) -> Dict[str, Dict[str, str]]`
  Group `instructions[]` by `category`; within each category compose one
  template string ordered by `handout_template_structure[]` (falling back to
  `type` grouping order for types absent from the structure list), joining each
  section's `instruction_text` entries under a readable section heading. Key the
  result by the file's `version`, and also expose it under each entry of
  `version_history[]` that has no distinct content so the existing UI version
  selector (`v1.2.0`, `v1.1.0`) always resolves to real upstream text.
  The composer **binds and orders vetted text only — it must not rewrite,
  paraphrase, or generate clinical prose** (Zero AI-Originated Clinical Prose).
- `adapt_orders(raw: dict) -> Dict[str, ClinicalOrders]`
  Map `synthetic_orders[]` onto `ClinicalOrders`, preferring the record whose
  `version` matches the file's current `version` for each `category`:
  | upstream field | canonical field |
  |---|---|
  | `patient_synthetic_id` | `patient_id` |
  | `patient_age` | `age` |
  | `diagnosis` | `diagnosis` |
  | `medications[]` (`name`/`dose`/`route`/`frequency`) | `medications[]` `MedicationOrder` |
  | `temperature_threshold_urgent` | `urgent_fever_threshold` |
  | `temperature_threshold_emergency` | `emergency_fever_threshold` |
  | `clinic_phone_daytime` | `daytime_phone` |
  | `clinic_phone_after_hours` | `after_hours_phone` |
  | `emergency_contact` | `emergency_phone` |
  | `order_id` | `order_id` |
  | `version` | `order_version` |
  `hydration_order` and `red_flag_symptoms[]` carry safety-critical content and
  must be preserved into the composed template text (not dropped), so the
  verbatim-lock evaluator can assert their presence downstream.

### FIX-B3 — Stop masking failures (`storage/github_loader.py`)

- Introduce `fetch_remote_templates_and_orders(strict: bool = False)` returning
  the existing tuple, plus a module-level accessor such as
  `get_last_load_status() -> dict` with at least
  `{"source": "github_app" | "mock", "error": Optional[str], "warnings": [str]}`.
- Narrow the bare `except Exception` to the specific recoverable cases
  (`requests.RequestException`, `json.JSONDecodeError`, `ValidationError`,
  `KeyError`, `FileNotFoundError`), always recording the failure reason.
- Error strings must never embed credential material.
- `strict=True` re-raises instead of falling back, for use by the integration tests.

### FIX-C1 — Honest provenance badge (`app/clinician_ui.py`)

- Drive the sidebar badge from the **actual load result** (`get_last_load_status()`),
  not from credential presence:
  - `source == "github_app"` → green `☁️ GitHub App (In-Memory, No Local Copy)`
  - configured but load failed → red/amber
    `⚠️ GitHub App configured but live load failed — showing bundled synthetic data`
    with the recorded reason displayed.
  - not configured → existing amber "not configured" message.
- Render any non-fatal data-quality warnings from FIX-B1.

### FIX-C2 — No silent mock substitution (`app/clinician_ui.py`)

- If `raw_template` resolves empty while live data is expected, set
  `live_pipeline_notice` (or a distinct data-level notice) rather than silently
  taking the mock branch.
- Distinguish the two failure classes in the banner text so a clinician can tell
  a *model* outage from a *data* outage:
  - "Live model call unavailable …"
  - "Live clinical data unavailable …"

---

## 4. TDD Order (failing test first, per project convention)

| # | Test (new) | Asserts | Fix |
|---|---|---|---|
| 1 | `tests/test_llm_config.py::test_azure_key_names_resolve` | a section using only Azure key names yields a populated `ModelConfig` with `is_azure is True` and `deployment == MODEL_DEPLOYMENT` | FIX-A1 |
| 2 | `tests/test_llm_config.py::test_local_alias_uses_plain_openai_client` | local alias (empty api_version) resolves `is_azure is False` | FIX-A1 |
| 3 | `tests/test_llm_config.py::test_get_client_selects_azure_client` | `get_client` constructs `AzureOpenAI` for a remote alias and `OpenAI` for a local one (both patched) | FIX-A1 |
| 4 | `tests/test_github_loader.py::test_trailing_comma_json_is_parsed_and_warned` | payload with a trailing comma parses and records a warning | FIX-B1 |
| 5 | `tests/test_github_loader.py::test_adapt_modules_groups_by_category` | fixture mirroring the real schema yields `{category: {version: text}}` with all `instruction_text` values present verbatim | FIX-B2 |
| 6 | `tests/test_github_loader.py::test_adapt_orders_maps_upstream_fields` | every field in the FIX-B2 mapping table lands on the right canonical field | FIX-B2 |
| 7 | `tests/test_github_loader.py::test_failed_live_load_records_error_and_reports_mock_source` | on parse/network failure, status is `source="mock"` with a non-empty, credential-free `error` | FIX-B3 |
| 8 | `tests/test_github_loader.py::test_strict_mode_reraises` | `strict=True` propagates instead of falling back | FIX-B3 |
| 9 | `tests/test_ui_components.py::test_badge_reflects_actual_load_source` | badge text differs for `github_app` vs failed-load status | FIX-C1 |
| 10 | `tests/test_ui_components.py::test_empty_live_template_raises_data_notice` | empty `raw_template` under live config sets the data notice flag | FIX-C2 |

All existing 63 tests must continue to pass unchanged.

---

## 5. Live Acceptance Criteria (manual, after unit tests are green)

1. `fetch_remote_templates_and_orders(strict=True)` returns modules whose
   composed text is **not** equal to `load_mock_templates_and_orders()[0]`, and
   `get_last_load_status()["source"] == "github_app"`.
2. Adapted orders for `sickle_cell_pain` carry the upstream synthetic patient id
   and both upstream fever thresholds.
3. Sidebar badge shows the green GitHub App state, and the review pane's
   "Original Clinical Text" column contains upstream `instruction_text` content.
4. "🚀 Generate Instructions" with a remote alias completes **without** the
   "Live model call unavailable" banner, and `evaluation_metrics` are populated
   from a genuine model response.
5. Verbatim locks still hold: every protected value in `ClinicalOrders`
   (doses, both thresholds, all phone numbers) appears verbatim in `simplified_en`;
   any mismatch populates `verbatim_mismatches` and blocks sign-off.
6. Safety Judge failure still degrades to `FLAGGED_FOR_REVIEW` rather than crashing.

---

## 6. Governance Constraints (binding on the implementer)

- **Never** read, print, log, echo, or commit `~/.streamlit/secrets.toml`, any
  private key file, JWT, installation token, or API key. Diagnose using
  Streamlit's `st.secrets` API and structural facts (key names, booleans,
  lengths) only.
- **Zero disk writes** of clinical templates, synthetic orders, or repaired JSON.
- **Zero AI-originated clinical prose** — adapters order and bind vetted upstream
  text; they must not author or paraphrase medical content.
- Spanish output remains gated on dual translation + back-translation verification.
- Work stays on the participant branch (currently `trackABC`); never commit to `main`.
- Upstream data defects (RC-2) should additionally be reported to the
  `stjude-biohackathon/team7-data` owners so the trailing comma is fixed at source.

---

## 7. Out of Scope

- Rewriting the offline Phase 1 `generate()` / `recheck_edits()` paths.
- Changing `schemas/instruction_packet.py` (would require a multi-track sync gate).
- Any modification to the upstream data repository from this codebase.

---

## 7. Resolution Log (implemented & live-verified)

| Fix | Outcome |
| --- | --- |
| FIX-A1 | `pipeline/llms.py` resolves Azure key names (`AZURE_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_ENDPOIN`, `MODEL_DEPLOYMENT`) and builds `AzureOpenAI` vs `OpenAI` accordingly. Verified with a real completion. |
| FIX-B1 | `parse_json_tolerantly()` retries once past the upstream trailing comma and records a visible data-quality warning instead of hiding it. |
| FIX-B2 | `adapt_modules()` / `adapt_orders()` translate the real upstream schema (`instructions[]`, `synthetic_orders[]`) into the canonical contract. `type` → section mapping is clinician-supplied. |
| FIX-B3 | `get_last_load_status()` records `source`/`error`/`warnings`; `strict=True` re-raises; errors are sanitised of credentials. |
| FIX-C1 | The sidebar badge is driven by the *actual* load source, not credential presence. A configured-but-failed load shows red with the sanitised reason. |
| FIX-C2 | Model outage, data outage, and upstream data-quality warnings are three distinct notices. `describe_model_error()` reports the real cause (missing credentials vs HTTP 403 vs unreachable endpoint) without leaking keys or endpoints. |

### Follow-on decisions (clinician-directed, 2026-09-17)

1. **Default LLM1 changed `gpt52` → `gpt4o`.** The `gpt52` endpoint returns HTTP 403
   (Virtual Network/Firewall) from the deployment host, so the previous default
   silently degraded every first run to offline mock output.
2. **Verbatim locks now bind extracted safety values, not whole field strings.**
   Upstream order fields bundle prose with the protected value
   (`"555-0144 (Pediatric Hematology Day Clinic, M-F 8am-5pm)"`). `extract_safety_values()`
   pulls doses, temperatures, and phone/emergency numbers; descriptive text is not locked.
   - Both units of a dual-unit threshold are locked (`100.4°F` **and** `38.0°C`) — a dropped
     conversion is real content loss.
   - `911` is a protected value; otherwise the emergency field has no machine-checkable anchor.
   - A product strength (`100 mg/5 mL`) is one atomic token, never split into `100 mg` + `5 mL`
     (splitting produced tokens `check_verbatim` could never match, since it refuses a dose
     followed by `/`).
   - Fields with no extractable clinical value are not locked as prose.
3. **The deterministic safety gate now vetoes the live judge.** `_enforce_deterministic_safety_gate()`
   forces `FLAGGED_FOR_REVIEW` whenever regex parity fails in the English, Spanish, or
   back-translated pane, regardless of the LLM2 verdict. Numeric/unit parity is a hard
   sign-off block and a model may not waive it. The live path previously discarded the
   deterministic result entirely, so a judge returning `PASS` masked a real mismatch.

### Outstanding — needs a human with write access

The upstream defect could **not** be filed automatically: the GitHub App installation holds
read-only `contents` scope, so `POST /issues` returns `403 Resource not accessible by integration`.
An issue should be opened manually on `stjude-biohackathon/team7-data` for the trailing comma in
`data/modules/pediatric_discharge_instruction_templates.json` (`_readme` object, ~line 22).

### Test hermeticity note

Once live credentials resolve, `AppTest` runs will call the real GitHub App and the real
models. Unit tests must therefore patch `storage.github_loader.fetch_remote_templates_and_orders`,
`storage.github_loader.get_last_load_status`, and `PipelineOrchestrator.generate_live` /
`recheck_edits_live` (see `offline_app()` in `tests/test_ui_components.py`), and clear
`st.cache_data` between runs.
