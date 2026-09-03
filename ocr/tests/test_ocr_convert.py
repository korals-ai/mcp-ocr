"""Tests for the OCR conversion logic — input-validation and error-mapping
paths that don't need a real ocrmypdf/tesseract (absent in CI). The binary
fork itself is exercised by the post-deploy integration suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ocr_convert import (
    SUPPORTED_LANGUAGES,
    OcrError,
    ocr,
)


def test_eng_is_supported() -> None:
    assert "eng" in SUPPORTED_LANGUAGES


def test_unsupported_language_rejected_before_disk(tmp_path: Path) -> None:
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(OcrError, match="unsupported language"):
        ocr(src, language="zzz")


def test_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(OcrError, match="source does not exist"):
        ocr(tmp_path / "nope.pdf")


def test_directory_source_raises(tmp_path: Path) -> None:
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(OcrError, match="source is not a file"):
        ocr(d)


def test_missing_binary_raises_with_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.ocr_convert as oc

    monkeypatch.setattr(oc.shutil, "which", lambda _name: None)
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(OcrError, match="not on PATH"):
        ocr(src)


def test_default_output_path_is_ocr_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub the subprocess run so we exercise the path logic without ocrmypdf:
    # fake a success that "writes" the expected output.
    import src.ocr_convert as oc

    monkeypatch.setattr(oc.shutil, "which", lambda _name: "/usr/bin/ocrmypdf")

    def fake_run(argv, *, timeout_s):
        out = Path(argv[-1])
        out.write_bytes(b"%PDF-1.4\nocr\n")
        return 0, ""

    monkeypatch.setattr(oc, "_run_with_timeout", fake_run)
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = ocr(src)
    assert out == tmp_path / "scan.ocr.pdf"
    assert out.exists()
