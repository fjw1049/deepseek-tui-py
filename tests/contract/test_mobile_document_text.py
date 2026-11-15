import io
import zipfile

import pytest

from deepseek_tui.mobile.document_text import MAX_TEXT, extract_document_text
from deepseek_tui.mobile.files import _upload


def test_docx_paragraphs_tables_and_upload_integration(tmp_path):
    import base64

    from docx import Document

    document = Document()
    document.add_paragraph("用户上传的项目说明")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "范围"
    table.cell(0, 1).text = "只做离线验证"
    output = io.BytesIO()
    document.save(output)
    result = _upload(
        tmp_path,
        "document-thread",
        {"name": "说明.docx", "data_base64": base64.b64encode(output.getvalue()).decode()},
    )
    assert result["parser_available"] is True
    assert "项目说明" in result["text_preview"] and "范围 | 只做离线验证" in result["text_preview"]
    assert (tmp_path / result["path"]).is_file()
    assert result["preview_truncated"] is False


def test_xlsx_formulas_are_text_and_rows_are_bounded():
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["项目", "数值"])
    sheet.append(["预算", "=1+2"])
    for i in range(205):
        sheet.append([f"row{i}", i])
    output = io.BytesIO()
    book.save(output)
    result = extract_document_text(output.getvalue(), "data.xlsx")
    assert result["parser_available"] is True
    assert "=1+2" in result["text_preview"]
    assert "row204" not in result["text_preview"]
    assert result["preview_truncated"] is True


def test_pptx_text_and_table():
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "实施计划"
    table = slide.shapes.add_table(1, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "阶段"
    table.cell(0, 1).text = "手机联调"
    output = io.BytesIO()
    deck.save(output)
    result = extract_document_text(output.getvalue(), "slides.pptx")
    assert "实施计划" in result["text_preview"] and "阶段 | 手机联调" in result["text_preview"]
    assert not result["preview_error"]


def test_office_xml_entities_and_zip_bomb_rejected():
    for payload in [
        b'<!DOCTYPE doc [<!ENTITY e SYSTEM "file:///etc/passwd">]><doc>&e;</doc>',
        b"A" * (17 * 1024 * 1024),
    ]:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", payload)
        result = extract_document_text(output.getvalue(), "unsafe.docx")
        assert result["text_preview"] == ""
        assert result["preview_error"]


def test_preview_character_limit_and_missing_pdf_parser(monkeypatch):
    from docx import Document

    document = Document()
    document.add_paragraph("文字" * (MAX_TEXT + 1))
    output = io.BytesIO()
    document.save(output)
    result = extract_document_text(output.getvalue(), "long.docx")
    assert len(result["text_preview"]) <= MAX_TEXT and result["preview_truncated"]
    monkeypatch.setattr("deepseek_tui.mobile.document_text.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "deepseek_tui.mobile.document_text.importlib.util.find_spec", lambda _: None
    )
    result = extract_document_text(b"%PDF-1.4\n%%EOF", "sample.pdf")
    assert result["parser_available"] is False and "pdftotext" in result["preview_error"]


def test_invalid_file_is_saved_but_reported_without_successful_preview(tmp_path):
    import base64

    result = _upload(
        tmp_path,
        "document-thread",
        {"name": "broken.docx", "data_base64": base64.b64encode(b"not a zip").decode()},
    )
    assert (tmp_path / result["path"]).is_file()
    assert result["preview_error"] and result["text_preview"] == ""


def make_pdf(*, pages=1, encrypted=False, large_stream=False):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for index in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            (b" " * (5 * 1024 * 1024) if large_stream else b"")
            + f"BT /F1 12 Tf 72 720 Td (Hello mobile PDF page {index + 1}) Tj ET".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(
            stream.flate_encode() if large_stream else stream
        )
    if encrypted:
        writer.encrypt("private-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_actual_text_in_resource_limited_subprocess():
    pytest.importorskip("pypdf")
    result = extract_document_text(make_pdf(), "actual.pdf")
    assert result["parser_available"] is True
    assert result["preview_error"] is None, result
    assert "Hello mobile PDF page 1" in result["text_preview"]
    assert result["preview_truncated"] is False


def test_pdf_page_limit_and_encrypted_document():
    pytest.importorskip("pypdf")
    result = extract_document_text(make_pdf(pages=21), "long.pdf")
    assert "page 20" in result["text_preview"] and "page 21" not in result["text_preview"]
    assert result["preview_truncated"] is True
    locked = extract_document_text(make_pdf(encrypted=True), "locked.pdf")
    assert locked["text_preview"] == "" and "密码" in locked["preview_error"]


def test_pdf_rejects_large_decompressed_page_and_reports_ocr():
    pypdf = pytest.importorskip("pypdf")
    result = extract_document_text(make_pdf(large_stream=True), "compressed.pdf")
    assert result["text_preview"] == "" and "4 MiB" in result["preview_error"]
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    empty = extract_document_text(output.getvalue(), "scan.pdf")
    assert empty["text_preview"] == "" and "OCR" in empty["preview_error"]


def test_pdf_worker_timeout_is_explicit(monkeypatch):
    import subprocess

    pytest.importorskip("pypdf")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("pdf-worker", 12)

    monkeypatch.setattr("deepseek_tui.mobile.document_text.subprocess.run", timeout)
    result = extract_document_text(b"%PDF-1.4", "timeout.pdf")
    assert "超时" in result["preview_error"]
