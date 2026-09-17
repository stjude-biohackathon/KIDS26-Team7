# Track A — Sync Point 1 handoff

Participant 1, branch `kartik`. The latest combined code in `kartik/` is the
baseline. Phase 1 implements the offline mock engine against the existing
canonical schema; live model calls belong to Phase 2.

## What works

- `PipelineOrchestrator.generate()` binds structured order values into supplied
  templates and returns a new `PENDING` packet with real evaluation metrics.
- The original source is retained byte-for-byte in `original_clinical_text`.
  `clinical_orders` is a deep copy, including nested medication records.
- `evaluate_text()` calculates English FKGL using `textstat`, and checks exact
  doses, temperature thresholds, and phone numbers with escaped regex matches.
- `recheck_edits()` returns a new pending revision with new metrics, ID, and
  timestamp. It preserves the old packet, clears its review metadata in the new
  revision, and invalidates the previous bilingual output.
- `python -m pipeline.demo` shows the four text outputs without APIs or file writes.

The rule-based mock **binds supplied wording; it does not rewrite clinical prose**.
This follows `AGENTS.md`. Callers can supply a separate plain-language template
alongside the original reference. Actual clinical wording must come from vetted,
versioned sources. The neutral synthetic examples in tests/demo are not vetted
clinical instructions. Spanish and back-translation are supplied mock templates,
not model-generated or human-authorized translations.

## Public interfaces for Tracks B and C

```python
pipeline = PipelineOrchestrator(llm1_model="gpt52", llm2_model="gpt4o")
packet = pipeline.generate(
    original_template,
    orders,
    module_version=selected_module_version,
    condition=selected_condition,
    simplified_template_text=plain_language_template,
    spanish_template_text=spanish_mock_template,
    back_translation_template_text=back_translation_mock_template,
)
revision = pipeline.recheck_edits(packet, edited_en)
metrics = evaluate_text(english_text, orders)
```

`condition` is now required explicitly to populate the shared packet; it is not
inferred from free-text diagnosis. The three output-template keywords are new
optional arguments for the mock stage. No shared schema fields were added.
If the English template is omitted, the original template is bound unchanged.
Omitted bilingual templates produce empty output fields and explicit unavailable
messages in `safety_judge.explanation`; they never produce fake translations.

Templates use Python `string.Template` placeholders:

- `$urgent_fever_threshold`, `$emergency_fever_threshold`, `$daytime_phone`,
  `$after_hours_phone`, `$emergency_phone`, and other string-valued order fields.
- `$medication_0_name`, `$medication_0_dose`, `$medication_0_route`,
  `$medication_0_frequency`, `$medication_0_special_instructions`; index 1 refers
  to the second medication, and so on.
- `${medication_0_dose}` is also supported; `$$` represents a literal dollar sign.

Missing/malformed placeholders, blank supplied templates, missing source/version
metadata, and failed/nonfinite readability calculations raise `ValueError`.
Callers should display the error and keep their previous packet. Inserted values
are never recursively interpreted as template code.

## Interpreting the checks

`EvaluationMetrics` describes the English output. Repeated identical protected
values count once. Empty order fields are skipped; with no protected values,
the match percentage is 100% but is not evidence of clinical correctness.
Full structured values are retained rather than extracting only a recognizable
substring of a dose. Regex boundaries reject partial matches such as `5 mg`
inside `15 mg`, `0.5 mg`, or `5 mg/kg`. Matching preserves case, whitespace,
degree signs, and phone formatting exactly.

FKGL scores are not rounded before comparison. The target is **5.0–6.9**;
values below **4.0** or above **7.0** also receive the spec's wider review flag.
Both results are explained in the judge message. Track C can compute its target
badge directly from `5.0 <= metrics.fkgl_score <= 6.9`; the shared schema has no
`fkgl_target_met` field.

The judge result is explicitly a mock: `NEEDS_REVIEW` for a clean value check,
`FLAGGED_FOR_REVIEW` for missing/changed protected values. Supplied Spanish and
back-translation also receive verbatim checks; failures flag the judge message
without pretending that English FKGL measures Spanish readability. Numerical
risk scores and semantic findings in the shared schema remain uncomputed defaults.
This phase does not detect contradictions, swapped medication assignments, or
additional wrong values when the required value is also present.

All generated/rechecked packets remain `PENDING`. A real clinical safety judge,
sentinel masking before LLM calls, and authorized Spanish review are not supplied
by this mock. No LLM is called, even when credentials are already configured.

Rechecking cannot translate new English in Phase 1, so it clears Spanish and
back-translation. The caller must retain the original packet/revision if history
is needed; the engine stores no records on disk and does not make mutable Pydantic
objects globally immutable.

## Run locally

From `kartik/`:

```bash
venv/bin/python -B -m pipeline.demo
venv/bin/python -B tests/test_pipeline.py
venv/bin/python -B tests/test_llm_config.py
venv/bin/python -B tests/test_components.py
venv/bin/python -B -m unittest discover -s tests -v
venv/bin/python -m py_compile app/clinician_ui.py
```

Core behaviors were implemented using failing regression tests first. Coverage
includes real FKGL arithmetic, exact/altered values, metadata preservation,
readability failures, bilingual mismatches, and independent edit revisions.

## Stop at Sync 1

Track A's local deliverable is ready for team integration. **The shared Sync 1
gate is still pending:** the existing UI calls `app.mock_components.run_mock_pipeline`
and its old evaluator. It does not yet call the new Track A engine.

At the team sync:

1. Track B supplies the selected source, order object, versions, and matching mock
   output templates. Confirm the output templates belong to the selected module
   version; the current shared schema cannot prove that provenance.
2. Track C replaces its mock generation call with the interface above and its
   inline edit logic with `recheck_edits()`. Keep the previous packet separately
   when storing the returned revision. Render missing translation fields as
   unavailable, and consume the real metrics instead of the old mock evaluator.
3. Run the shared component/syntax checks, launch Streamlit, generate a packet,
   and verify all four panes plus FKGL/verbatim badges. Recheck an edit and verify
   the prior packet stays unchanged and the new revision is pending.
4. Obtain team review and follow the documented commit/push/PR merge workflow
   when ready. No commit, push, PR, or merge was performed for this implementation.

Track B/C implementation and the canonical schema were not changed here. Stop
before Phase 2. Before live calls, reconcile the spec's AI simplification wording
with the no-rewriting rule and agree how vetted content and authorized Spanish
review will be represented. Live credential routing/translation/judging are Sync 2
work; the Scenario C simulator and final workflow hardening are later work.
