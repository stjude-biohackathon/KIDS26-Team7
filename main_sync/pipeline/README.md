# CLEAR pipeline through Phase 3

Run from `main_sync` using the environment in the repository root:

```bash
../.venv/bin/python -m streamlit run app/clinician_ui.py
../.venv/bin/python -B tests/run_suite.py
```

The test runner uses synthetic fixtures and mocked external service boundaries. It blocks network requests, user-secret reads, and JSONL access. It is not a clinical certification or a live-service acceptance run.

## Composition and translation

`PipelineOrchestrator.generate()` binds supplied templates and order values without a model call. Optional supplied Spanish/back-translation templates support offline demonstrations. Missing translations remain unavailable.

`generate_live()` composes English from versioned source wording and structured orders, then calls LLM1 for Spanish and LLM2 for back-translation and safety judgment. It never asks a model to rewrite clinical English. Achieving the FKGL target depends on vetted source wording or clinician edits.

`pipeline/protection.py` masks numeric values and units before translation and judge calls. Translation output must preserve every sentinel and occurrence count. Missing/changed/extra sentinels and invented numbers fail explicitly. Judge outages, incomplete audit objects, and invalid verdicts become `FLAGGED_FOR_REVIEW`.

`recheck_edits()` and `recheck_edits_live()` create new pending revisions with `parent_packet_id`, without mutating the source. Offline rechecking clears translations; successful live rechecking regenerates them. Old physician decisions and Spanish attestations do not carry forward.

## Safety and Scenario C

One canonical evaluator measures FKGL and exact protected-value preservation. Approval checks all output panes, rejects additional unsupplied safety values, and conservatively requires exact English source-warning lines. These checks cannot certify clinical semantics; human review remains necessary.

`pipeline/drift.py` operates on synthetic copies only:

- Doubled medication dose.
- Altered fever threshold.
- Contradictory anti-emetic advice.
- Omitted source warning.

The evaluator checks the actual changed content, not just a scenario label. A scenario without a matching value or warning fails explicitly. Simulation packets cannot be approved for patient use.

## Review and export

The UI binds successful checks to an exact packet snapshot. Later edits require another check. Authorized Spanish verification is a per-revision attestation recorded in clinician notes; this prototype does not authenticate professional credentials.

`storage.gold_library.ReviewLibrary` keeps immutable copies in session memory. Repeated identical saves are idempotent, conflicting overwrites fail, and separate sessions do not share review history. Closing/resetting a session or restarting the server can lose that history. There is no JSONL/SQLite persistence.

Approval/rejection builds the PDF before saving the review. Long bilingual columns span pages with repeated headers, bold protected values, review badges, versions, timestamps, and page numbers. Rejected output is an audit copy marked not for patient use.

## Remaining acceptance work

The automated suite exercises all three conditions and review outcomes with synthetic providers. A live GitHub/model run and authorized clinical/translation validation remain pending. No commit, push, or merge is performed by this implementation.
