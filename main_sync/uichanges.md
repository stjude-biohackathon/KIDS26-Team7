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
