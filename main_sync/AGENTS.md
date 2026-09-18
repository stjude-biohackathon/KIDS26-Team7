# CLEAR — Engineering & Governance Guidelines

## 1. Development Principles & Governance
- **Spec-Driven Development (SDD):** plan.md and files under `specs/` are the authoritative specifications. Build strictly to these documented schemas, state machines, and API contracts.
- **Test-Driven Development (TDD):** Write failing unit/regression tests before writing implementation code for core services—especially sentinel protection/restoration, numeric parity, red-flag presence, translation authorization, and immutability.
- **Investigate, Never Assume:** Do not guess causes or mask unexpected behavior. Always inspect code, data fixtures, and logs to identify and solve root causes directly.

## 2. Clinical Safety & Institutional Translation Governance
- **Source-Grounded Simplification:** Clinical facts originate solely from clinician-vetted, versioned instructions and orders. The composer binds order values; LLM1 then simplifies English to measured FKGL 5.0–6.9 before Spanish translation. Rephrasing is authorized; invented facts and omitted clinical meaning are not. Preserve protected values verbatim, require safety judging, and retain clinician and authorized Spanish review.
- **Authorized Translation Gate:** All patient-facing Spanish guidance must be vetted by authorized personnel (certified medical translator or credentialed bilingual clinician). Accurate and precise Spanish translation is a hard sign-off block. 
- **Sentinel Protection & Parity:** Safety-critical values (doses, thresholds, phone numbers) are masked  before any LLM processing and restored verbatim. Numeric/unit parity mismatch is a hard sign-off block.
- **Zero Real Patient Data:** Use synthetic, de-identified fixtures only. Never introduce real identifiers. Never save data on desk, obtain data on the fly and process it without saving.

## 3. Implementation Governance
- **Track-specific implementation** Do not proceed with any implementation before determining which participant the user is assigned to and only implement the track for that participant according to the plan and specs for that participant as described in the authoritative specs. A user can act as more than one participant and you can implement more than one track.
- **Branch-specific development** Do not do implementations on main branch, ask the user for their dedicated branch and do or instruct them to do the following before  proceeding to do any work:

 ```bash
    git checkout <user dedicated branch>
    git fetch --all
    git pull
 ```
- **Merging branch to main** Pause and instruct the user to commit and push their changes and create a pull request to merge to main, when the track implementation reaches a synchronization point that needs to merge to other tracks for testing the entire project as specified in the Git Branching & Merge Strategy in the specs.
## 4. Secrets governance
- **Do not commit .streamlit folder instruct user to move it to their home directory or add it to .gitignore**
- **Do not keep, print, or commit any API keys, App IDs, or any other secrets, sanitize files before committing**
- **Do not commit data/ folder and add it to .gitignore**
