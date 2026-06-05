"""ColPali strict PDF loader tests (mocked â€” no GPU required)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from template_engine.ingestion.pdf_loader import PageData, TextBlock, load_pdf, pdf_parser_mode


def test_pdf_parser_mode_default_colpali(monkeypatch):
    monkeypatch.delenv("PDF_PARSER", raising=False)
    assert pdf_parser_mode() == "colpali"


@patch("template_engine.ingestion.colpali_runtime.extract_pdf_colpali_inprocess")
def test_load_pdf_strict_colpali_uses_colpali(mock_extract, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_PARSER", "colpali")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")

    mock_extract.return_value = [
        PageData(
            page_index=0,
            width=612,
            height=792,
            text_blocks=[TextBlock(text="Chapter 1", font_size=14, bold=True)],
            raw_text="Chapter 1",
        )
    ]

    with patch("template_engine.ingestion.pdf_loader._load_pdfplumber") as mock_plum:
        pages, method = load_pdf(pdf, strict_colpali=True)
        mock_plum.assert_not_called()

    assert method == "colpali"
    assert len(pages) == 1
    assert pages[0].raw_text == "Chapter 1"
    mock_extract.assert_called_once()


@patch("template_engine.ingestion.colpali_runtime.extract_pdf_colpali_inprocess")
def test_load_pdf_strict_raises_when_colpali_fails(mock_extract, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_PARSER", "colpali")
    monkeypatch.setenv("COLPALI_ALLOW_SIDECAR", "false")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    mock_extract.side_effect = RuntimeError("ColPali model load failed")

    with pytest.raises(RuntimeError, match="ColPali extraction failed"):
        load_pdf(pdf, strict_colpali=True)


@patch("template_engine.ingestion.colpali_runtime.extract_pdf_colpali_inprocess")
def test_load_pdf_legacy_uses_pdfplumber_when_colpali_unavailable(mock_extract, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_PARSER", "legacy")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    mock_extract.return_value = None

    fake_page = PageData(page_index=0, width=100, height=100, raw_text="legacy text")

    with patch("template_engine.ingestion.pdf_loader._load_pdfplumber", return_value=[fake_page]):
        pages, method = load_pdf(pdf)
        assert method == "pdfplumber"
        assert pages[0].raw_text == "legacy text"

@patch("template_engine.ingestion.colpali_runtime._load_structural_pages")
@patch("template_engine.ingestion.colpali_runtime._run_colpali_vision_pass")
@patch("template_engine.ingestion.colpali_runtime.get_colpali_processor")
@patch("template_engine.ingestion.colpali_runtime.get_colpali_model")
@patch("template_engine.ingestion.colpali_runtime._rasterize_pdf_pages")
@patch("template_engine.ingestion.colpali_runtime._pdf_page_count", return_value=2)
def test_extract_uses_processor_not_module_process_images(
    mock_page_count,
    mock_raster,
    mock_model,
    mock_processor,
    mock_vision,
    mock_structural,
    tmp_path,
):
    from template_engine.ingestion.colpali_runtime import extract_pdf_colpali_inprocess
    from template_engine.ingestion.pdf_loader import PageData, TextBlock

    pdf = tmp_path / "t.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    mock_raster.return_value = [object()]
    mock_structural.return_value = [
        PageData(page_index=0, width=100, height=100, text_blocks=[TextBlock(text="Hi")], raw_text="Hi")
    ]

    pages = extract_pdf_colpali_inprocess(pdf)
    assert len(pages) == 1
    assert mock_vision.call_count == 2
    assert mock_raster.call_count == 2
    mock_structural.assert_called_once_with(pdf)
