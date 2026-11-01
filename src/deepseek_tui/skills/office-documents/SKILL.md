---
name: office-documents
description: Create or edit Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files from a script. Use for any task that produces or changes these formats.
---

# Office documents

Run these scripts with the interpreter named `office python` in `## Environment`. It already has python-docx, openpyxl and python-pptx, so do not install anything. If the environment lists none, say so instead of installing into the user's system.

Write the script to a file in the workspace and run it. After saving, open the file again and read back what you need to confirm.

## Word

```python
from docx import Document

doc = Document()                      # or Document("existing.docx") to edit
doc.add_heading("Title", 0)
doc.add_paragraph("Body text")
table = doc.add_table(rows=1, cols=2)
table.style = "Table Grid"
table.rows[0].cells[0].text = "Item"
doc.save("out.docx")
```

Reading back: `[p.text for p in Document("out.docx").paragraphs]` does not include table text; use `doc.tables[0].cell(0, 0).text`.

## Excel

```python
from openpyxl import Workbook

book = Workbook()                     # or load_workbook("existing.xlsx")
sheet = book.active
sheet.title = "Summary"
sheet.append(["Month", "Amount"])
sheet.append(["Jan", 100])
sheet["B3"] = "=SUM(B2:B2)"
book.save("out.xlsx")
```

openpyxl does not calculate. A formula it wrote reads back as the formula text, and as `None` with `data_only=True`, until Excel or LibreOffice opens the file. Compute any number you report yourself in Python; do not expect to read it from the sheet.

## PowerPoint

```python
from pptx import Presentation
from pptx.util import Inches

deck = Presentation()                 # or Presentation("existing.pptx")
slide = deck.slides.add_slide(deck.slide_layouts[1])
slide.shapes.title.text = "Title"
slide.placeholders[1].text = "Point"
box = slide.shapes.add_textbox(Inches(1), Inches(5), Inches(4), Inches(1))
box.text_frame.text = "Note"
deck.save("out.pptx")
```

Reading back: `[s.text_frame.text for s in slide.shapes if s.has_text_frame]`.

## What these libraries cannot do

They edit the file format; they do not render it. Page counts, line wrapping and how a slide looks are unknown without `soffice`. When `## Environment` says it is not installed, tell the user that the layout was not checked rather than implying it was, and do not spend rounds trying to measure it.

## PDF

With `soffice`, convert the document: `soffice --headless --convert-to pdf out.docx`.

Without it, Office files cannot become PDF. Write the same content as an HTML file and print that with the `chrome` path from `## Environment`:

```
"<chrome>" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf=out.pdf "file://$PWD/out.html"
```

`<div style="page-break-before:always">` starts a new page. Count pages with `grep -c "/Type /Page[^s]" out.pdf`, and stop adjusting once the page limit is met: exact layout is not the deliverable.
