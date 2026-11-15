"""Bounded document text previews using the Runtime's existing Office libraries.

No macro execution, external links, formula calculation, OCR, or package installs.
The caller passes already validated uploaded bytes, never a client-selected path.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

MAX_INPUT = 8 * 1024 * 1024
MAX_TEXT = 12000
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 1500
FORMATS = {".docx", ".xlsx", ".pptx", ".pdf"}


class Preview:
    def __init__(self):
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def add(self, value: object):
        line = str(value).strip()
        if not line:
            return
        room = MAX_TEXT - self.size
        if room <= 0:
            self.truncated = True
            return
        self.parts.append(line[:room])
        self.size += len(line[:room]) + 1
        if len(line) > room:
            self.truncated = True

    @property
    def full(self):
        return self.size >= MAX_TEXT


def _validate_zip(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError("Office archive has too many entries")
        total = 0
        for info in entries:
            total += info.file_size
            if total > MAX_ZIP_BYTES or info.file_size > 16 * 1024 * 1024:
                raise ValueError("Office archive expanded size exceeds preview limits")
            if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Encrypted or symbolic-link Office entries are unsupported")
            if info.file_size > max(1, info.compress_size) * 1000:
                raise ValueError("Office archive compression ratio exceeds preview limits")
            if info.filename.lower().endswith((".xml", ".rels")):
                # Validate every XML part before the library sees it; no entity expansion.
                with archive.open(info) as stream:
                    xml = stream.read(min(info.file_size, 16 * 1024 * 1024) + 1)
                if len(xml) > info.file_size:
                    raise ValueError("Office archive size declaration mismatch")
                lowered = xml.replace(b"\x00", b"").lower()
                if b"<!doctype" in lowered or b"<!entity" in lowered:
                    raise ValueError("Office XML document types and entities are unsupported")


def _docx(data: bytes, out: Preview):
    from docx import Document

    document = Document(io.BytesIO(data))
    # iter_inner_content preserves paragraph/table order in python-docx >= 1.1.
    from docx.table import Table

    for index, block in enumerate(document.iter_inner_content()):
        if index >= 500 or out.full:
            out.truncated = True
            break
        if isinstance(block, Table):
            for row_index, row in enumerate(block.rows):
                if row_index >= 200 or out.full:
                    out.truncated = True
                    break
                out.add(" | ".join(cell.text for cell in row.cells[:50]))
                if len(row.cells) > 50:
                    out.truncated = True
        else:
            out.add(block.text)


def _xlsx(data: bytes, out: Preview):
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        for index, sheet in enumerate(book.worksheets):
            if index >= 10 or out.full:
                out.truncated = True
                break
            out.add(f"[工作表：{sheet.title}]")
            # Formulas are shown as text; they are never evaluated.
            if (sheet.max_row or 0) > 200 or (sheet.max_column or 0) > 50:
                out.truncated = True
            for row in sheet.iter_rows(
                max_row=min(sheet.max_row or 200, 200),
                max_col=min(sheet.max_column or 50, 50),
                values_only=True,
            ):
                out.add(" | ".join("" if value is None else str(value) for value in row))
                if out.full:
                    out.truncated = True
                    break
    finally:
        book.close()


def _pptx(data: bytes, out: Preview):
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    for index, slide in enumerate(deck.slides):
        if index >= 50 or out.full:
            out.truncated = True
            break
        out.add(f"[幻灯片 {index + 1}]")
        for shape_index, shape in enumerate(slide.shapes):
            if shape_index >= 200 or out.full:
                out.truncated = True
                break
            if shape.has_text_frame:
                out.add(shape.text_frame.text)
            if shape.has_table:
                for row_index, row in enumerate(shape.table.rows):
                    if row_index >= 200 or out.full:
                        out.truncated = True
                        break
                    out.add(" | ".join(cell.text for cell in list(row.cells)[:50]))
                    if len(row.cells) > 50:
                        out.truncated = True


def _pdf(data: bytes, out: Preview, executable: str):
    with tempfile.TemporaryDirectory(prefix="mobile-pdf-preview-") as directory:
        source = Path(directory) / "input.pdf"
        source.write_bytes(data)
        process = subprocess.Popen(
            [executable, "-f", "1", "-l", "20", "-enc", "UTF-8", str(source), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        captured = bytearray()
        deadline = time.monotonic() + 10
        try:
            assert process.stdout is not None
            fd = process.stdout.fileno()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("PDF text extraction timed out")
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    raise ValueError("PDF text extraction timed out")
                chunk = os.read(fd, min(8192, MAX_TEXT * 4 + 1 - len(captured)))
                if not chunk:
                    break
                captured.extend(chunk)
                if len(captured) > MAX_TEXT * 4:
                    out.truncated = True
                    break
            if process.poll() is None and out.truncated:
                process.kill()
            code = process.wait(timeout=2)
            if code and not out.truncated:
                raise ValueError("PDF may be encrypted or invalid")
            # pdftotext uses form feeds between pages. We do not inspect beyond 20.
            decoded = captured.decode("utf-8", errors="replace")
            if decoded.count("\f") >= 20:
                out.truncated = True
            out.add(decoded)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()


class PdfPreviewError(ValueError):
    """A fixed, safe diagnostic that may be shown to the user."""


def _pdf_library(data: bytes, out: Preview):
    # Spawn instead of preexec_fn: this function is called from a worker thread.
    # Resource limits are set inside the child before importing the PDF parser.
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--pdf-worker"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfPreviewError("PDF 正文解析超时；文件已保存。") from exc
    if result.returncode:
        raise PdfPreviewError("PDF 解析超出资源限制或失败；文件已保存。")
    payload = json.loads(result.stdout)
    if payload.get("error"):
        raise PdfPreviewError(payload["error"])
    out.add(payload["text"])
    out.truncated = out.truncated or payload["truncated"]


def _pdf_worker() -> dict:
    import resource

    # Separate process: native parser allocations and decompression cannot OOM
    # the HTTP Runtime. CPU and wall-clock limits cover malformed page trees.
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_DATA, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ValueError, OSError):
        if sys.platform != "darwin":
            raise
        # Darwin rejects finite RLIMIT_AS/RLIMIT_DATA with EINVAL. Watch actual
        # resident usage there; parser allocation/decompression caps below are
        # the primary bounds, not an unsupported OS virtual-memory claim.
        import threading

        def watch_memory():
            while True:
                if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 512 * 1024 * 1024:
                    os._exit(70)
                time.sleep(0.02)

        threading.Thread(target=watch_memory, daemon=True).start()
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    from pypdf import PdfReader, overwrite_configuration

    overwrite_configuration(
        maximum_declared_stream_length=4 * 1024 * 1024,
        array_based_stream_maximum_output_length=4 * 1024 * 1024,
        zlib_maximum_output_length=4 * 1024 * 1024,
        lzw_maximum_output_length=4 * 1024 * 1024,
        run_length_maximum_output_length=4 * 1024 * 1024,
        brotli_maximum_output_length=4 * 1024 * 1024,
        image_maximum_buffer_size=4 * 1024 * 1024,
        array_maximum_element_count=10000,
        dictionary_maximum_element_count=10000,
        stream_decoding_work_maximum_length=16 * 1024 * 1024,
        stream_parsing_work_maximum_count=100000,
        page_tree_maximum_entries=1000,
        page_tree_maximum_page_entries=20000,
        page_tree_maximum_depth=30,
        xform_maximum_invocations_per_extraction=100,
        jbig2dec_binary=None,
    )

    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        return {"error": "PDF 超过 8 MiB 限制；文件已保存。"}
    reader = PdfReader(
        io.BytesIO(data),
        strict=False,
        root_object_recovery_limit=1000,
        xref_stream_maximum_entries=50000,
    )
    if reader.is_encrypted:
        return {"error": "PDF 已加密，需要密码才能读取正文；文件已保存。"}
    out = Preview()
    for index, page in enumerate(reader.pages):
        if index >= 20 or out.full:
            out.truncated = True
            break
        # Decompression itself is also confined by the child memory/time budget.
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 4 * 1024 * 1024:
            return {"error": "PDF 单页解压内容超过 4 MiB 预览限制；文件已保存。"}
        out.add(page.extract_text() or "")
    return {"text": "\n".join(out.parts)[:MAX_TEXT], "truncated": out.truncated}


def extract_document_text(data: bytes, filename: str) -> dict:
    kind = Path(filename).suffix.lower()
    result = {
        "text_preview": "",
        "preview_truncated": False,
        "parser_available": False,
        "preview_format": kind.lstrip("."),
        "preview_error": None,
    }
    if kind not in FORMATS:
        return result
    if len(data) > MAX_INPUT:
        return {**result, "preview_error": "文档超过 8 MiB 正文预览限制"}
    pdf_library = kind == ".pdf" and importlib.util.find_spec("pypdf") is not None
    executable = shutil.which("pdftotext") if kind == ".pdf" else None
    if kind == ".pdf" and not (pdf_library or executable):
        return {
            **result,
            "preview_error": "电脑缺少 pypdf 或 pdftotext，PDF 已保存，但无法提取正文。",
        }
    out = Preview()
    try:
        if kind != ".pdf":
            _validate_zip(data)
        result["parser_available"] = True
        if kind == ".docx":
            _docx(data, out)
        elif kind == ".xlsx":
            _xlsx(data, out)
        elif kind == ".pptx":
            _pptx(data, out)
        elif pdf_library:
            _pdf_library(data, out)
        else:
            _pdf(data, out, executable)
        result.update(text_preview="\n".join(out.parts)[:MAX_TEXT], preview_truncated=out.truncated)
        if not out.parts:
            result["preview_error"] = "未提取到正文；扫描件需要 OCR，嵌入内容可能不支持。"
    except PdfPreviewError as exc:
        result["preview_error"] = str(exc)
    except ImportError:
        result.update(
            parser_available=False, preview_error="电脑缺少对应 Office 解析库，文件已保存。"
        )
    except Exception as exc:
        # Do not echo internal parser tracebacks or document bytes to the client.
        result["preview_error"] = f"无法生成文档正文预览（{type(exc).__name__}）；文件已保存。"
    return result


if __name__ == "__main__" and sys.argv[1:] == ["--pdf-worker"]:
    try:
        output = _pdf_worker()
    except MemoryError:
        output = {"error": "PDF 解析超出内存限制；文件已保存。"}
    except Exception as exc:
        output = {
            "error": "PDF 超出单流 4 MiB 或结构解析限制；文件已保存。"
            if type(exc).__name__ == "LimitReachedError"
            else "PDF 损坏或无法解析；文件已保存。"
        }
    print(json.dumps(output, ensure_ascii=True))
