# CLEAR pipeline through Phase 3

Run from `main_sync` using the environment in the repository root:

```bash
../.venv/bin/python -m streamlit run app/clinician_ui.py
../.venv/bin/python -B tests/run_suite.py
```

The test runner uses synthetic fixtures and mocked external service boundaries. It blocks network requests, user-secret reads, and JSONL access. It is not a clinical certification or a live-service acceptance run.

## Composition and translation

`PipelineOrchestrator.generate()` binds supplied templates and order values without a model call. Optional supplied Spanish/back-translation templates support offline demonstrations. Missing translations remain unavailable.

`generate_live()` composes source English and orders, then calls LLM1 only to simplify the existing instructions in their original order. It may replace difficult words and split long sentences, but must not generate a rewritten handout, add advice or explanations, reorganize instructions, or omit their meaning. It measures restored-text FKGL and retries from the source up to three times with score feedback to reach 5.0–6.9. Unmet targets stop generation explicitly before translation. If Spanish is requested, LLM1 translates the passing text and LLM2 back-translates. LLM2 judges English safety in either case. The UI defaults to `translate=False`; the backend retains its bilingual default for compatibility. Normal UI generation always uses this live path; offline helpers remain for tests and local simulations only.

`pipeline/protection.py` masks numeric values and units before translation and judge calls. Output must preserve every distinct sentinel at least once; repetition counts need not match. Each instruction and its associated values must still survive semantic review. Missing/changed/extra sentinels and invented numbers return a blocked, reviewable draft with stage-labeled failure details. Only exact known markers are restored for display; missing values are not inserted and malformed markers stay visibly unresolved. Later stages stop, and no model safety pass is claimed. Fresh edit checks require each distinct source numeric value at least once before clearing failures on a new revision. Judge outages, incomplete audit objects, and invalid verdicts become `FLAGGED_FOR_REVIEW`.

`recheck_edits()` and `recheck_edits_live()` create new pending revisions with `parent_packet_id`, without mutating the source. Offline rechecking clears translations; successful live rechecking regenerates them only when requested; English-only rechecking skips both translation calls. Old physician decisions and Spanish attestations do not carry forward.

## Safety and Scenario C

One canonical evaluator measures FKGL and exact protected-value preservation. Approval checks all output panes, rejects additional unsupplied safety values, and requires FKGL 5.0–6.9 and no judge-reported omissions or contradictions; warning wording may change while meaning must survive. These checks cannot certify clinical semantics; human review remains necessary.

`pipeline/drift.py` operates on synthetic copies only:

- Doubled medication dose.
- Altered fever threshold.
- Contradictory anti-emetic advice.
- Omitted source warning.

The evaluator checks the actual changed content, not just a scenario label. A scenario without a matching value or warning fails explicitly. Simulation packets cannot be approved for patient use.

## Review and export

The UI binds successful checks to an exact packet snapshot. Later edits require another check. When Spanish is requested, authorized Spanish verification is a per-revision attestation recorded in clinician notes; this prototype does not authenticate professional credentials.

`storage.gold_library.ReviewLibrary` keeps immutable copies in session memory. Repeated identical saves are idempotent, conflicting overwrites fail, and separate sessions do not share review history. Closing/resetting a session or restarting the server can lose that history. There is no JSONL/SQLite persistence.

Approval/rejection builds the PDF before saving the review. English-only PDFs use one full-width column and an English banner. Long English or bilingual columns span pages with repeated headers, bold protected values, review badges, versions, timestamps, and page numbers. Rejected output is an audit copy marked not for patient use.

## Remaining acceptance work

The automated suite exercises all three conditions and review outcomes with synthetic providers. A live GitHub/model run and authorized clinical/translation validation remain pending. No commit, push, or merge is performed by this implementation.
