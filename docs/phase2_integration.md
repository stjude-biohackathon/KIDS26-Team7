# Phase 2: live integrations at the repository root

## What is implemented

The root Streamlit application has two explicit runtime modes. **Offline demo
(Phase 1)** remains the default and never calls model providers or fetches remote
clinical data. **Live integrations (Phase 2)** fetches a versioned GitHub catalog,
binds its supplied plain-language English to synthetic orders, translates to
Spanish, back-translates to English, and evaluates the complete packet with a
safety judge. Model aliases, module versions, and order-set versions are selected
in the sidebar. Refresh rereads the current session's live catalog.

This is implementation verified against mocked external services. No real GitHub
App/model credentials were available for a live acceptance run. The software is
not a clinical certification or a verification of institutional reviewer roles.

## Public interfaces and source contract

- `load_mock_templates_and_orders()` retains the offline fixtures.
- `fetch_remote_templates_and_orders()` is strictly live. Failure returns a
  sanitized error, never silently substituted mock data.
- `parse_remote_catalog(modules, orders)` validates remote data in memory.
- `PipelineOrchestrator.generate(...)` remains the offline entrypoint.
- `PipelineOrchestrator.generate_live(protocol, orders, *, module_version,
  condition)` composes English and invokes the selected providers.
- `recheck_edits(packet, edited_en)` returns an independent pending revision.
  Live revisions obtain fresh translations and judging; offline revisions clear
  bilingual output. Both clear prior review metadata and preserve the old packet.

Live modules are nested by condition and version. Each version must supply the
new `ProtocolTemplate` contract. This replaces the old bare-string source format;
plain-language clinical wording must be supplied by its vetted author, not
invented by the application. The following is a **neutral contract example**, not
patient guidance or an actually vetted protocol:

```json
{
  "demo": {
    "v1": {
      "original_text": "Synthetic reference. Example: $emergency_phone.",
      "plain_language_template": "Example: $emergency_phone.",
      "vetted_by": "Synthetic test reviewer",
      "vetted_at": "2026-09-17",
      "required_red_flags": []
    }
  }
}
```

The source owner supplies actual vetting metadata and the required English
red-flag snippets. Snippets may use the same order placeholders. They must appear
verbatim in bound English before requests proceed. An empty list asserts no
explicit snippets; it does not prove the absence of clinically important warnings.
The judge also compares the entire original source against the outputs.

Orders support multiple versions per condition:

```json
{
  "demo": {
    "v1": {
      "patient_id": "SYN-PED-001",
      "diagnosis": "Synthetic demonstration",
      "order_id": "SYN-ORDER",
      "order_version": "v1",
      "medications": [],
      "urgent_fever_threshold": "",
      "emergency_fever_threshold": "",
      "daytime_phone": "",
      "after_hours_phone": "",
      "emergency_phone": "911"
    }
  }
}
```

A single order object per condition is also accepted using its explicit
`order_version`. Catalog conditions must match. Each order must explicitly supply
`medications`, both threshold fields, all three phone fields, and `order_version`;
empty values are allowed but missing values do not receive demo defaults.
Patient IDs must match `SYN-PED-` followed by digits. This format check does not
anonymize arbitrary text: source owners must supply synthetic data only.

Packets now also contain `source_mode`, a copied `protocol`, `llm1_model`, and
`llm2_model`. Existing offline packets default to mock mode. These fields preserve
which source and routing choices produced a revision; they contain no credentials.

## Configuration

Use Python 3.11 or later, create the root `.venv`, and install `requirements.txt`.
Configuration is read from `~/.streamlit/secrets.toml`, then the ignored project
`.streamlit/secrets.toml`, with environment variables taking precedence. Keep real
credentials outside this repository. Do not paste them into chat or commit them.

GitHub App configuration uses the existing `[dataloader]` keys:

- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY_PATH`
- `GITHUB_DATA_REPO`
- `MODULES_PATH`
- `ORDERS_PATH`

The environment variables use those same names. The App must have access to the
configured repository and Contents read permission. Only the private key file is
read locally; repository contents are decoded directly into memory. Installation
tokens are cached in memory by App, installation, and key path for at most fifty
minutes, shortened to respect the server's expiry minus a minute.

Each selected model alias needs an explicit OpenAI-compatible endpoint, deployed
model ID, and API key. Aliases are `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`,
`local1`, and `local2`; none is assumed to be a real provider deployment name.
For example, the shape of a home secrets section is:

```toml
[gpt52]
model = "YOUR_DEPLOYED_MODEL_ID"
base_url = "https://YOUR_PROVIDER/OpenAI-compatible-base-path"
api_key = "SET_LOCALLY"
```

Alternatively use `CLEAR_GPT52_MODEL`, `CLEAR_GPT52_BASE_URL`, and
`CLEAR_GPT52_API_KEY` (replace `GPT52` with the selected alias). Role sections
`[llm1]`/`[llm2]` may supply these fields plus `alias`; a role is used only when
its alias matches the selected dropdown. Role environment variables follow
`CLEAR_LLM1_ALIAS`, `CLEAR_LLM1_MODEL`, `CLEAR_LLM1_BASE_URL`, and
`CLEAR_LLM1_API_KEY`, likewise for LLM2. Alias-specific values override role values.
The app never borrows one alias's credentials for another alias.

Endpoints require HTTPS, except HTTP on localhost. Native provider APIs that do
not implement this Chat Completions interface need an adapter; no such native
adapter is claimed. Requests have a thirty-second timeout and no automatic
retries, use `store=False`, and require complete non-refusal responses. The judge
endpoint must support JSON-object output. Provider errors and SDK debug request
logging are suppressed from the UI. `store=False` is not a claim about every
provider's retention policy; deployment owners must verify that separately.

## Live safety and review behavior

1. Bind the source owner's English wording; never rewrite or originate clinical
   instructions. Keep original source and independent structured-order snapshots.
2. Run real FKGL, exact structured-value presence checks, and declared English
   red-flag checks. Missing values/flags block requests and approval.
3. Mask medication names, structured doses/thresholds/phone numbers, and other
   numeric values with opaque sentinels. Recognized numeric units and time-unit
   phrases are masked together. Every live request, including the judge inputs,
   receives masked values. Patient/order IDs are omitted from judge inputs.
4. Require exactly the same sentinel occurrence counts in each translation, no
   unknown/malformed markers, and no newly introduced raw digits. Restore each
   protected value verbatim. Recognized unit phrases retain their source spelling,
   including English time-unit words; the authorized reviewer must assess whether
   the resulting bilingual presentation is suitable.
5. Judge source, structured orders, English, Spanish, back-English, and declared
   red flags. Require all schema fields with strict types and a finite risk score
   between zero and one. Findings override inconsistent PASS verdicts.
6. Any translation/protection/judge failure creates a flagged pending packet.
   Failed outputs stay unavailable; successful earlier outputs can remain visible
   for review. No fabricated translations or scores are substituted.
7. Live approval requires a complete PASS judge result, current bilingual output,
   source provenance, checked English, and a named authorized-Spanish-review
   attestation tied to that packet ID. A new edit creates a new pending ID and
   requires fresh authorization. Confirmation is an attestation, not a credential
   lookup. A machine PASS alone never approves a packet.

Sentinels cannot prove that prose is clinically correct. They do not detect every
written-out number, changed association, semantic omission, or contradictory
sentence. FKGL is a readability estimate, not a clinical quality score. Clinical
review and authorized Spanish review remain necessary even with passing checks.

Review snapshots, revision history, catalogs, and PDF bytes stay in memory. A
session reset loses history. Downloading a reviewed PDF is an explicit user action;
the server does not write it to a clinical data file.

## Validation and Sync 2 acceptance

```bash
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -m streamlit run app/clinician_ui.py
```

Validation result: 76 root tests passed; compilation and diff checks passed.
Tests use neutral synthetic fixtures. Provider doubles echo protected text to
verify routing/restoration; they do not demonstrate Spanish accuracy. The UI
integration test mocks only GitHub HTTP and the external OpenAI client, uses a
temporary test signing key, and exercises actual JWT construction, catalog
validation, version/model selections, edit retranslation, authorization, approval,
and refresh. Existing Phase 0–1 regression tests remain in the same suite.

Before Sync 2 can be called externally accepted, configure the real services,
provide a compatible vetted catalog, execute an authenticated end-to-end run, and
obtain clinical/authorized translation review. Commit, push, and create a reviewed
PR at the synchronization checkpoint. No commit, push, merge, or Phase 3 work is
performed by this implementation.

Implementation references: [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat)
and [GitHub repository Contents API](https://docs.github.com/en/rest/repos/contents#get-repository-content).
