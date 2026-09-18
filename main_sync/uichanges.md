- what is packet? (get rid of it)
- change diagnosis label to be called module
- in the main clinician interface instead of 4 columns, the default should only be original clinician orders and simplified english. 
remove some padding between top of page and title
this is a workflow change, but the simplified instructions should not be translated to spanish automatically. there should be another button / option to translate to spanish and backtranslate if applies for family. 
CAN BE REMOVED - 2. In-Memory Data Stream
Source: ☁️ GitHub App (In-Memory, No Local Copy)
Zero local copies • In-memory stream
NEW FRONT PAGE LAYOUT: 
("Bilingual Pediatric Discharge Instruction Review") - below this title in the main homepage, 
show patient MRN(fill with patient id value): (patient age) 

Below the patient age and MRN, show current module ("module: ") (which we can select from the sidebar) this should change immediately if we change the module from sidebar. 
below module, have the generate simplified instructions button. To the right of this button, have a checkbox that confirms if they want the spanish translation (this should also generate the english backtranslations) 
below the generate button and checkbox,
have the original clinical instructions in the rest of the page. It should be inside a box as it is now so u scroll within the box but the box should take the whole screen. 

After generate instructions are clicked (and spanish box is not checked), there should be 2 boxes side by side on the left is original and on the right is simplified english. There should be a slider along the inside to alter their screen view percentage. 
Show the FKGL readability score, verbatim score and judge review in place of where the generate button was. Display the 3 cleanly and round the FGKL score to the nearest 10th and verbatim score to the nearest whole number. 
remove the locked safety tokens that are correct and
Show the missing safety tokens when you hover over the verbatim score. 
If the spanish is checked, do the same views but instead of 2 boxes make 4 boxes side by side: original, simplified, simplified in spanish, span simplified back translated to eng.


## Implementation status

All requested items above are implemented in `app/clinician_ui.py` and connected review/export paths:

- Patient MRN/age, immediate module selection, reduced title padding, main-page generation controls, and full-width scrollable original preview.
- English-only by default; the family checkbox opts into Spanish and English back-translation. Translation calls are skipped for English-only generation and rechecking.
- Two or four review panes with a width-percentage slider; metrics replace generation controls. FKGL uses one decimal, verbatim uses whole percentages, and missing tokens appear in its help tooltip.
- Removed the data-stream panel, correct-token lists, user-facing "packet" terminology, diagnosis labels, and decorative emojis. The internal `InstructionPacket` contract is retained.
- English-only approval/export works without a Spanish attestation or empty Spanish PDF column. Spanish review still requires fresh authorized attestation. Input changes clear stale reviews; New Generation returns to the preview.
- Refresh Protocols, actionable data-loading failures, safety checks, revision checks, and session-only history remain available.

Verified with 140 automated tests using synthetic fixtures and mocked external services. Live-service and authorized clinical acceptance remain pending. See `plan.md` and `specs/03_TRACK_C_CLINICIAN_UI_UX.md` for the updated workflow contract.
