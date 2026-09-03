"""Make scanned PDFs searchable via OCRmyPDF (Tesseract under the hood).

Tenders frequently arrive as image-only scanned PDFs — the workspace image's
poppler can only pull *embedded* text, so a scan reads as empty. This sidecar
runs OCRmyPDF to add an invisible text layer, producing a searchable PDF the
agent (and downstream tools) can then extract from.

Importable contract:

    from pathlib import Path
    from src.ocr_convert import ocr, OcrError

    out = ocr(Path("/home/agent/scan.pdf"))   # -> /home/agent/scan.ocr.pdf

Like the office sidecar's converter, this owns the subprocess flag set, a hard
timeout with process-group SIGKILL (OCRmyPDF spawns Ghostscript/Tesseract
children), and output verification.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_OCRMYPDF_CANDIDATES = ("ocrmypdf",)

# OCR is CPU-heavy: a dense 30-page scan can take ~1 min on one core. 300s
# leaves room for a large tender scan without letting a wedged run hold a chat
# pod forever (the sidecar has its own cgroup, but still).
_DEFAULT_TIMEOUT_S = 300.0

# Tesseract language packs installed in the image. ``eng`` is always present;
# extend the Dockerfile apt set + this tuple together if a tender corpus needs
# another language.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("eng",)


class OcrError(RuntimeError):
    """OCR failed: missing binary, bad source, unsupported language, ocrmypdf
    non-zero exit, no output produced, or timeout. ``stderr`` carries
    ocrmypdf's last words when relevant."""

    def __init__(self, msg: str, *, stderr: str | None = None) -> None:
        super().__init__(msg)
        self.stderr = stderr


def _find_ocrmypdf() -> str:
    for name in _OCRMYPDF_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise OcrError(
        "ocrmypdf not on PATH — install ocrmypdf + tesseract-ocr or run inside "
        "the workspace-tool-ocr image"
    )


def _run_with_timeout(argv: list[str], *, timeout_s: float) -> tuple[int, str]:
    """Run ``argv`` with a hard timeout; SIGKILL the whole process group on
    timeout (ocrmypdf forks Ghostscript/Tesseract, so a plain kill leaks
    children). Returns ``(exit_code, stderr_text)``."""
    started = time.monotonic()
    # argv is built here from a resolved binary + static flags + caller Paths;
    # shell=False so no interpolation escape.
    proc = subprocess.Popen(  # noqa: S603 - argv source is trusted, see comment above
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr_b = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        try:
            _, stderr_b = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stderr_b = b""
        elapsed = time.monotonic() - started
        raise OcrError(
            f"ocrmypdf timed out after {elapsed:.1f}s (limit {timeout_s:.1f}s)",
            stderr=stderr_b.decode("utf-8", errors="replace"),
        ) from None
    return proc.returncode, stderr_b.decode("utf-8", errors="replace")


def ocr(
    src: Path,
    dst: Path | None = None,
    *,
    language: str = "eng",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Path:
    """Add a searchable text layer to a scanned PDF.

    ``src`` is a PDF (image-only or mixed). ``dst`` defaults to
    ``<src.stem>.ocr.pdf`` next to the source — never overwrites ``src``.
    ``--skip-text`` is used so pages that already have text are passed through
    untouched (OCR only the image pages), which is the right default for mixed
    tender documents. Returns the output path.

    Raises ``OcrError`` for any failure (binary missing, source missing/not a
    PDF, unsupported language, ocrmypdf non-zero exit, no output, timeout).
    """
    if language not in SUPPORTED_LANGUAGES:
        raise OcrError(
            f"unsupported language {language!r}; installed: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    if not src.exists():
        raise OcrError(f"source does not exist: {src}")
    if not src.is_file():
        raise OcrError(f"source is not a file: {src}")

    binary = _find_ocrmypdf()
    out = dst if dst is not None else src.with_suffix(".ocr.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        binary,
        "--skip-text",  # leave existing-text pages alone; OCR image pages only
        "--language",
        language,
        str(src),
        str(out),
    ]
    logger.info("ocr: %s -> %s (lang=%s)", src, out, language)
    rc, stderr = _run_with_timeout(argv, timeout_s=timeout_s)
    if rc != 0:
        raise OcrError(f"ocrmypdf exited {rc} on {src.name}", stderr=stderr)
    if not out.exists():
        raise OcrError(
            f"ocrmypdf produced no output for {src.name} (corrupt, encrypted, or not a PDF?)",
            stderr=stderr,
        )
    return out
