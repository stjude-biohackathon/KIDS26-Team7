# Phase 1 integration at the repository root

The runnable application is now in `KIDS26-Team7/`. Participant directories were
used as sources and left intact. Integration changes apply only to the root copy;
continue shared integration work there to avoid diverging copies.

## Source selection

| Track | Latest participant source | Root components |
| --- | --- | --- |
| A — pipeline and checks | `kartik/` | `pipeline/`, pipeline/configuration tests |
| B — data, schema, records, PDF | `nima/` | `schemas/`, `storage/`, `exporters/`, component/loader tests |
| C — review UI | `ramzi/` | `app/`, UI tests |

All three schema copies and specification sets agreed. The canonical schema was
copied unchanged. Shared `plan.md`, `specs/`, and `AGENTS.md` are now available at
the root, along with requirements and local-file ignore rules. No virtual
environments, credentials, generated data, or participant-only scratch files
were copied into application packages.

## Runtime connections

1. Track B's `load_mock_templates_and_orders()` supplies the selected source and
   structured orders. The UI labels this as mock data and derives version menus
   from the actual loader results.
2. Track C's existing demo wording is retained in `app/mock_components.py`.
   Its compatibility entrypoint calls `PipelineOrchestrator.generate()` with the
   supplied English/Spanish/back-English strings. It no longer constructs a
   competing packet or uses a separate evaluator.
3. Track A calculates real FKGL and exact-value results. Its original-source copy,
   independent order snapshot, and pending-review defaults remain intact.
4. The UI renders all four panes, includes the real checker explanations, and
   calls Track A's `recheck_edits()` to produce separate pending revisions.
5. Review decisions use Track B's PDF exporter and serialized record snapshots.
   The UI keeps records in a browser-session-owned list; loading a record returns
   a new object, so later edits do not change history.

The root packages and tests do not import code from participant directories.
The existing `kartik/venv/bin/python` is just a convenient installed interpreter.

## Integration resolutions

- **Conflicting evaluator behavior:** the old UI evaluator normalized values and
  could fabricate a readability score. Compatibility calls now delegate to Track A.
  A clean mock check means `NEEDS_REVIEW`; a value mismatch means `FLAGGED_FOR_REVIEW`.
- **Storage versus governance:** Nima's file-based JSONL interface became an
  in-memory serialized-record interface. `save_to_gold_library(packet, library=...)`
  and `load_gold_records(library=...)` use the supplied session list. The old
  `file_path` parameter is not supported in this Phase 1 integration. Test records
  also remain in memory.
- **Edit behavior:** rechecking replaces the active packet with a new revision,
  clears prior bilingual output, and retains the previous packet in session history.
  The UI no longer presents word replacements as a new Spanish translation.
- **Review gate:** changed-but-unchecked English, missing bilingual outputs,
  flagged values, and missing Spanish review confirmation block approval. The
  reviewer name and confirmation are recorded in the existing `clinician_notes`
  field; no shared schema fields were added. Confirmation is an attestation,
  not an institutional identity/credential check.
- **UI integration:** the order version stores its real version rather than a
  decorated menu label; medication widgets are keyed by condition; rejection
  dialogs survive reruns and have explicit cancel/dismiss handling.
- **PDF rendering:** supplied rejection notes and metadata are escaped as text
  before ReportLab sees them, preventing tag-shaped text from breaking the PDF.
- **Portable tests:** Streamlit tests resolve the root app relative to their own
  file. Schema tests use the root contract without importing a participant copy.

## Validation and known limits

The root test suite covers schema compatibility, all three condition screens,
real value/readability checks, edit revision independence, isolated session
history, approval with a complete neutral fixture and Spanish confirmation,
rejection/PDF generation, and offline loader behavior. Live HTTP calls are mocked
in the loader unit tests; the UI explicitly selects the mock loader.

The supplied clinical demo paragraphs were preserved. For default orders,
sickle-cell and nausea/hydration text omit the emergency fever threshold; the
fever/neutropenia text omits its medication dose. The real checks therefore flag
those demo packets. Approved content must address these omissions before those
packets can be approved. A neutral, complete synthetic fixture exercises the
positive approval path in the integration tests without inventing new care advice.

The prepared wording includes fixed medication names/schedules and is not a
universal composer for arbitrary edited orders. The value checker does not prove
semantic correctness, detect every contradiction, or verify translation quality.
Missing values are not silently appended to make a fixture pass. An English edit
invalidates both bilingual outputs; Phase 1 does not translate the revision.

Records are ephemeral: resetting the session loses its history. No disk-backed
clinical persistence or real identity/role verification is introduced here.
Track C's existing synthetic drift demonstrations remain mock scenarios, not a
live LLM safety judge. Track B's existing live-loader helpers are included but
are not activated or certified by this Phase 1 merge.

## Run and synchronize

From the repository root:

```bash
kartik/venv/bin/python -m streamlit run app/clinician_ui.py
kartik/venv/bin/python -B -m unittest discover -s tests -v
kartik/venv/bin/python -B tests/test_components.py
kartik/venv/bin/python -B tests/test_github_loader.py
kartik/venv/bin/python -B tests/test_llm_config.py
kartik/venv/bin/python -m py_compile app/clinician_ui.py
```

Use the setup instructions in the root README for a fresh `.venv`. Phase 1 needs
no live credentials. At Sync 1, review the root changes together and use the
team's commit/push/PR workflow when ready; this integration does not commit,
push, merge branches, or proceed to live Phase 2 work.
