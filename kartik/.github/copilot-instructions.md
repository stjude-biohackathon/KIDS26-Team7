# Copilot Instructions — CLEAR (kartik track)

## Project state
This directory has no implementation code yet — only planning docs (`plan.md`, `specs/`, `AGENTS.md`, `requirements.txt`). Before writing code, read `plan.md` and the relevant file(s) in `specs/` (`00_OVERVIEW_AND_SCHEDULE.md` through `04_INTEGRATION_TEST_PLAN.md`); they are the authoritative spec, not this file.

## Who this track is
Per `../project-management/team.md`, this repo implements **CLEAR**: an AI-assisted, clinician-in-the-loop tool that turns pediatric discharge instructions into plain-language, bilingual (EN/ES) handouts. Work is split into three decoupled tracks against a shared Pydantic contract in `schemas/instruction_packet.py` (not yet created):
- **Track A — Pipeline & Safety** (`pipeline/`): LLM1 simplifier, FKGL/verbatim quality gate, LLM2 safety judge, EN→ES translation + back-translation.
- **Track B — Data & Storage** (`schemas/`, `storage/`, `exporters/`): canonical schema, in-memory GitHub App loader (zero-disk), JSONL versioned library, bilingual PDF exporter.
- **Track C — Clinician UI** (`app/`): Streamlit review dashboard (`app/clinician_ui.py`).

`kartik/AGENTS.md` assigns Track A (pipeline & safety) to this participant (with Ramzi). **Do not implement Track B/C code from here** unless the user explicitly says they're also covering that track — confirm the assigned track before writing any code, per `AGENTS.md` §3.

## Non-negotiable governance (from `AGENTS.md`)
- **Spec-driven / TDD**: write failing tests before implementation for sentinel protection/restoration, numeric parity, red-flag presence, translation authorization, and immutability.
- **Zero AI-originated clinical prose**: never generate or rewrite clinical content; only bind clinician-vetted, structured order values.
- **Sentinel protection & parity**: mask safety-critical values (doses, thresholds, phone numbers) before any LLM call and restore them verbatim after. A numeric/unit mismatch is a hard sign-off block.
- **Translation gate**: Spanish output requires sign-off from an authorized translator/bilingual clinician; this is a hard block, not a suggestion.
- **Zero real patient data**: synthetic/de-identified fixtures only; never fetch-and-persist data — stream it on the fly.
- **Branch discipline**: never commit implementation work on `main`. Confirm the user's dedicated branch first:
  ```bash
  git checkout <branch>
  git fetch --all
  git pull
  ```
  At a track sync point (see `specs/00_OVERVIEW_AND_SCHEDULE.md` merge gates), stop and tell the user to commit/push and open a PR instead of merging locally.
- **Secrets**: never commit `.streamlit/` (instruct the user to relocate it) or `data/`; both must be gitignored. Never print/commit API keys or App IDs — sanitize before any commit.

## Planned architecture (per `specs/`)
End-to-end pipeline (see `plan.md` §2 for the diagram): `LLM1 simplify → quality gate (FKGL + verbatim regex + LLM2 judge) → LLM1 translate to ES → LLM2 back-translate to EN → clinician review UI (Approve / Edit / Reject) → versioned JSONL log + bilingual PDF + interactive family view`.

Track A component contracts (`specs/01_TRACK_A_PIPELINE_AND_SAFETY.md`):
- `pipeline/orchestrator.py` — LLM1 simplifier; enforce FKGL 5.0–6.9, ≤15 words/sentence, second-person voice, verbatim-preserve meds/doses/units/thresholds/phone numbers.
- `pipeline/evaluator.py` — quality gate: `textstat.flesch_kincaid_grade`; verbatim regex extraction for doses (`mg|mL|mcg|g|tablets?|capsules?|drops?`), temperatures (`°?[FC]`), phone numbers; every token from `orders` must appear verbatim in output or it's logged to `EvaluationMetrics.verbatim_mismatches`.
- LLM2 safety judge + Scenario C drift simulator for negative testing (inject synthetic hallucinations to prove the gate catches them).

## Planned commands (not yet runnable — no code exists)
Per `specs/04_INTEGRATION_TEST_PLAN.md`, sync-gate checks will be:
```bash
python -c "from schemas.instruction_packet import InstructionPacket; print('Schema OK')"
python tests/test_components.py
python tests/test_github_loader.py
python tests/test_llm_config.py
python tests/test_pipeline.py      # Track A
python -m py_compile app/clinician_ui.py   # Track C
streamlit run app/clinician_ui.py
```
Dependencies are pinned in `requirements.txt` (openai, pydantic, textstat, reportlab, streamlit); install into `venv/` before running anything.
