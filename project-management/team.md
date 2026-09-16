# Team and Roles

- **Team name:** [Team7, Team-CLEAR]
- **Team lead:** [Ramzi Alsallaq, ralsallaq]
- **Communication channel:** [https://stjudebiohackathon.slack.com/archives/C0BS7NTMAV9]
- **Project question/problem:** [Clinician-Led, Easy-to-read, Accessible Reaffirmed Instructions]
- **Expected output:** [UI/UX for clinician to use with bilingual EN/ES handout that is safe and easy to read for patients]
- **Tools and stack:** [Python, llms]

## Roles
| Team Member | Domain | Scope & Responsibilities | Key Dependencies / Deliverables |
|:---|:---|:---|:---|
| **Person 1 (P1)** | **AI Pipeline & Safety Judge Engine** | • LLM1 Simplification & Spanish translation prompts.<br>• LLM2 Evaluator prompt (drift, omission scoring) & back-translation.<br>• Automated regex verbatim-preservation checker.<br>• Textstat integration (FKGL, Coleman-Liau). | `pipeline/orchestrator.py`<br>`pipeline/evaluator.py`<br>`pipeline/prompts.py` |
| **Person 2 (P2)** | **Clinician UI & Workflow (Streamlit/Web)** | • Clean, hospital-grade review dashboard.<br>• Module picker & discharge order input forms.<br>• 4-pane comparative view (Original, Simple, Spanish, Back-EN).<br>• Drift alert banners, score gauges, inline edit mode, reject modal. | `app/clinician_ui.py`<br>`app/components/`<br>`app/styles/` |
| **Person 3 (P3)** | **Data Architecture, PDF Engine & Family UX** | • Structured synthetic order library for all 3 disease tracks.<br>• Dual-language, print-ready PDF generator (ReportLab/WeasyPrint).<br>• Interactive responsive family web view.<br>• Versioned gold storage (JSONL/SQLite) for feedback loop. | `data/orders/`<br>`exporters/pdf_generator.py`<br>`storage/gold_library.py` |
| **Clinician Partner** | **Domain Expert & Evaluator** | • Review and calibrate verbatim clinical anchors (Day 1 EOD).<br>• Test-drive prototype with realistic order scenarios (Day 2 PM).<br>• Validate rejection threshold and readability fidelity. | Clinical feedback logs & sign-off |

P1: Kartikeya Bomb & Ramzi ALsallaq
P2 & P3:Prisha Chhabra & Nima Aflaki & Ramzi Alsallaq

Roles can overlap. Revisit them when the project direction or stack changes.
