ERRORR: even when everything passes, approve and publish gives this error.
reportlab.platypus.doctemplate.LayoutError: Flowable <Table@0x78B4915C6210 1 rows x 2 cols(tallest row 1170)> with cell(0,0) containing
'<Paragraph at 0x78b4915c5f40>ENGLISH (5th–6th Grade)### Discharge Instructions for Your C'(530 x 1170), tallest cell 1170.0 points,  too large on page 2 in frame 'normal'(528.0 x 708.0*) of template 'Later'

File "/home/ralsallaq/KIDS26-Team7/main_sync/app/clinician_ui.py", line 741, in <module>
    pdf_data = live_pdf_gen(packet)
               ^^^^^^^^^^^^^^^^^^^^
File "/home/ralsallaq/KIDS26-Team7/main_sync/exporters/pdf_generator.py", line 175, in create_bilingual_pdf
    doc.build(elements)
File "/home/ralsallaq/KIDS26-Team7/venv/lib/python3.12/site-packages/reportlab/platypus/doctemplate.py", line 1322, in build
    BaseDocTemplate.build(self,flowables, canvasmaker=canvasmaker)
File "/home/ralsallaq/KIDS26-Team7/venv/lib/python3.12/site-packages/reportlab/platypus/doctemplate.py", line 1083, in build
    self.handle_flowable(flowables)
File "/home/ralsallaq/KIDS26-Team7/venv/lib/python3.12/site-packages/reportlab/platypus/doctemplate.py", line 962, in handle_flowable
    raise LayoutError(ident)