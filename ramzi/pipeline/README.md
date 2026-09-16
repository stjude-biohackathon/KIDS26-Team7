# Track A — Sync Point 0 handoff

Participant 1 works on branch `kartik`. Phase 0 supplies pipeline interface
stubs and a test harness, as specified in `plan.md`. The interfaces below are
proposals for the team to lock at Sync Point 0, not an agreed shared contract.

## Proposed public interfaces

| Interface | Inputs | Eventual result |
| --- | --- | --- |
| `PipelineOrchestrator(llm1_model=..., llm2_model=...)` | Model selections; defaults `gpt52` / `gpt4o` | Orchestrator configured with model identifiers |
| `PipelineOrchestrator.generate(...)` | `composite_template_text: str`, `orders: ClinicalOrders`, keyword-only `module_version: str` | `InstructionPacket` pending clinician review |
| `PipelineOrchestrator.recheck_edits(...)` | `packet: InstructionPacket`, `edited_en: str` | Re-evaluated `InstructionPacket`, still pending review |
| `evaluate_text(...)` | `text: str`, `orders: ClinicalOrders` | `EvaluationMetrics` |

These public interfaces are the test boundaries for the Phase 0 harness.
Generation, edit rechecking, and evaluation raise `NotImplementedError` until
the shared contract is available and their later phases are implemented.
There is no fallback packet, successful safety verdict, or translated text.
The stubs reference Track B's types only in annotations; Track A does not
define substitute schemas. Runtime annotation resolution requires the real
schema to be integrated at Sync Point 0.

`pipeline.llms.AVAILABLE_MODELS` uses the seven identifiers in the detailed
Track A and Track C specs: `gpt52`, `gpt4o`, `gpt56luna`, `kimik3`, `copus5`,
`local1`, `local2`. They are configuration aliases, not verified provider model
names. Phase 0 validates selections only; it does not resolve credentials,
create clients, or make model requests.

## Local checks

Run from `kartik/`, using the existing environment:

```bash
venv/bin/python tests/test_pipeline.py
venv/bin/python tests/test_llm_config.py
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m compileall -q pipeline tests
```

The scaffold tests use opaque in-memory inputs. They do not validate a
`ClinicalOrders` or `InstructionPacket` instance, nor certify clinical safety.
Schema-backed tests must be added after the shared contract arrives.

Validation at this handoff: all five scaffold tests pass (each behavior was
first checked with a failing test), both direct-script runners work, and
compilation succeeds. The schema import below was also run and fails with
`ModuleNotFoundError: No module named 'schemas'`. This is an outstanding shared
gate, not a completed Sync Point 0. The existing virtual environment's five
core packages match `requirements.txt`; the pre-existing requirements and
Copilot instructions were not modified.

## Required team synchronization

The shared Sync Point 0 gate is currently pending Track B:

```bash
venv/bin/python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
```

Track B owns `schemas/instruction_packet.py` and its schema tests. The team
needs to agree on `ClinicalOrders`, `MedicationOrder`, `InstructionPacket`,
`EvaluationMetrics`, and `SafetyJudgeResult`, their location/import path, and
the proposed generation/recheck signatures above. No schema was created here.

Contract decisions to settle together:

- Preserve original textual doses, units, thresholds, and phone numbers;
  agree how source warnings and red flags reach the evaluator.
- Represent vetted content versions/provenance and authorized Spanish review.
  Specify how edits invalidate prior checks and translation authorization.
- Agree on pending-review defaults, blocking safety results, and immutable
  approved versions without conflating an AI verdict with human approval.
- Reconcile the simplification specs with `AGENTS.md`, which prohibits
  generating or rewriting clinical instructions. No clinical rewriting or
  prompt implementation is included in Phase 0.
- Clarify FKGL target `5.0–6.9` versus flags only below `4.0` or above `7.0`.
- Confirm the seven model aliases above versus references elsewhere to six
  models or a single `local` alias.
- Resolve the no-data-on-disk rule versus Track B's planned JSONL storage.

Stop here before Phase 1. At this handoff, review the local changes and
coordinate the shared contract with Tracks B and C. The documented merge
workflow is a team-reviewed PR; no commit, push, or merge is performed by this
implementation step. Once synchronized, Phase 1 adds the deterministic mock
pipeline, readability, and verbatim checks with tests written first.
